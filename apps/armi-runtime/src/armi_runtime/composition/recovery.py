"""Offline database-and-artifact backup plus isolated restore verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast
from uuid import uuid7

import psycopg
from armi_kernel.application import CredentialPurpose
from armi_postgresql_contract.catalog_fingerprint import (
    database_catalog_digest,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from .environment import PreparedEnvironment
from .runtime_errors import RuntimeViolation
from .runtime_process import RuntimeProcessManager

_MANIFEST_SCHEMA: Final = "armi.recovery-backup.v1"
_MAX_CONNINFO_BYTES: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    status: str
    backup_id: str
    bundle: str
    database_digest: str
    catalog_digest: str
    table_count: int
    row_count: int
    artifact_count: int

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "backup_id": self.backup_id,
            "bundle": self.bundle,
            "database_digest": self.database_digest,
            "catalog_digest": self.catalog_digest,
            "table_count": self.table_count,
            "row_count": self.row_count,
            "artifact_count": self.artifact_count,
        }


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _connection_identity(conninfo: str) -> str:
    values = conninfo_to_dict(conninfo)
    identity = "\n".join(
        str(values.get(key, "")) for key in ("host", "port", "dbname")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(identity).hexdigest()}"


def _client(client_root: Path, name: str) -> Path:
    if client_root.is_symlink():
        raise RuntimeViolation(
            "RECOVERY-CLIENT",
            "the fixed PostgreSQL client installation is unavailable",
        )
    root = client_root.resolve(strict=True)
    executable = root / "bin" / (f"{name}.exe" if os.name == "nt" else name)
    if (
        not root.is_dir()
        or root.is_symlink()
        or not executable.is_file()
        or executable.is_symlink()
    ):
        raise RuntimeViolation(
            "RECOVERY-CLIENT",
            "the fixed PostgreSQL client installation is unavailable",
        )
    return executable


def _pg_environment(conninfo: str) -> dict[str, str]:
    environment = dict(os.environ)
    values = conninfo_to_dict(conninfo)
    variables = {
        "host": "PGHOST",
        "port": "PGPORT",
        "dbname": "PGDATABASE",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
    }
    for key, variable in variables.items():
        value = values.get(key)
        if value:
            environment[variable] = str(value)
    return environment


def _run_client(arguments: list[str], *, conninfo: str, code: str) -> None:
    try:
        completed = subprocess.run(
            arguments,
            env=_pg_environment(conninfo),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise RuntimeViolation(code, "the PostgreSQL recovery command failed") from None
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        detail = " ".join(detail.split())[:1024]
        raise RuntimeViolation(
            code,
            "the PostgreSQL recovery command failed"
            + (f": {detail}" if detail else ""),
        )


def _table_counts(
    connection: psycopg.Connection[tuple[Any, ...]],
) -> list[dict[str, object]]:
    names = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT relation.relname
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'armi' AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """
        ).fetchall()
    ]
    result: list[dict[str, object]] = []
    for name in names:
        row = connection.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier("armi"), sql.Identifier(name)
            )
        ).fetchone()
        if row is None:
            raise RuntimeViolation(
                "RECOVERY-DATABASE-EVIDENCE",
                "database recovery evidence is incomplete",
            )
        result.append({"name": name, "rows": int(row[0])})
    return result


def _database_evidence(
    connection: psycopg.Connection[tuple[Any, ...]],
) -> dict[str, object]:
    connection.execute("SET ROLE armi_owner")
    active = connection.execute(
        "SELECT count(*) FROM armi.runtime_instances WHERE status = 'active'"
    ).fetchone()
    if active is None or int(active[0]) != 0:
        raise RuntimeViolation(
            "RECOVERY-RUNTIME-ACTIVE",
            "the Runtime must be stopped before a recovery backup",
        )
    tables = _table_counts(connection)
    history = [
        [str(value) for value in row]
        for row in connection.execute(
            "SELECT version_num FROM armi.alembic_version"
        ).fetchall()
    ]
    subjects = [
        [str(value) if value is not None else None for value in row]
        for row in connection.execute(
            """
            SELECT subject_id, subject_version, state_epoch, status,
                   current_generation_id, current_bundle_activation_id
            FROM armi.subjects ORDER BY subject_id
            """
        ).fetchall()
    ]
    artifacts = [
        {
            "artifact_id": str(row[0]),
            "content_digest": str(row[1]),
            "byte_size": int(row[2]),
            "storage_locator": str(row[3]),
        }
        for row in connection.execute(
            """
            SELECT artifact_id, content_digest, byte_size, storage_locator
            FROM armi.artifacts
            WHERE retention_status = 'retained' AND integrity_status = 'verified'
            ORDER BY content_digest, artifact_id
            """
        ).fetchall()
    ]
    return {
        "catalog_digest": database_catalog_digest(connection),
        "tables": tables,
        "history": history,
        "subjects": subjects,
        "artifacts": artifacts,
    }


def _copy_artifacts(
    *, data_root: Path, staging: Path, artifacts: list[dict[str, object]]
) -> None:
    unresolved_root = data_root / "artifacts"
    if unresolved_root.is_symlink():
        raise RuntimeViolation(
            "RECOVERY-ARTIFACT-INCOMPLETE",
            "the retained artifact root cannot be a link",
        )
    source_root = unresolved_root.resolve(strict=True)
    target_root = staging / "artifacts"
    target_root.mkdir()
    for item in artifacts:
        locator = cast(str, item["storage_locator"])
        relative = Path(locator)
        unresolved_source = unresolved_root / relative
        source = unresolved_source.resolve(strict=True)
        candidate = unresolved_root
        contains_link = False
        for part in relative.parts:
            candidate /= part
            if candidate.is_symlink():
                contains_link = True
                break
        if (
            not source.is_relative_to(source_root)
            or not source.is_file()
            or contains_link
            or source.stat().st_size != item["byte_size"]
            or _digest_file(source) != item["content_digest"]
        ):
            raise RuntimeViolation(
                "RECOVERY-ARTIFACT-INCOMPLETE",
                "a retained artifact is unavailable or corrupt",
            )
        target = target_root / locator
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _result(
    manifest: dict[str, object], bundle: Path, *, status: str
) -> RecoveryResult:
    database = cast(dict[str, object], manifest["database"])
    tables = cast(list[dict[str, object]], database["tables"])
    artifacts = cast(list[dict[str, object]], manifest["artifacts"])
    return RecoveryResult(
        status=status,
        backup_id=cast(str, manifest["backup_id"]),
        bundle=str(bundle),
        database_digest=cast(str, database["dump_digest"]),
        catalog_digest=cast(str, database["catalog_digest"]),
        table_count=len(tables),
        row_count=sum(cast(int, item["rows"]) for item in tables),
        artifact_count=len(artifacts),
    )


def _resolve_destination(prepared: PreparedEnvironment, destination: Path) -> Path:
    if destination.is_symlink():
        raise RuntimeViolation(
            "RECOVERY-DESTINATION",
            "the recovery destination must be outside the environment root",
        )
    target = destination.resolve(strict=True)
    if (
        not target.is_dir()
        or any(target.iterdir())
        or target == prepared.root
        or target.is_relative_to(prepared.root)
        or prepared.root.is_relative_to(target)
    ):
        raise RuntimeViolation(
            "RECOVERY-DESTINATION",
            "the recovery destination must be outside the environment root",
        )
    return target


def create_recovery_backup(
    prepared: PreparedEnvironment,
    *,
    postgresql_client_root: Path,
    destination: Path,
) -> RecoveryResult:
    runtime = RuntimeProcessManager(
        prepared.root,
        str(prepared.effective.config.environment.environment_id),
    ).status()
    if runtime["status"] != "stopped":
        raise RuntimeViolation(
            "RECOVERY-RUNTIME-ACTIVE",
            "the Runtime must be stopped before a recovery backup",
        )
    target_root = _resolve_destination(prepared, destination)
    backup_id = uuid7()
    name = f"armi-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{backup_id}"
    staging = target_root / f".{name}.staging"
    bundle = target_root / name
    if staging.exists() or bundle.exists():
        raise RuntimeViolation(
            "RECOVERY-DESTINATION",
            "the recovery destination already exists",
        )
    locator = prepared.effective.config.secret_locators.get("database.migrator")
    if locator is None:
        raise RuntimeViolation(
            "RECOVERY-CREDENTIAL", "the migrator credential is unavailable"
        )
    dump = _client(postgresql_client_root, "pg_dump")
    staging.mkdir()
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.recovery")
        ) as handle:

            def create(value: memoryview) -> dict[str, object]:
                conninfo = bytes(value).decode("utf-8", "strict")
                with psycopg.connect(conninfo) as connection:
                    evidence = _database_evidence(connection)
                dump_path = staging / "database.dump"
                _run_client(
                    [
                        os.fspath(dump),
                        "--role=armi_owner",
                        "--format=custom",
                        "--no-owner",
                        "--exclude-schema=armi_extensions",
                        "--exclude-extension=pg_trgm",
                        "--exclude-extension=vector",
                        "--file",
                        os.fspath(dump_path),
                    ],
                    conninfo=conninfo,
                    code="RECOVERY-DATABASE-DUMP",
                )
                if not dump_path.is_file() or dump_path.stat().st_size == 0:
                    raise RuntimeViolation(
                        "RECOVERY-DATABASE-DUMP", "the database dump is unavailable"
                    )
                artifacts = cast(list[dict[str, object]], evidence["artifacts"])
                _copy_artifacts(
                    data_root=prepared.data_root,
                    staging=staging,
                    artifacts=artifacts,
                )
                return {
                    "schema_version": _MANIFEST_SCHEMA,
                    "backup_id": str(backup_id),
                    "environment_id": str(
                        prepared.effective.config.environment.environment_id
                    ),
                    "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "source_connection_identity": _connection_identity(conninfo),
                    "database": {
                        "dump_path": "database.dump",
                        "dump_bytes": dump_path.stat().st_size,
                        "dump_digest": _digest_file(dump_path),
                        "catalog_digest": evidence["catalog_digest"],
                        "history": evidence["history"],
                        "tables": evidence["tables"],
                        "subjects": evidence["subjects"],
                    },
                    "artifacts": artifacts,
                }

            manifest = handle.consume(create)
        _write_manifest(staging / "manifest.json", manifest)
        staging.replace(bundle)
        return _result(manifest, bundle, status="created")
    except Exception:
        if staging.is_dir() and staging.parent == target_root:
            shutil.rmtree(staging)
        raise


def _read_manifest(bundle: Path) -> tuple[Path, dict[str, object]]:
    if bundle.is_symlink():
        raise RuntimeViolation("RECOVERY-BUNDLE", "the recovery bundle is invalid")
    root = bundle.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeViolation("RECOVERY-BUNDLE", "the recovery bundle is invalid")
    manifest_path = root / "manifest.json"
    try:
        raw = manifest_path.read_bytes()
        value = json.loads(raw.decode("utf-8", "strict"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        raise RuntimeViolation(
            "RECOVERY-BUNDLE", "the recovery manifest is invalid"
        ) from None
    if type(value) is not dict:
        raise RuntimeViolation("RECOVERY-BUNDLE", "the recovery manifest is invalid")
    manifest = cast(dict[str, object], value)
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        raise RuntimeViolation("RECOVERY-BUNDLE", "the recovery manifest is invalid")
    return root, manifest


def verify_recovery_backup(bundle: Path) -> RecoveryResult:
    root, manifest = _read_manifest(bundle)
    try:
        database = cast(dict[str, object], manifest["database"])
        dump = (root / cast(str, database["dump_path"])).resolve(strict=True)
        if (
            not dump.is_relative_to(root)
            or not dump.is_file()
            or dump.is_symlink()
            or dump.stat().st_size != database["dump_bytes"]
            or _digest_file(dump) != database["dump_digest"]
        ):
            raise ValueError
        for item in cast(list[dict[str, object]], manifest["artifacts"]):
            artifact = (
                root / "artifacts" / cast(str, item["storage_locator"])
            ).resolve(strict=True)
            if (
                not artifact.is_relative_to(root / "artifacts")
                or not artifact.is_file()
                or artifact.is_symlink()
                or artifact.stat().st_size != item["byte_size"]
                or _digest_file(artifact) != item["content_digest"]
            ):
                raise ValueError
    except KeyError, OSError, TypeError, ValueError:
        raise RuntimeViolation(
            "RECOVERY-BUNDLE", "the recovery bundle is corrupt"
        ) from None
    return _result(manifest, root, status="verified")


def _read_conninfo(path: Path) -> str:
    if path.is_symlink():
        raise RuntimeViolation("RECOVERY-TARGET", "the recovery target is invalid")
    resolved = path.resolve(strict=True)
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or resolved.stat().st_size > _MAX_CONNINFO_BYTES
    ):
        raise RuntimeViolation("RECOVERY-TARGET", "the recovery target is invalid")
    try:
        return resolved.read_text(encoding="utf-8").strip()
    except OSError, UnicodeError:
        raise RuntimeViolation(
            "RECOVERY-TARGET", "the recovery target is invalid"
        ) from None


def _reject_nonempty_target(conninfo: str) -> None:
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            """
            SELECT count(*)
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_catalog.pg_depend AS dependency
              ON dependency.objid = relation.oid AND dependency.deptype = 'e'
            WHERE namespace.nspname NOT IN (
                    'pg_catalog', 'information_schema', 'armi_extensions'
                  )
              AND namespace.nspname NOT LIKE 'pg_toast%'
              AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
              AND dependency.objid IS NULL
            """
        ).fetchone()
    if row is None or int(row[0]) != 0:
        raise RuntimeViolation(
            "RECOVERY-TARGET-NOT-EMPTY", "the recovery target database is not empty"
        )


def drill_recovery_backup(
    bundle: Path,
    *,
    quarantine_root: Path,
    target_conninfo_file: Path,
    postgresql_client_root: Path,
) -> RecoveryResult:
    verified = verify_recovery_backup(bundle)
    root, manifest = _read_manifest(bundle)
    if quarantine_root.is_symlink():
        raise RuntimeViolation(
            "RECOVERY-QUARANTINE", "the recovery quarantine root must be empty"
        )
    quarantine = quarantine_root.resolve(strict=True)
    if not quarantine.is_dir() or quarantine.is_symlink() or any(quarantine.iterdir()):
        raise RuntimeViolation(
            "RECOVERY-QUARANTINE", "the recovery quarantine root must be empty"
        )
    conninfo = _read_conninfo(target_conninfo_file)
    if _connection_identity(conninfo) == manifest.get("source_connection_identity"):
        raise RuntimeViolation(
            "RECOVERY-TARGET-SOURCE",
            "the recovery drill cannot target the source database",
        )
    _reject_nonempty_target(conninfo)
    restore = _client(postgresql_client_root, "pg_restore")
    database = cast(dict[str, object], manifest["database"])
    dump = root / cast(str, database["dump_path"])
    target_database = conninfo_to_dict(conninfo).get("dbname")
    if not isinstance(target_database, str) or not target_database:
        raise RuntimeViolation("RECOVERY-TARGET", "the recovery target is invalid")
    _run_client(
        [
            os.fspath(restore),
            "--single-transaction",
            "--exit-on-error",
            "--no-owner",
            "--role=armi_owner",
            "--dbname",
            target_database,
            os.fspath(dump),
        ],
        conninfo=conninfo,
        code="RECOVERY-RESTORE",
    )
    artifact_target = quarantine / "artifacts"
    shutil.copytree(root / "artifacts", artifact_target, symlinks=False)
    with psycopg.connect(conninfo) as connection:
        restored = _database_evidence(connection)
    if (
        restored["catalog_digest"] != database["catalog_digest"]
        or restored["history"] != database["history"]
        or restored["tables"] != database["tables"]
        or restored["subjects"] != database["subjects"]
    ):
        raise RuntimeViolation(
            "RECOVERY-RESTORE-DRIFT",
            "the restored database does not match the backup",
        )
    for item in cast(list[dict[str, object]], manifest["artifacts"]):
        artifact = artifact_target / cast(str, item["storage_locator"])
        if (
            not artifact.is_file()
            or artifact.stat().st_size != item["byte_size"]
            or _digest_file(artifact) != item["content_digest"]
        ):
            raise RuntimeViolation(
                "RECOVERY-RESTORE-ARTIFACT",
                "the restored artifacts do not match the backup",
            )
    del verified
    return _result(manifest, root, status="drill_passed")


__all__ = (
    "RecoveryResult",
    "create_recovery_backup",
    "drill_recovery_backup",
    "verify_recovery_backup",
)
