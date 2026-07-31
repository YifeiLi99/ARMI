"""Run the real PostgreSQL 18.4 integration suite in an isolated cluster."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RuntimeError("PG-INTEGRATION-PROCESS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path, default=Path(".armi-tools"))
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--artifact-summary-file", type=Path)
    parser.add_argument("--work-summary-file", type=Path)
    parser.add_argument("--birth-summary-file", type=Path)
    parser.add_argument("--authority-summary-file", type=Path)
    parser.add_argument("--recovery-summary-file", type=Path)
    parser.add_argument("--s026-live-env-file", type=Path)
    parser.add_argument("--s026-live-output", type=Path)
    parser.add_argument("--test-expression")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    tool_root = (root / args.tool_root).resolve()
    pg_bin = tool_root / "installs/postgresql/18.4/pgsql/bin"
    initdb = pg_bin / "initdb.exe"
    pg_ctl = pg_bin / "pg_ctl.exe"
    postgres = pg_bin / "postgres.exe"
    if not all(path.is_file() for path in (initdb, pg_ctl, postgres)):
        print("PG-CACHE-INCOMPLETE: PostgreSQL 18.4 is unavailable", file=sys.stderr)
        return 2
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(32)
    port = _port()
    with tempfile.TemporaryDirectory(
        prefix="postgresql-18.4-", dir=temporary_root
    ) as temporary:
        work = Path(temporary)
        data = work / "data"
        password_file = work / "password"
        log_file = work / "postgresql.log"
        password_file.write_text(password, encoding="utf-8", newline="\n")
        try:
            _run(
                [
                    str(initdb),
                    "-D",
                    str(data),
                    "--username=s009_admin",
                    f"--pwfile={password_file}",
                    "--auth-host=scram-sha-256",
                    "--auth-local=scram-sha-256",
                    "--encoding=UTF8",
                    "--locale-provider=builtin",
                    "--builtin-locale=C.UTF-8",
                    "--data-checksums",
                    "--no-sync",
                ]
            )
            with (data / "postgresql.conf").open(
                "a", encoding="utf-8", newline="\n"
            ) as configuration:
                configuration.write("\ntimezone = 'UTC'\n")
            _run(
                [
                    str(pg_ctl),
                    "-D",
                    str(data),
                    "-l",
                    str(log_file),
                    "-w",
                    "start",
                    "-o",
                    f"-h 127.0.0.1 -p {port}",
                ]
            )
            environment = dict(os.environ)
            environment["S009_ADMIN_DSN"] = (
                f"postgresql://s009_admin:{password}@127.0.0.1:{port}/postgres"
            )
            if args.summary_file is not None:
                environment["S009_SUMMARY_FILE"] = str(args.summary_file.resolve())
            if args.artifact_summary_file is not None:
                environment["S012_ARTIFACT_SUMMARY_FILE"] = str(
                    args.artifact_summary_file.resolve()
                )
            if args.work_summary_file is not None:
                environment["S014_WORK_SUMMARY_FILE"] = str(
                    args.work_summary_file.resolve()
                )
            if args.birth_summary_file is not None:
                environment["S015_BIRTH_SUMMARY_FILE"] = str(
                    args.birth_summary_file.resolve()
                )
            if args.authority_summary_file is not None:
                environment["S016_AUTHORITY_SUMMARY_FILE"] = str(
                    args.authority_summary_file.resolve()
                )
            if args.recovery_summary_file is not None:
                environment["S017_RECOVERY_SUMMARY_FILE"] = str(
                    args.recovery_summary_file.resolve()
                )
            if args.s026_live_env_file is not None:
                environment["S026_LIVE_ENV_FILE"] = str(
                    args.s026_live_env_file.resolve()
                )
            if args.s026_live_output is not None:
                environment["S026_LIVE_OUTPUT"] = str(args.s026_live_output.resolve())
            pytest_command = [
                sys.executable,
                "-m",
                "pytest",
                "tests/postgresql",
                "-q",
            ]
            test_expression = args.test_expression
            if args.s026_live_env_file is not None and test_expression is None:
                test_expression = "t03_subject_commit"
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
            print(f"{error}: isolated PostgreSQL command failed", file=sys.stderr)
            return 1
        finally:
            if data.is_dir():
                subprocess.run(
                    [str(pg_ctl), "-D", str(data), "-m", "immediate", "-w", "stop"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    raise SystemExit(main())
