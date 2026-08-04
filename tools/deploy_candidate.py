"""Install and atomically activate an immutable ARMI candidate."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7
from zipfile import ZipFile

try:
    from tools.candidate_bundle import (
        COMPOSITION_MANIFEST,
        SCHEMA_MANIFEST,
        CandidateError,
        canonical_bytes,
        sha256_bytes,
        sha256_file,
        verify_bundle,
    )
except ModuleNotFoundError:
    from candidate_bundle import (  # type: ignore[no-redef]
        COMPOSITION_MANIFEST,
        SCHEMA_MANIFEST,
        CandidateError,
        canonical_bytes,
        sha256_bytes,
        sha256_file,
        verify_bundle,
    )

INSTALLATION_SCHEMA = "armi.candidate-installation.v1"
DEPLOYMENT_SCHEMA = "armi.deployment-state.v1"
PENDING_SCHEMA = "armi.deployment-pending.v1"

_PROJECTION = r"""
import hashlib, importlib.metadata, importlib.resources, json, os, shutil, sys
expected = json.loads(os.environ["ARMI_INSTALL_EXPECTED"])
versions = {}
entries = {}
for name in expected["versions"]:
    dist = importlib.metadata.distribution(name)
    versions[name] = dist.version
    entries[name] = sorted(
        [entry.name, entry.value]
        for entry in dist.entry_points
        if entry.group == "console_scripts"
    )
resources = {}
for package, relative in expected["resources"]:
    data = importlib.resources.files(package).joinpath(relative).read_bytes()
    resources[relative] = "sha256:" + hashlib.sha256(data).hexdigest()
path_parts = [os.path.normcase(os.path.abspath(item)) for item in sys.path]
forbidden = {
    os.path.normcase(os.path.abspath(item)) for item in expected["forbidden_roots"]
}
if any(item in forbidden for item in path_parts):
    raise SystemExit("DEP-SOURCE-PATH")
if shutil.which("node") is not None or shutil.which("npm") is not None:
    raise SystemExit("DEP-NODE-PATH")
print(json.dumps({"entry_points": entries, "resources": resources, "versions": versions}, sort_keys=True, separators=(",", ":")))
"""


class DeploymentError(ValueError):
    """A stable candidate deployment failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    code: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=None if environment is None else dict(environment),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise DeploymentError(code, detail[-1] if detail else "command failed")
    return completed.stdout.strip()


def _is_reparse(path: Path) -> bool:
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except AttributeError, OSError:
        return path.is_symlink()


def _require_directory(path: Path, code: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or _is_reparse(resolved):
        raise DeploymentError(code, "directory is unavailable or is a reparse point")
    return resolved


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical_bytes(value))
    temporary.replace(path)


def _strict_json(path: Path, code: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeploymentError(code, "deployment metadata is unreadable") from error
    if not isinstance(value, dict) or canonical_bytes(value) != raw:
        raise DeploymentError(code, "deployment metadata is not canonical")
    return cast(dict[str, Any], value)


def _projection(
    installation: Path,
    identity: dict[str, Any],
    *,
    forbidden_root: Path,
) -> dict[str, Any]:
    bundle = cast(dict[str, Any], identity["bundle_identity"])
    expected = {
        "versions": {
            item["distribution"]: item["version"] for item in bundle["wheels"]
        },
        "resources": [
            ["armi_runtime.interfaces.creator_web_resources", "manifest.json"],
            [
                "armi_runtime.composition.runtime_resources",
                SCHEMA_MANIFEST.removeprefix(
                    "armi_runtime/composition/runtime_resources/"
                ),
            ],
            [
                "armi_runtime.composition.runtime_resources",
                COMPOSITION_MANIFEST.removeprefix(
                    "armi_runtime/composition/runtime_resources/"
                ),
            ],
        ],
        "forbidden_roots": [
            os.fspath(forbidden_root.resolve()),
            *[
                os.fspath(path.resolve())
                for path in (
                    forbidden_root / "apps/armi-runtime/src",
                    forbidden_root / "apps/armi-admin/src",
                    forbidden_root / "packages/armi-kernel/src",
                )
            ],
        ],
    }
    environment = {
        "ARMI_INSTALL_EXPECTED": json.dumps(expected, separators=(",", ":")),
        "PATH": os.pathsep.join(
            (
                os.fspath(installation / "venv/Scripts"),
                os.fspath(Path(os.environ["WINDIR"]) / "System32"),
            )
        ),
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "WINDIR": os.environ["WINDIR"],
        "TEMP": os.environ.get("TEMP", os.fspath(installation)),
        "TMP": os.environ.get("TMP", os.fspath(installation)),
    }
    output = _run(
        [
            os.fspath(installation / "venv/Scripts/python.exe"),
            "-I",
            "-c",
            _PROJECTION,
        ],
        cwd=installation,
        code="DEP-INSTALL-PROJECTION",
        environment=environment,
    )
    try:
        projection = json.loads(output)
    except json.JSONDecodeError as error:
        raise DeploymentError("DEP-INSTALL-PROJECTION", "invalid projection") from error
    if projection["versions"] != expected["versions"]:
        raise DeploymentError("DEP-INSTALL-VERSION", "installed versions drifted")
    expected_resources = {
        "manifest.json": bundle["creator_static"]["manifest_sha256"],
        SCHEMA_MANIFEST.removeprefix(
            "armi_runtime/composition/runtime_resources/"
        ): bundle["database_schema"]["manifest_sha256"],
        COMPOSITION_MANIFEST.removeprefix(
            "armi_runtime/composition/runtime_resources/"
        ): bundle["active_bindings"]["manifest_sha256"],
    }
    if projection["resources"] != expected_resources:
        raise DeploymentError("DEP-INSTALL-RESOURCE", "installed resources drifted")
    return cast(dict[str, Any], projection)


def _bundle_member_path(stage: Path, member: str) -> Path:
    target = stage / "bundle" / Path(*member.split("/"))
    resolved_parent = target.parent.resolve()
    bundle_root = (stage / "bundle").resolve()
    if resolved_parent != bundle_root and bundle_root not in resolved_parent.parents:
        raise DeploymentError("DEP-ARCHIVE-PATH", "archive member escaped staging")
    return target


def install(
    bundle_path: Path,
    deployment_root: Path,
    *,
    dependency_mode: str,
    repository_root: Path,
    tool_root: Path,
) -> dict[str, Any]:
    try:
        bundle_identity = verify_bundle(bundle_path.resolve(strict=True))
    except (CandidateError, OSError) as error:
        code = error.code if isinstance(error, CandidateError) else "DEP-BUNDLE-READ"
        raise DeploymentError(code, str(error)) from error
    deployment_root.mkdir(parents=True, exist_ok=True)
    root = _require_directory(deployment_root, "DEP-ROOT")
    bundle_id = cast(str, bundle_identity["bundle_id"])
    target = root / "installations" / bundle_id.removeprefix("sha256:")
    if target.exists():
        verified = verify_installation(target, forbidden_root=repository_root)
        if verified["bundle_id"] != bundle_id:
            raise DeploymentError("DEP-INSTALL-COLLISION", "installation differs")
        return {**verified, "installation": os.fspath(target), "reused": True}
    python = tool_root / "installs/python/cpython-3.14.6-windows-x86_64-none/python.exe"
    uv = tool_root / "installs/uv/0.11.33/uv.exe"
    if not python.is_file() or not uv.is_file():
        raise DeploymentError("DEP-INSTALL-TOOL", "pinned Python or uv is absent")
    staging_root = root / "staging"
    staging_root.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=staging_root))
    try:
        shutil.copyfile(bundle_path, stage / "candidate.zip")
        with ZipFile(bundle_path) as archive:
            for name in archive.namelist():
                target_member = _bundle_member_path(stage, name)
                target_member.parent.mkdir(parents=True, exist_ok=True)
                target_member.write_bytes(archive.read(name))
        _run(
            [os.fspath(python), "-m", "venv", os.fspath(stage / "venv")],
            cwd=stage,
            code="DEP-INSTALL-VENV",
        )
        requirements = stage / "bundle/locks/runtime-requirements.txt"
        dependency_command = [
            os.fspath(uv),
            "pip",
            "install",
            "--python",
            os.fspath(stage / "venv/Scripts/python.exe"),
            "--require-hashes",
        ]
        if dependency_mode == "offline":
            dependency_command.append("--offline")
        dependency_command.extend(("-r", os.fspath(requirements)))
        _run(
            dependency_command,
            cwd=stage,
            code="DEP-INSTALL-DEPENDENCIES",
            environment=os.environ,
        )
        wheels = sorted((stage / "bundle/wheels").glob("*.whl"))
        _run(
            [
                os.fspath(uv),
                "pip",
                "install",
                "--python",
                os.fspath(stage / "venv/Scripts/python.exe"),
                "--offline",
                "--no-index",
                "--no-deps",
                *[os.fspath(path) for path in wheels],
            ],
            cwd=stage,
            code="DEP-INSTALL-WHEELS",
        )
        provisional: dict[str, Any] = {
            "schema_version": INSTALLATION_SCHEMA,
            "bundle_id": bundle_id,
            "source_revision": bundle_identity["source_revision"],
            "archive_sha256": sha256_file(stage / "candidate.zip"),
            "python_version": "3.14.6",
            "uv_version": "0.11.33",
            "requirements_sha256": sha256_file(requirements),
            "bundle_identity": bundle_identity,
        }
        projection = _projection(stage, provisional, forbidden_root=repository_root)
        identity = {
            **provisional,
            "projection": projection,
            "projection_sha256": sha256_bytes(canonical_bytes(projection)),
        }
        (stage / "installation-identity.json").write_bytes(canonical_bytes(identity))
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.replace(target)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    verified = verify_installation(target, forbidden_root=repository_root)
    return {**verified, "installation": os.fspath(target), "reused": False}


def verify_installation(
    installation: Path, *, forbidden_root: Path | None = None
) -> dict[str, Any]:
    root = _require_directory(installation, "DEP-INSTALL-ROOT")
    identity = _strict_json(root / "installation-identity.json", "DEP-INSTALL-IDENTITY")
    if identity.get("schema_version") != INSTALLATION_SCHEMA:
        raise DeploymentError("DEP-INSTALL-IDENTITY", "installation schema drifted")
    if {path.name for path in root.iterdir()} != {
        "bundle",
        "candidate.zip",
        "installation-identity.json",
        "venv",
    }:
        raise DeploymentError("DEP-INSTALL-MEMBERS", "installation members drifted")
    bundle_path = root / "candidate.zip"
    try:
        bundle = verify_bundle(bundle_path)
    except CandidateError as error:
        raise DeploymentError(error.code, str(error)) from error
    if (
        identity.get("bundle_identity") != bundle
        or identity.get("bundle_id") != bundle.get("bundle_id")
        or identity.get("archive_sha256") != sha256_file(bundle_path)
    ):
        raise DeploymentError("DEP-INSTALL-IDENTITY", "bundle identity drifted")
    with ZipFile(bundle_path) as archive:
        expected_members = set(archive.namelist())
        actual_members = {
            path.relative_to(root / "bundle").as_posix()
            for path in (root / "bundle").rglob("*")
            if path.is_file()
        }
        if actual_members != expected_members:
            raise DeploymentError("DEP-INSTALL-MEMBERS", "extracted bundle drifted")
        for member in expected_members:
            extracted = root / "bundle" / Path(*member.split("/"))
            if _is_reparse(extracted) or extracted.read_bytes() != archive.read(member):
                raise DeploymentError("DEP-INSTALL-MEMBERS", "bundle member drifted")
    requirements = root / "bundle/locks/runtime-requirements.txt"
    if identity.get("requirements_sha256") != sha256_file(requirements):
        raise DeploymentError("DEP-INSTALL-IDENTITY", "requirements drifted")
    projection = _projection(
        root,
        identity,
        forbidden_root=forbidden_root or Path("__source_forbidden__"),
    )
    if identity.get("projection") != projection or identity.get(
        "projection_sha256"
    ) != sha256_bytes(canonical_bytes(projection)):
        raise DeploymentError("DEP-INSTALL-PROJECTION", "projection drifted")
    return {
        "status": "pass",
        "bundle_id": bundle["bundle_id"],
        "source_revision": bundle["source_revision"],
        "archive_sha256": identity["archive_sha256"],
        "projection_sha256": identity["projection_sha256"],
    }


def _environment_id(root: Path) -> str:
    environment = _require_directory(root, "DEP-ENVIRONMENT-ROOT")
    try:
        value = tomllib.loads((environment / "environment.toml").read_text("utf-8"))
        identifier = str(value["environment"]["environment_id"])
        parsed = UUID(identifier)
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        raise DeploymentError(
            "DEP-ENVIRONMENT-ID", "environment id is invalid"
        ) from error
    if parsed.version != 7 or str(parsed) != identifier:
        raise DeploymentError("DEP-ENVIRONMENT-ID", "environment id is invalid")
    return identifier


def _deployment_root(environment_root: Path) -> Path:
    return environment_root.resolve(strict=True).parent / "deployment"


def _state_paths(environment_root: Path) -> tuple[Path, Path]:
    identifier = _environment_id(environment_root)
    state_root = _deployment_root(environment_root) / "environments" / identifier
    return state_root, state_root / "active.json"


def _state(environment_root: Path) -> dict[str, Any]:
    _, active_path = _state_paths(environment_root)
    if not active_path.exists():
        return {
            "schema_version": DEPLOYMENT_SCHEMA,
            "environment_id": _environment_id(environment_root),
            "generation": 0,
            "active": None,
        }
    value = _strict_json(active_path, "DEP-STATE")
    if value.get("schema_version") != DEPLOYMENT_SCHEMA:
        raise DeploymentError("DEP-STATE", "deployment state schema drifted")
    return value


def stage(
    installation: Path, environment_root: Path, *, expected_active: str
) -> dict[str, Any]:
    verified = verify_installation(installation)
    environment_root = _require_directory(environment_root, "DEP-ENVIRONMENT-ROOT")
    expected_install_root = _deployment_root(environment_root) / "installations"
    if installation.resolve().parent != expected_install_root.resolve():
        raise DeploymentError(
            "DEP-INSTALL-BOUNDARY", "installation is outside deployment"
        )
    state_root, _ = _state_paths(environment_root)
    state = _state(environment_root)
    current = state.get("active")
    current_id = "none" if current is None else current.get("bundle_id")
    if current_id != expected_active:
        raise DeploymentError("DEP-ACTIVE-CAS", "expected Active bundle drifted")
    if current is not None and current_id != verified["bundle_id"]:
        raise DeploymentError(
            "DEP-COMPATIBILITY-UNPROVEN", "cross-bundle activation is not approved"
        )
    pending_root = state_root / "pending"
    if pending_root.exists() and any(pending_root.glob("*.json")):
        raise DeploymentError("DEP-PENDING", "an activation is already pending")
    activation_id = str(uuid7())
    pending = {
        "schema_version": PENDING_SCHEMA,
        "activation_id": activation_id,
        "environment_id": state["environment_id"],
        "generation": int(state["generation"]) + 1,
        "bundle_id": verified["bundle_id"],
        "installation": f"installations/{verified['bundle_id'].removeprefix('sha256:')}",
        "previous": current,
    }
    path = pending_root / f"{activation_id}.json"
    _atomic_json(path, pending)
    return {
        "status": "pending",
        "activation_id": os.fspath(path.resolve()),
        "bundle_id": verified["bundle_id"],
    }


def _runtime_status(installation: Path, environment_root: Path) -> dict[str, Any]:
    output = _run(
        [
            os.fspath(installation / "venv/Scripts/armi.exe"),
            "status",
            "--environment-root",
            os.fspath(environment_root),
        ],
        cwd=environment_root,
        code="DEP-RUNTIME-STATUS",
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise DeploymentError("DEP-RUNTIME-STATUS", "invalid Runtime status") from error
    if not isinstance(value, dict):
        raise DeploymentError("DEP-RUNTIME-STATUS", "invalid Runtime status")
    return cast(dict[str, Any], value)


def _windows_process_identity(pid: int) -> tuple[Path, str]:
    if os.name != "nt":
        raise DeploymentError("DEP-WINDOWS-REQUIRED", "Windows process proof required")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise DeploymentError("DEP-PROCESS", "Runtime process is unavailable")
    token = wintypes.HANDLE()
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            raise DeploymentError("DEP-PROCESS-IMAGE", "process image is unavailable")
        if not advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            raise DeploymentError("DEP-PROCESS-SID", "process token is unavailable")
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, token_buffer, required, ctypes.byref(required)
        ):
            raise DeploymentError("DEP-PROCESS-SID", "token user is unavailable")
        sid_pointer = ctypes.cast(token_buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise DeploymentError("DEP-PROCESS-SID", "token SID is unavailable")
        try:
            sid = sid_text.value
        finally:
            kernel32.LocalFree(sid_text)
        if sid is None:
            raise DeploymentError("DEP-PROCESS-SID", "token SID is unavailable")
        return Path(buffer.value), sid
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(handle)


def commit(activation_path: Path, *, runtime_sid: str) -> dict[str, Any]:
    pending = _strict_json(activation_path, "DEP-PENDING")
    if pending.get("schema_version") != PENDING_SCHEMA:
        raise DeploymentError("DEP-PENDING", "pending schema drifted")
    state_root = activation_path.resolve().parent.parent
    deployment_root = state_root.parent.parent
    installation = deployment_root / cast(str, pending["installation"])
    environment_id = cast(str, pending["environment_id"])
    environment_candidates = [
        path
        for path in deployment_root.parent.iterdir()
        if path.is_dir()
        and path.name != "deployment"
        and (path / "environment.toml").is_file()
    ]
    environment_root = next(
        (
            path
            for path in environment_candidates
            if _environment_id(path) == environment_id
        ),
        None,
    )
    if environment_root is None:
        activation_path.unlink(missing_ok=True)
        raise DeploymentError("DEP-ENVIRONMENT-ROOT", "environment root is unavailable")
    try:
        verify_installation(installation)
        observed = _runtime_status(installation, environment_root)
        runtime = observed.get("runtime")
        if observed.get("status") != "running" or not isinstance(runtime, dict):
            raise DeploymentError("DEP-RUNTIME-NOT-READY", "Runtime is not running")
        if runtime.get("readiness") != "ready" or runtime.get("runtime_state") not in {
            "ready",
            "degraded",
        }:
            raise DeploymentError("DEP-RUNTIME-NOT-READY", "Runtime is not ready")
        if runtime.get("runtime_state") == "degraded" and runtime.get(
            "reason_codes"
        ) != ["RUNTIME_MODEL_UNAVAILABLE"]:
            raise DeploymentError("DEP-RUNTIME-NOT-READY", "degraded reasons drifted")
        pid = observed.get("pid")
        if type(pid) is not int or pid < 1:
            raise DeploymentError("DEP-PROCESS", "Runtime PID is invalid")
        image, sid = _windows_process_identity(pid)
        expected_image = (installation / "venv/Scripts/pythonw.exe").resolve()
        if os.path.normcase(image.resolve()) != os.path.normcase(expected_image):
            raise DeploymentError("DEP-PROCESS-IMAGE", "Runtime image drifted")
        if sid != runtime_sid:
            raise DeploymentError("DEP-PROCESS-SID", "Runtime token SID drifted")
        active = {
            "schema_version": DEPLOYMENT_SCHEMA,
            "environment_id": environment_id,
            "generation": pending["generation"],
            "active": {
                "bundle_id": pending["bundle_id"],
                "installation": pending["installation"],
            },
        }
        _atomic_json(state_root / "active.json", active)
    except Exception:
        activation_path.unlink(missing_ok=True)
        raise
    activation_path.unlink(missing_ok=True)
    return {
        "status": "active",
        "bundle_id": pending["bundle_id"],
        "generation": pending["generation"],
        "pid": pid,
    }


def deactivate(environment_root: Path, *, expected_active: str) -> dict[str, Any]:
    environment_root = _require_directory(environment_root, "DEP-ENVIRONMENT-ROOT")
    _, active_path = _state_paths(environment_root)
    state = _state(environment_root)
    active = state.get("active")
    current = "none" if active is None else active.get("bundle_id")
    if current != expected_active:
        raise DeploymentError("DEP-ACTIVE-CAS", "expected Active bundle drifted")
    if active is None:
        return {"status": "inactive", "generation": state["generation"]}
    installation = _deployment_root(environment_root) / active["installation"]
    observed = _runtime_status(installation, environment_root)
    if observed.get("status") != "stopped":
        raise DeploymentError("DEP-RUNTIME-RUNNING", "Runtime must be stopped")
    updated = {
        "schema_version": DEPLOYMENT_SCHEMA,
        "environment_id": state["environment_id"],
        "generation": int(state["generation"]) + 1,
        "active": None,
    }
    _atomic_json(active_path, updated)
    return {"status": "inactive", "generation": updated["generation"]}


def status(environment_root: Path) -> dict[str, Any]:
    state = _state(environment_root)
    state_root, _ = _state_paths(environment_root)
    pending = sorted((state_root / "pending").glob("*.json"))
    return {**state, "pending_count": len(pending)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--bundle", type=Path, required=True)
    install_parser.add_argument("--deployment-root", type=Path, required=True)
    install_parser.add_argument(
        "--dependency-mode", choices=("online", "offline"), required=True
    )
    verify_parser = commands.add_parser("verify-install")
    verify_parser.add_argument("--installation", type=Path, required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--installation", type=Path, required=True)
    stage_parser.add_argument("--environment-root", type=Path, required=True)
    stage_parser.add_argument("--expected-active", required=True)
    commit_parser = commands.add_parser("commit")
    commit_parser.add_argument("--activation-id", type=Path, required=True)
    commit_parser.add_argument("--runtime-sid", required=True)
    deactivate_parser = commands.add_parser("deactivate")
    deactivate_parser.add_argument("--environment-root", type=Path, required=True)
    deactivate_parser.add_argument("--expected-active", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--environment-root", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    tool_root = args.tool_root.resolve() if args.tool_root else root / ".armi-tools"
    try:
        if args.command == "install":
            result = install(
                args.bundle,
                args.deployment_root,
                dependency_mode=args.dependency_mode,
                repository_root=root,
                tool_root=tool_root,
            )
        elif args.command == "verify-install":
            result = verify_installation(args.installation, forbidden_root=root)
        elif args.command == "stage":
            result = stage(
                args.installation,
                args.environment_root,
                expected_active=args.expected_active,
            )
        elif args.command == "commit":
            result = commit(args.activation_id, runtime_sid=args.runtime_sid)
        elif args.command == "deactivate":
            result = deactivate(
                args.environment_root, expected_active=args.expected_active
            )
        else:
            result = status(args.environment_root)
    except DeploymentError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
