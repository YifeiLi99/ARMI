"""Reusable lifecycle for a disposable loopback PostgreSQL container."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

IMAGE = "pgvector/pgvector:0.8.6-pg18-trixie"


class PostgreSQLUnavailable(RuntimeError):
    """The local deterministic PostgreSQL prerequisite is unavailable."""


class PostgreSQLLaunchError(RuntimeError):
    """The isolated PostgreSQL environment failed after prerequisites passed."""


@dataclass(frozen=True, slots=True)
class IsolatedPostgreSQL:
    admin_dsn: str
    container: str


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_postgres(container: str, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = _run(["docker", "inspect", "--format", "{{.State.Running}}", container])
        if state.returncode != 0 or state.stdout.strip() != "true":
            raise PostgreSQLLaunchError("PG-INTEGRATION-CONTAINER")
        ready = _run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "--username=s009_admin",
                "--dbname=postgres",
            ]
        )
        if ready.returncode == 0:
            return
        time.sleep(0.25)
    raise PostgreSQLLaunchError("PG-INTEGRATION-READY")


def _remove_container(container: str) -> None:
    if not container.startswith("armi-postgresql-test-"):
        raise PostgreSQLLaunchError("PG-INTEGRATION-CONTAINER-IDENTITY")
    removed = _run(["docker", "rm", "--force", container])
    if removed.returncode != 0:
        raise PostgreSQLLaunchError("PG-INTEGRATION-CLEANUP")


@contextmanager
def isolated_postgresql(root: Path) -> Iterator[IsolatedPostgreSQL]:
    init_script = root / "tools/docker/postgresql/initdb/00-vector.sql"
    if not init_script.is_file():
        raise PostgreSQLUnavailable("PG-INTEGRATION-INIT")
    try:
        engine = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    except OSError as error:
        raise PostgreSQLUnavailable("PG-DOCKER-ENGINE") from error
    if engine.returncode != 0:
        raise PostgreSQLUnavailable("PG-DOCKER-ENGINE")

    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(32)
    port = _free_port()
    container = f"armi-postgresql-test-{os.getpid()}-{secrets.token_hex(4)}"
    started = False
    with tempfile.TemporaryDirectory(
        prefix="postgresql-docker-", dir=temporary_root
    ) as temporary:
        environment_file = Path(temporary) / "container.env"
        environment_file.write_text(
            "\n".join(
                (
                    "POSTGRES_DB=postgres",
                    "POSTGRES_USER=s009_admin",
                    f"POSTGRES_PASSWORD={password}",
                    "POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale-provider=builtin "
                    "--builtin-locale=C.UTF-8 --data-checksums",
                    "TZ=UTC",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        try:
            launch = _run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    container,
                    "--env-file",
                    str(environment_file),
                    "--publish",
                    f"127.0.0.1:{port}:5432",
                    "--mount",
                    f"type=bind,src={init_script.resolve()},"
                    "dst=/docker-entrypoint-initdb.d/00-vector.sql,readonly",
                    "--tmpfs",
                    "/var/lib/postgresql:rw",
                    IMAGE,
                    "-c",
                    "timezone=UTC",
                    "-c",
                    "password_encryption=scram-sha-256",
                ]
            )
            if launch.returncode != 0:
                raise PostgreSQLLaunchError("PG-INTEGRATION-START")
            started = True
            _wait_for_postgres(container)
            yield IsolatedPostgreSQL(
                f"postgresql://s009_admin:{password}@127.0.0.1:{port}/postgres",
                container,
            )
        finally:
            if started:
                _remove_container(container)


__all__ = (
    "IsolatedPostgreSQL",
    "PostgreSQLLaunchError",
    "PostgreSQLUnavailable",
    "isolated_postgresql",
)
