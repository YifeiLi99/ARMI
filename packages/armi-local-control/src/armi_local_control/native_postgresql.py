"""Lifecycle of an explicitly owned, native Windows PostgreSQL cluster."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, cast

import psutil
from pydantic import BaseModel, ConfigDict, Field

from .configuration.models import AbsolutePath
from .configuration.paths import has_reparse_point
from .process_identity import ManagedProcessIdentity, ManagedProcessState
from .runtime_errors import RuntimeViolation
from .runtime_process import LocalProcessLock


class PostgreSQLControlBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ownership: Literal["exclusive", "shared"]
    installation_root: AbsolutePath
    data_directory: AbsolutePath
    port: int = Field(ge=1024, le=65535)


def private_directory(path: Path) -> None:
    """Create an owner-only local directory before writing credentials."""
    if not path.is_absolute() or has_reparse_point(path, root=Path(path.anchor)):
        raise RuntimeViolation("LOCAL-PRIVATE-PATH", "invalid private directory")
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    system = Path(os.environ["SYSTEMROOT"]) / "System32"
    result = subprocess.run(
        [str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    rows = list(
        csv.reader(io.StringIO(result.stdout.decode("utf-8", errors="replace")))
    )
    sid = rows[0][-1]
    if re.fullmatch(r"S-1-[0-9-]+", sid) is None:
        raise RuntimeViolation("LOCAL-PRIVATE-IDENTITY", "user SID is unavailable")
    result = subprocess.run(
        [
            str(system / "icacls.exe"),
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
        ],
        capture_output=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeViolation("LOCAL-PRIVATE-ACL", "private directory ACL failed")


def write_control(path: Path, value: dict[str, object]) -> None:
    """Publish control metadata atomically inside an already protected directory."""
    temporary = path.with_suffix(path.suffix + ".pending")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class NativePostgreSQL:
    """Never discover, reconfigure, or stop another environment's database."""

    def __init__(
        self,
        binding: PostgreSQLControlBinding,
        *,
        environment_root: Path,
        environment_id: str,
    ) -> None:
        self.binding = binding
        self.root = environment_root.resolve()
        self.environment_id = environment_id
        self.data = binding.data_directory
        self.control = self.data.parent
        self.identity_path = self.control / "cluster.json"
        if (
            binding.ownership != "exclusive"
            or not self.data.is_relative_to(self.root)
            or self.data == self.root
            or has_reparse_point(self.data, root=self.root)
            or has_reparse_point(
                binding.installation_root, root=Path(binding.installation_root.anchor)
            )
        ):
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-BOUNDARY", "invalid cluster binding"
            )

    def _run(self, tool: str, *arguments: str, timeout: int = 60) -> bytes:
        executable = self.binding.installation_root / "bin" / (tool + ".exe")
        if not executable.is_file():
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-UNAVAILABLE", "native PostgreSQL is missing"
            )
        environment = {
            k: v for k, v in os.environ.items() if not k.upper().startswith("PG")
        }
        environment.update({"LANG": "C", "LC_ALL": "C", "LC_MESSAGES": "C"})
        try:
            # A Windows postgres descendant can inherit pg_ctl's output handles.
            # File capture lets the launcher finish without waiting for pipe EOF.
            private_directory(self.control / "tmp")
            with tempfile.TemporaryFile(dir=self.control / "tmp") as output:
                result = subprocess.run(
                    [str(executable), *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    timeout=timeout,
                    check=False,
                    env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                output.seek(0)
                captured = output.read()
        except subprocess.TimeoutExpired:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-UNKNOWN", "query cluster status before retrying"
            ) from None
        except OSError:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-UNAVAILABLE", "native PostgreSQL cannot run"
            ) from None
        if result.returncode:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-FAILED",
                f"PostgreSQL {tool} failed; inspect the local database log",
            )
        return captured

    def _system_identifier(self) -> str:
        output = self._run("pg_controldata", str(self.data)).decode(
            "utf-8", errors="replace"
        )
        match = re.search(
            r"^Database system identifier:\s*(\d+)\s*$", output, re.MULTILINE
        )
        if match is None:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-IDENTITY", "cluster identity is unavailable"
            )
        return match.group(1)

    def _identity(self) -> dict[str, object]:
        try:
            value = json.loads(self.identity_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-NOT-INITIALIZED",
                "cluster must be initialized explicitly",
            ) from None
        if not isinstance(value, dict) or value != {
            "schema_version": "armi.native-postgresql.v1",
            "environment_id": self.environment_id,
            "data_directory": str(self.data),
            "port": self.binding.port,
            "postgresql_version": "18.4",
            "system_identifier": self._system_identifier(),
        }:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-IDENTITY", "cluster does not match its binding"
            )
        return cast(dict[str, object], value)

    def initialize(self, *, username: str, password: str) -> dict[str, object]:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", username)
            or not password
            or "\n" in password
            or "\r" in password
        ):
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-CREDENTIAL", "invalid bootstrap input"
            )
        private_directory(self.control)
        with LocalProcessLock(self.control / "native.lock"):
            if self.identity_path.exists():
                return {"status": "initialized", **self._identity()}
            if self.data.exists() and any(self.data.iterdir()):
                raise RuntimeViolation(
                    "LOCAL-POSTGRESQL-NONEMPTY",
                    "initialization requires an empty data directory",
                )
            if (
                self._run("postgres", "--version").strip()
                != b"postgres (PostgreSQL) 18.4"
            ):
                raise RuntimeViolation(
                    "LOCAL-POSTGRESQL-VERSION", "PostgreSQL must be exactly 18.4"
                )
            for name in ("vector", "pg_trgm"):
                if not (
                    self.binding.installation_root / "lib" / f"{name}.dll"
                ).is_file():
                    raise RuntimeViolation(
                        "LOCAL-POSTGRESQL-EXTENSION",
                        f"native {name} extension is missing",
                    )
            password_file = self.control / "init-password"
            try:
                with password_file.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(password + "\n")
                self._run(
                    "initdb",
                    "-D",
                    str(self.data),
                    "--username",
                    username,
                    "--pwfile",
                    str(password_file),
                    "--encoding=UTF8",
                    "--locale-provider=builtin",
                    "--builtin-locale=C.UTF-8",
                    "--auth=scram-sha-256",
                    "--data-checksums",
                )
            finally:
                password_file.unlink(missing_ok=True)
            with (self.data / "postgresql.conf").open(
                "a", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write(
                    f"\nlisten_addresses = '127.0.0.1'\nport = {self.binding.port}\n"
                    "timezone = 'UTC'\nlog_timezone = 'UTC'\n"
                    "password_encryption = 'scram-sha-256'\n"
                    "log_statement = 'none'\nlog_min_error_statement = 'panic'\n"
                )
            identity: dict[str, object] = {
                "schema_version": "armi.native-postgresql.v1",
                "environment_id": self.environment_id,
                "data_directory": str(self.data),
                "port": self.binding.port,
                "postgresql_version": "18.4",
                "system_identifier": self._system_identifier(),
            }
            write_control(self.identity_path, identity)
            return {"status": "initialized", **identity}

    def _process(self) -> ManagedProcessIdentity | None:
        pid_path = self.data / "postmaster.pid"
        if not pid_path.exists():
            return None
        try:
            # The managed Windows distribution embeds an activeCodePage UTF-8
            # manifest. Filesystem metadata is independent of the host ACP.
            lines = pid_path.read_text(encoding="utf-8").splitlines()
            pid, started, port = int(lines[0]), int(lines[2]), int(lines[3])
            if Path(lines[1]).resolve() != self.data or port != self.binding.port:
                raise ValueError("cluster binding mismatch")
            identity = ManagedProcessIdentity.capture(
                pid, environment_identity=self.environment_id, incarnation=1
            )
            expected_executable = os.path.normcase(
                str((self.binding.installation_root / "bin/postgres.exe").resolve())
            )
            arguments = psutil.Process(pid).cmdline()
            if (
                identity.executable_identity != expected_executable
                or abs(identity.creation_time_microseconds / 1_000_000 - started) > 5
                or "-D" not in arguments
                or Path(arguments[arguments.index("-D") + 1]).resolve() != self.data
            ):
                raise ValueError("process mismatch")
            return identity
        except psutil.NoSuchProcess:
            return None
        except OSError, ValueError, IndexError, psutil.AccessDenied:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-PROCESS",
                "database process identity cannot be verified",
            ) from None

    def execute(self, action: Literal["start", "stop", "status"]) -> dict[str, object]:
        self._identity()
        with LocalProcessLock(self.control / "native.lock"):
            identity = self._process()
            if action == "start" and identity is None:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    if probe.connect_ex(("127.0.0.1", self.binding.port)) == 0:
                        raise RuntimeViolation(
                            "LOCAL-POSTGRESQL-PORT",
                            "the bound port belongs to another process",
                        )
                self._run(
                    "pg_ctl",
                    "start",
                    "-D",
                    str(self.data),
                    "-l",
                    str(self.control / "postgresql.log"),
                    "-w",
                    "-t",
                    "45",
                )
                identity = self._process()
                if identity is None:
                    raise RuntimeViolation(
                        "LOCAL-POSTGRESQL-UNKNOWN",
                        "database start could not be verified",
                    )
            if action == "stop" and identity is not None:
                if identity.inspect() != ManagedProcessState.MATCHES:
                    raise RuntimeViolation(
                        "LOCAL-POSTGRESQL-PROCESS",
                        "database process changed before stop",
                    )
                self._run(
                    "pg_ctl",
                    "stop",
                    "-D",
                    str(self.data),
                    "-m",
                    "fast",
                    "-w",
                    "-t",
                    "45",
                )
                if identity.inspect() == ManagedProcessState.MATCHES:
                    raise RuntimeViolation(
                        "LOCAL-POSTGRESQL-UNKNOWN",
                        "database stop could not be verified",
                    )
                identity = None
            if identity is not None:
                self._run(
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(self.binding.port),
                    "-t",
                    "3",
                )
            return {
                "ownership": "exclusive",
                "status": "ready" if identity else "stopped",
                "port": self.binding.port,
            }


__all__ = (
    "NativePostgreSQL",
    "PostgreSQLControlBinding",
    "free_loopback_port",
    "private_directory",
    "write_control",
)
