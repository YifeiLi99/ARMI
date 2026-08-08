"""Run the PostgreSQL 18.4 + pgvector 0.8.6 suite in an isolated container."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

_IMAGE = "pgvector/pgvector:0.8.6-pg18-trixie"


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _run(
    command: list[str], *, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=capture,
        text=True,
        encoding="utf-8",
    )


def _wait_for_postgres(container: str, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = _run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container,
            ]
        )
        if state.returncode != 0 or state.stdout.strip() != "true":
            raise RuntimeError("PG-INTEGRATION-CONTAINER")
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
    raise RuntimeError("PG-INTEGRATION-READY")


def _remove_container(container: str) -> None:
    if not container.startswith("armi-postgresql-test-"):
        raise RuntimeError("PG-INTEGRATION-CONTAINER-IDENTITY")
    _run(["docker", "rm", "--force", container])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--postgresql-client-root",
        type=Path,
        default=Path(".armi-tools/installs/postgresql/18.4/pgsql"),
    )
    parser.add_argument("--s026-live-env-file", type=Path)
    parser.add_argument("--s027-live-env-file", type=Path)
    parser.add_argument("--s028-live-env-file", type=Path)
    parser.add_argument("--s033-live-env-file", type=Path)
    parser.add_argument("--test-expression")
    parser.add_argument("--freeze-catalog", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    client_root = (root / args.postgresql_client_root).resolve()
    init_script = root / "tools/docker/postgresql/initdb/00-vector.sql"
    if not init_script.is_file():
        print("PG-INTEGRATION-INIT: vector bootstrap is unavailable", file=sys.stderr)
        return 2
    if _run(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode != 0:
        print("PG-DOCKER-ENGINE: Docker Engine is unavailable", file=sys.stderr)
        return 2

    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(32)
    port = _port()
    container = f"armi-postgresql-test-{os.getpid()}-{secrets.token_hex(4)}"
    started = False
    with tempfile.TemporaryDirectory(
        prefix="postgresql-docker-", dir=temporary_root
    ) as temporary:
        work = Path(temporary)
        environment_file = work / "container.env"
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
                    _IMAGE,
                    "-c",
                    "timezone=UTC",
                    "-c",
                    "password_encryption=scram-sha-256",
                ]
            )
            if launch.returncode != 0:
                raise RuntimeError("PG-INTEGRATION-START")
            started = True
            _wait_for_postgres(container)
            environment = dict(os.environ)
            environment["S003_POSTGRESQL_CLIENT_ROOT"] = str(client_root)
            environment["S009_ADMIN_DSN"] = (
                f"postgresql://s009_admin:{password}@127.0.0.1:{port}/postgres"
            )
            if args.s026_live_env_file is not None:
                environment["S026_LIVE_ENV_FILE"] = str(
                    args.s026_live_env_file.resolve()
                )
            if args.s027_live_env_file is not None:
                environment["S027_LIVE_ENV_FILE"] = str(
                    args.s027_live_env_file.resolve()
                )
            if args.s028_live_env_file is not None:
                environment["S028_LIVE_ENV_FILE"] = str(
                    args.s028_live_env_file.resolve()
                )
            if args.s033_live_env_file is not None:
                environment["S033_LIVE_ENV_FILE"] = str(
                    args.s033_live_env_file.resolve()
                )
            if args.freeze_catalog:
                frozen = subprocess.run(
                    [sys.executable, "tools/freeze_schema_catalog.py"],
                    cwd=root,
                    env=environment,
                    check=False,
                )
                if frozen.returncode != 0:
                    return frozen.returncode
            pytest_command = [sys.executable, "-m", "pytest", "tests/postgresql", "-q"]
            test_expression = args.test_expression
            if args.s026_live_env_file is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s027_live_env_file is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s028_live_env_file is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s033_live_env_file is not None and test_expression is None:
                test_expression = "web_observation_admission"
            if test_expression is not None:
                pytest_command.extend(("-k", test_expression))
            completed = subprocess.run(
                pytest_command,
                cwd=root,
                env=environment,
                check=False,
            )
            return completed.returncode
        except RuntimeError as error:
            print(f"{error}: isolated Docker PostgreSQL failed", file=sys.stderr)
            if started:
                logs = _run(["docker", "logs", "--tail", "40", container])
                if logs.stderr:
                    print(logs.stderr, file=sys.stderr)
            return 1
        finally:
            if started:
                _remove_container(container)


if __name__ == "__main__":
    raise SystemExit(main())
