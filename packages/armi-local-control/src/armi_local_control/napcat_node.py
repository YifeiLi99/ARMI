"""Pinned, optional NapCat Node distribution and its environment-owned process."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx
import psutil
from armi_kernel import load_yaml_mapping

from .configuration.paths import has_reparse_point
from .native_postgresql import private_directory, write_control
from .process_identity import ManagedProcessIdentity, ManagedProcessState
from .runtime_errors import RuntimeViolation
from .runtime_process import LocalProcessLock
from .windows_package import spawn_owned

# The newer 4.18.19 Node asset omits crypto.dll/ssl.dll required by its wrapper.
VERSION = "4.18.9"
ARCHIVE_SIZE = 114832420
ARCHIVE_SHA256 = "234f2b9341d355d107881ce486d6699f529300d644282e25af452717d00a50da"
ARCHIVE_URL = (
    "https://github.com/NapNeko/NapCatQQ/releases/download/v"
    + VERSION
    + "/NapCat.Shell.Windows.Node.zip"
)
_REQUIRED = ("node.exe", "index.js", "wrapper.node", "QQNT.dll", "napcat/napcat.mjs")


def _fail(code: str) -> RuntimeViolation:
    return RuntimeViolation("NAPCAT-" + code, "The managed QQ component is unavailable")


def _extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if (
            len(entries) > 30000
            or sum(entry.file_size for entry in entries) > 2 * 1024**3
        ):
            raise _fail("ARCHIVE-LIMIT")
        names: set[str] = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            name = entry.filename.rstrip("/").casefold()
            if (
                not name
                or name in names
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or stat.S_ISLNK(entry.external_attr >> 16)
                or any(
                    part.endswith((".", " ")) or os.path.isreserved(part)
                    for part in path.parts
                )
            ):
                raise _fail("ARCHIVE-PATH")
            names.add(name)
        for entry in entries:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


class NapCatNode:
    def __init__(self, environment: Path) -> None:
        self.environment = environment
        self.root = environment / "tools/napcat"
        self.control = environment / ".setup"
        self.progress_path = self.control / "napcat-install.json"
        self.process_path = environment / "run/napcat-node.json"
        for path in (self.root, self.control, self.process_path):
            if has_reparse_point(path, root=Path(path.anchor)):
                raise _fail("LOCAL-PATH")

    def installed(self) -> bool:
        marker = self.root / "armi-component.json"
        if has_reparse_point(marker, root=Path(marker.anchor)):
            raise _fail("LOCAL-PATH")
        if not marker.is_file():
            return False
        value = json.loads(marker.read_bytes())
        if value != {"version": VERSION, "sha256": ARCHIVE_SHA256}:
            raise _fail("COMPONENT-VERSION")
        for relative in _REQUIRED:
            path = self.root / relative
            if not path.is_file() or has_reparse_point(path, root=self.root):
                raise _fail("COMPONENT-INCOMPLETE")
        return True

    def progress(self, phase: str, **values: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"status": phase, "version": VERSION, **values}
        private_directory(self.control)
        write_control(self.progress_path, result)
        return result

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = (
            json.loads(self.progress_path.read_bytes())
            if self.progress_path.exists()
            else {}
        )
        result["installed"] = self.installed()
        result.setdefault(
            "status", "installed" if result["installed"] else "not_installed"
        )
        result["version"] = VERSION
        return result

    def install(self, environment_id: str) -> dict[str, Any]:
        private_directory(self.control)
        with LocalProcessLock(self.control / "napcat-install.lock"):
            if self.installed():
                return self.progress("installed")
            if self.root.exists():
                raise _fail("EXISTING-INSTALLATION")
            private_directory(self.root.parent)
            try:
                with tempfile.TemporaryDirectory(
                    prefix=".napcat-", dir=self.root.parent
                ) as temporary:
                    stage = Path(temporary)
                    archive = stage / "component.zip"
                    self._download(archive)
                    self.progress("extracting")
                    payload = stage / "payload"
                    payload.mkdir()
                    _extract(archive, payload)
                    if any(
                        not (payload / relative).is_file() for relative in _REQUIRED
                    ):
                        raise _fail("COMPONENT-INCOMPLETE")
                    self.progress("verifying")
                    shutil.copyfile(
                        Path(sys.base_prefix) / "vcruntime140.dll",
                        payload / "vcruntime140.dll",
                    )
                    # This bounded installer probe must not bind the persistent
                    # environment Job to the short-lived installer invocation.
                    probe = subprocess.run(
                        (
                            str(payload / "node.exe"),
                            "-e",
                            'const w=require("./wrapper.node");'
                            "const p=w.NodeQQNTWrapperUtil.getNTUserDataInfoConfig();"
                            "if(p)process.exit(2);"
                            'console.log("armi-napcat-native-ready");process.exit(0);',
                        ),
                        cwd=payload,
                        env=self._process_environment(payload),
                        capture_output=True,
                        timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if (
                        probe.returncode != 0
                        or probe.stdout.strip() != b"armi-napcat-native-ready"
                    ):
                        raise _fail("NATIVE-UNAVAILABLE")
                    write_control(
                        payload / "armi-component.json",
                        {"version": VERSION, "sha256": ARCHIVE_SHA256},
                    )
                    payload.rename(self.root)
                return self.progress("installed")
            except (
                OSError,
                ValueError,
                httpx.HTTPError,
                zipfile.BadZipFile,
                RuntimeViolation,
                subprocess.TimeoutExpired,
            ) as error:
                code = (
                    error.code
                    if isinstance(error, RuntimeViolation)
                    else "NAPCAT-INSTALL-FAILED"
                )
                self.progress("failed", error_code=code)
                raise _fail(code.removeprefix("NAPCAT-")) from None

    def _download(self, path: Path) -> None:
        self.progress("downloading", received=0, total=ARCHIVE_SIZE)
        # Explicit official-direct installation: no inherited proxy or mirror.
        with httpx.Client(trust_env=False, timeout=30.0) as client:
            url = ARCHIVE_URL
            for _ in range(5):
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname not in {
                    "github.com",
                    "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com",
                }:
                    raise _fail("DOWNLOAD-ORIGIN")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    digest = hashlib.sha256()
                    received = 0
                    observed = time.monotonic()
                    with path.open("xb") as output:
                        for block in response.iter_bytes(1024 * 1024):
                            received += len(block)
                            if received > ARCHIVE_SIZE:
                                raise _fail("DOWNLOAD-SIZE")
                            output.write(block)
                            digest.update(block)
                            if time.monotonic() - observed >= 0.5:
                                self.progress(
                                    "downloading", received=received, total=ARCHIVE_SIZE
                                )
                                observed = time.monotonic()
                    if received != ARCHIVE_SIZE or digest.hexdigest() != ARCHIVE_SHA256:
                        raise _fail("DOWNLOAD-DIGEST")
                    return
            raise _fail("DOWNLOAD-REDIRECT")

    def _identity(self) -> ManagedProcessIdentity | None:
        if not self.process_path.exists():
            return None
        identity = ManagedProcessIdentity.from_wire(
            json.loads(self.process_path.read_bytes())
        )
        if identity.executable_identity != os.path.normcase(
            str((self.root / "node.exe").resolve())
        ):
            raise _fail("PROCESS-IDENTITY")
        return identity

    @staticmethod
    def _process_environment(root: Path) -> dict[str, str]:
        environment = {
            name: value
            for name in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE")
            if (value := os.environ.get(name)) is not None
        }
        for name, relative in {
            "USERPROFILE": "profile",
            "HOME": "profile",
            "APPDATA": "profile/roaming",
            "LOCALAPPDATA": "profile/local",
            "TEMP": "tmp",
            "TMP": "tmp",
        }.items():
            directory = root / relative
            private_directory(directory)
            environment[name] = str(directory)
        environment["NAPCAT_WORKDIR"] = str(root)
        return environment

    def start(self, environment_id: str) -> dict[str, Any]:
        if not self.installed():
            return {"status": "not_installed"}
        config = self.environment / "channels/qq-napcat.yaml"
        if (
            not config.is_file()
            or load_yaml_mapping(config.read_bytes()).get("enabled") is not True
        ):
            return {"status": "disabled"}
        private_directory(self.process_path.parent)
        with LocalProcessLock(self.process_path.with_suffix(".lock")):
            identity = self._identity()
            if identity is not None:
                state = identity.inspect()
                if state == ManagedProcessState.MATCHES:
                    if identity.environment_identity != environment_id:
                        raise _fail("PROCESS-IDENTITY")
                    return {"status": "already_running"}
                if state != ManagedProcessState.ABSENT:
                    raise _fail("PROCESS-IDENTITY")
            environment = self._process_environment(self.root)
            with (self.root / "launcher.log").open("ab") as output:
                process = spawn_owned(
                    (str(self.root / "node.exe"), str(self.root / "index.js")),
                    environment_id=environment_id,
                    cwd=self.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            try:
                identity = ManagedProcessIdentity.capture(
                    process.pid, environment_identity=environment_id, incarnation=1
                )
                write_control(self.process_path, identity.to_wire())
            except BaseException:
                process.kill()
                process.wait(timeout=10)
                raise
            return {"status": "started"}

    def stop(self) -> dict[str, Any]:
        if not self.process_path.exists():
            return {"status": "stopped"}
        with LocalProcessLock(self.process_path.with_suffix(".lock")):
            identity = self._identity()
            if identity is None:
                return {"status": "stopped"}
            state = identity.inspect()
            if state == ManagedProcessState.MATCHES:
                process = psutil.Process(identity.pid)
                children = process.children(recursive=True)
                process.terminate()
                for child in children:
                    with suppress(psutil.NoSuchProcess):
                        child.terminate()
                _, alive = psutil.wait_procs([process, *children], timeout=10)
                if alive:
                    raise _fail("STOP-UNCONFIRMED")
            elif state != ManagedProcessState.ABSENT:
                raise _fail("PROCESS-IDENTITY")
            self.process_path.unlink(missing_ok=True)
            return {"status": "stopped"}


__all__ = ("NapCatNode",)
