"""Run the isolated M0-S045 installation and rollback rehearsal."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid7
from zipfile import ZipFile

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

try:
    from tools.candidate_bundle import (
        build_identity,
        verify_bundle,
        write_deterministic_bundle,
    )
    from tools.deploy_candidate import DeploymentError, install
except ModuleNotFoundError:
    from candidate_bundle import (  # type: ignore[no-redef]
        build_identity,
        verify_bundle,
        write_deterministic_bundle,
    )
    from deploy_candidate import DeploymentError, install  # type: ignore[no-redef]


class RehearsalError(RuntimeError):
    """A stable S045 rehearsal failure."""


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _run(command: list[str], *, cwd: Path, code: str) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise RehearsalError(f"{code}: {detail[-1] if detail else 'command failed'}")
    return completed.stdout.strip()


def _start_postgres(postgres: Path, data: Path, log: Path, port: int) -> Any:
    handle = log.open("ab", buffering=0)
    try:
        return subprocess.Popen(
            [
                os.fspath(postgres),
                "-D",
                os.fspath(data),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        handle.close()


def _wait_postgres(pg_isready: Path, process: Any, port: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RehearsalError("S045-POSTGRES-EXIT")
        completed = subprocess.run(
            [
                os.fspath(pg_isready),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-d",
                "postgres",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return
        time.sleep(0.05)
    raise RehearsalError("S045-POSTGRES-TIMEOUT")


def _negative_candidate(bundle: Path, output: Path) -> dict[str, Any]:
    identity = verify_bundle(bundle)
    with ZipFile(bundle) as archive:
        payloads = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != "bundle-identity.json"
        }
    wheels = cast(list[dict[str, Any]], identity["wheels"])
    locks = cast(list[dict[str, Any]], identity["locks"])
    wheel_files = [(item["path"], payloads[item["path"]]) for item in wheels]
    lock_files = [
        (
            item["role"],
            item["path"],
            payloads[item["path"]],
            item.get("derived_from"),
        )
        for item in locks
    ]
    negative = build_identity("0" * 40, wheel_files, lock_files)
    write_deterministic_bundle(output, negative, payloads)
    verify_bundle(output)
    return negative


def _installed_probe(
    installation: Path, root: Path, command: str, *arguments: str
) -> dict[str, Any]:
    output = _run(
        [
            os.fspath(installation / "venv/Scripts/python.exe"),
            "-I",
            os.fspath(root / "tools/s045_installed_probe.py"),
            command,
            *arguments,
        ],
        cwd=installation,
        code=f"S045-PROBE-{command.upper()}",
    )
    return json.loads(output)


def _quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _invoke_elevated(
    root: Path,
    environment_root: Path,
    installation: Path,
    incompatible_installation: Path,
    summary_path: Path,
) -> None:
    arguments = [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        os.fspath(root / "tools/invoke_s045_elevated.ps1"),
        "-RepositoryRoot",
        os.fspath(root),
        "-EnvironmentRoot",
        os.fspath(environment_root),
        "-Installation",
        os.fspath(installation),
        "-IncompatibleInstallation",
        os.fspath(incompatible_installation),
        "-SummaryPath",
        os.fspath(summary_path),
    ]
    encoded_arguments = ",".join(_quote_powershell(item) for item in arguments)
    command = (
        "$process=Start-Process -FilePath 'pwsh' -Verb RunAs "
        f"-ArgumentList @({encoded_arguments}) -Wait -PassThru; "
        "exit $process.ExitCode"
    )
    completed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise RehearsalError("S045-ELEVATED-FAILED")


def rehearse(root: Path, bundle: Path, work: Path, evidence: Path) -> dict[str, Any]:
    scratch_root = (root / ".tmp").resolve()
    if scratch_root not in work.parents:
        raise RehearsalError("S045-WORK-BOUNDARY")
    if work == evidence or work in evidence.parents:
        raise RehearsalError("S045-EVIDENCE-BOUNDARY")
    if work.exists():
        raise RehearsalError("S045-WORK-EXISTS")
    work.mkdir(parents=True)
    tool_root = root / ".armi-tools"
    primary_root = work / "primary"
    secondary_root = work / "secondary"
    primary_deployment = primary_root / "deployment"
    secondary_deployment = secondary_root / "deployment"
    environment_root = primary_root / "environment"
    environment_root.mkdir(parents=True)
    (environment_root / "data").mkdir()
    (environment_root / "secrets").mkdir()
    sanitized = dict(os.environ)
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
        sanitized.pop(name, None)
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(sanitized)
    try:
        primary = install(
            bundle,
            primary_deployment,
            dependency_mode="online",
            repository_root=root,
            tool_root=tool_root,
        )
        secondary = install(
            bundle,
            secondary_deployment,
            dependency_mode="offline",
            repository_root=root,
            tool_root=tool_root,
        )
        negative_path = work / "incompatible.zip"
        negative = _negative_candidate(bundle, negative_path)
        incompatible = install(
            negative_path,
            primary_deployment,
            dependency_mode="offline",
            repository_root=root,
            tool_root=tool_root,
        )
    finally:
        os.environ.clear()
        os.environ.update(original)
    corrupt_path = work / "corrupt.zip"
    corrupt = bytearray(bundle.read_bytes())
    corrupt[len(corrupt) // 2] ^= 1
    corrupt_path.write_bytes(corrupt)
    corrupt_code = None
    try:
        install(
            corrupt_path,
            work / "corrupt-deployment",
            dependency_mode="offline",
            repository_root=root,
            tool_root=tool_root,
        )
    except DeploymentError as error:
        corrupt_code = error.code
    if corrupt_code is None:
        raise RehearsalError("S045-CORRUPT-ACCEPTED")

    pg_bin = tool_root / "installs/postgresql/18.4/pgsql/bin"
    initdb = pg_bin / "initdb.exe"
    postgres = pg_bin / "postgres.exe"
    pg_ctl = pg_bin / "pg_ctl.exe"
    pg_isready = pg_bin / "pg_isready.exe"
    password = secrets.token_urlsafe(32)
    password_file = work / "postgres-password"
    password_file.write_text(password, encoding="utf-8", newline="\n")
    pg_data = work / "postgresql/data"
    pg_data.parent.mkdir()
    _run(
        [
            os.fspath(initdb),
            "-D",
            os.fspath(pg_data),
            "--username=s045_admin",
            f"--pwfile={password_file}",
            "--auth-host=scram-sha-256",
            "--auth-local=scram-sha-256",
            "--encoding=UTF8",
            "--locale-provider=builtin",
            "--builtin-locale=C.UTF-8",
            "--data-checksums",
            "--no-sync",
        ],
        cwd=work,
        code="S045-INITDB",
    )
    with (pg_data / "postgresql.conf").open(
        "a", encoding="utf-8", newline="\n"
    ) as stream:
        stream.write("\ntimezone = 'UTC'\n")
    port = _port()
    process = _start_postgres(postgres, pg_data, work / "postgresql.log", port)
    result: dict[str, Any] | None = None
    try:
        _wait_postgres(pg_isready, process, port)
        database = f"s045_{secrets.token_hex(5)}"
        admin_dsn = make_conninfo(
            host="127.0.0.1",
            port=port,
            dbname="postgres",
            user="s045_admin",
            password=password,
        )
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' "
                    "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8'"
                ).format(sql.Identifier(database))
            )
        provisioner = make_conninfo(
            host="127.0.0.1",
            port=port,
            dbname=database,
            user="s045_admin",
            password=password,
        )
        environment_id = str(uuid7())
        role_passwords = {
            name: secrets.token_urlsafe(32) for name in ("runtime", "admin", "migrator")
        }
        bootstrap_root = work / "database-bootstrap"
        bootstrap_root.mkdir()
        (bootstrap_root / "provisioner").write_text(
            provisioner, encoding="utf-8", newline="\n"
        )
        for name, value in role_passwords.items():
            (bootstrap_root / name).write_text(value, encoding="utf-8", newline="\n")
        _run(
            [
                os.fspath(root / ".venv/Scripts/python.exe"),
                "-B",
                os.fspath(root / "tools/bootstrap_database_roles.py"),
                "--environment-id",
                environment_id,
                "--secret-root",
                os.fspath(bootstrap_root),
                "--provisioner-conninfo-file",
                os.fspath(bootstrap_root / "provisioner"),
                "--runtime-password-file",
                os.fspath(bootstrap_root / "runtime"),
                "--admin-password-file",
                os.fspath(bootstrap_root / "admin"),
                "--migrator-password-file",
                os.fspath(bootstrap_root / "migrator"),
                "--apply",
            ],
            cwd=root,
            code="S045-DATABASE-ROLES",
        )
        common = {"host": "127.0.0.1", "port": port, "dbname": database}
        for name in ("runtime", "admin", "migrator"):
            role = f"armi_{environment_id.replace('-', '')}_{name}"
            dsn = make_conninfo(**common, user=role, password=role_passwords[name])
            (environment_root / "secrets" / name).write_text(
                dsn, encoding="utf-8", newline="\n"
            )
        creator = "creator-v1." + secrets.token_urlsafe(32)
        (environment_root / "secrets/creator").write_text(
            creator, encoding="utf-8", newline="\n"
        )
        (environment_root / "secrets/preview").write_text(
            secrets.token_urlsafe(32), encoding="utf-8", newline="\n"
        )
        creator_port = _port()
        (environment_root / "environment.toml").write_text(
            "\n".join(
                (
                    "[environment]",
                    f'environment_id = "{environment_id}"',
                    f'data_root = "{(environment_root / "data").as_posix()}"',
                    "",
                    "[creator]",
                    f"port = {creator_port}",
                    "",
                    "[secret_locators]",
                    f'"database.runtime" = "file:{(environment_root / "secrets/runtime").as_posix()}"',
                    f'"database.admin" = "file:{(environment_root / "secrets/admin").as_posix()}"',
                    f'"database.migrator" = "file:{(environment_root / "secrets/migrator").as_posix()}"',
                    f'"creator.bearer" = "file:{(environment_root / "secrets/creator").as_posix()}"',
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        installation = Path(primary["installation"])
        _installed_probe(
            installation,
            root,
            "birth-manifest",
            "--environment-root",
            os.fspath(environment_root),
        )
        _installed_probe(
            installation,
            root,
            "admin-config",
            "--environment-root",
            os.fspath(environment_root),
            "--postgresql-tool-root",
            os.fspath(tool_root / "installs/postgresql/18.4/pgsql"),
        )
        elevated_summary = work / "elevated-summary.json"
        _invoke_elevated(
            root,
            environment_root,
            installation,
            Path(incompatible["installation"]),
            elevated_summary,
        )
        elevated = json.loads(elevated_summary.read_bytes())
        result = {
            "schema_version": "armi.s045-evidence.v1",
            "status": "pass",
            "tooling_revision": _run(
                ["git", "rev-parse", "HEAD"], cwd=root, code="S045-GIT-REVISION"
            ),
            "bundle": {
                "bundle_id": primary["bundle_id"],
                "source_revision": primary["source_revision"],
                "archive_sha256": primary["archive_sha256"],
            },
            "primary_projection_sha256": primary["projection_sha256"],
            "secondary_projection_sha256": secondary["projection_sha256"],
            "secondary_offline": True,
            "corrupt_rejection_code": corrupt_code,
            "incompatible_bundle_id": negative["bundle_id"],
            "elevated": elevated,
            "postgresql": "18.4",
            "cleanup": {
                "runtime_stopped": elevated["cleanup"]["runtime_stopped"],
                "active_cleared": elevated["cleanup"]["active_cleared"],
                "accounts_removed": elevated["cleanup"]["accounts_removed"],
                "postgresql_stopped": False,
                "environment_roots_removed": False,
            },
        }
    finally:
        if pg_data.is_dir():
            subprocess.run(
                [
                    os.fspath(pg_ctl),
                    "-D",
                    os.fspath(pg_data),
                    "-m",
                    "immediate",
                    "-w",
                    "stop",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if result is None:
        raise RehearsalError("S045-NO-RESULT")
    if process.poll() is None:
        raise RehearsalError("S045-POSTGRES-CLEANUP")
    result["cleanup"]["postgresql_stopped"] = True
    shutil.rmtree(work)
    result["cleanup"]["environment_roots_removed"] = not work.exists()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = rehearse(
            args.root.resolve(),
            args.bundle.resolve(strict=True),
            args.work_root.resolve(),
            args.evidence.resolve(),
        )
    except (OSError, RehearsalError, DeploymentError) as error:
        print(f"S045-REHEARSAL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
