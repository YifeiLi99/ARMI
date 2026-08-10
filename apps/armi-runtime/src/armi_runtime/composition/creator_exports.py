"""Creator-owned local complete-data export with explicit completeness semantics."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResult,
    CreatorExportStatus,
    CreatorExportViolation,
    RuntimeFence,
    TransactionIsolation,
)
from armi_kernel.contracts import Digest, ErrorCategory, Instant, Purpose, TraceId
from psycopg import sql

from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

_EXPORT_FORMAT = "armi.creator-local-export.v1"


@dataclass(frozen=True, slots=True)
class _ArtifactSnapshot:
    ref: ArtifactRef
    logical_kind: str


@dataclass(frozen=True, slots=True)
class _SnapshotResult:
    tables: tuple[dict[str, Any], ...]
    artifacts: tuple[_ArtifactSnapshot, ...]
    row_count: int
    snapshot_at: str


class CreatorExportService(CreatorExportPort):
    """Persist an idempotent export record and materialize one restricted directory."""

    __slots__ = (
        "_creator_party_id",
        "_exports_root",
        "_storage",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        data_root: Path,
        storage: ContentAddressedArtifactStore,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    ) -> None:
        if creator_party_id.version != 7 or not data_root.is_absolute():
            raise CreatorExportViolation("CREATOR-EXPORT-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._exports_root = data_root / "exports"
        self._storage = storage
        self._uow_factory = unit_of_work_factory

    async def open(self) -> None:
        try:
            await self._uow_factory.open()
            await asyncio.to_thread(self._prepare_root)
        except DatabaseTransactionError, OSError:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._uow_factory.close()

    async def export(self, command: CreatorExportCommand) -> CreatorExportResult:
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "directory_name": command.directory_name,
                    "format": _EXPORT_FORMAT,
                }
            )
        )
        export_id, created = await self._register(command, request_digest)
        if not created:
            result = await self.get(export_id)
            if result is None:
                raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE")
            return result

        destination = self._destination(command.directory_name)
        staging = self._exports_root / f".{export_id}.staging"
        try:
            await asyncio.to_thread(self._create_staging, staging, destination)
            snapshot = await self._write_snapshot(staging)
            copied, missing = await self._copy_artifacts(staging, snapshot.artifacts)
            status = (
                CreatorExportStatus.COMPLETED
                if not missing
                else CreatorExportStatus.PARTIAL
            )
            manifest = self._manifest(
                export_id=export_id,
                command=command,
                snapshot=snapshot,
                copied=copied,
                missing=missing,
                status=status,
            )
            manifest_bytes = _pretty_json(manifest)
            await asyncio.to_thread(
                (staging / "manifest.json").write_bytes,
                manifest_bytes,
            )
            await asyncio.to_thread(os.replace, staging, destination)
            return await self._settle(
                export_id=export_id,
                trace_id=command.trace_id,
                status=status,
                table_count=len(snapshot.tables),
                row_count=snapshot.row_count,
                artifact_count=copied,
                missing=missing,
                error_code=None,
            )
        except CreatorExportViolation:
            await self._settle_failed(export_id, command.trace_id)
            raise
        except ArtifactViolation, DatabaseTransactionError, OSError, ValueError:
            await self._settle_failed(export_id, command.trace_id)
            raise CreatorExportViolation("CREATOR-EXPORT-FAILED") from None
        finally:
            await asyncio.to_thread(_remove_staging, staging, self._exports_root)

    async def get(self, export_id: UUID) -> CreatorExportResult | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        """
                        SELECT creator_export_id, status, directory_name,
                               destination_path, table_count,
                               row_count, artifact_count, missing_artifacts,
                               error_code, created_at, completed_at
                        FROM armi.creator_exports
                        WHERE creator_export_id = %s AND creator_party_id = %s
                        """,
                        (export_id, self._creator_party_id),
                    )
                ).fetchone()
        except DatabaseTransactionError:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None
        return None if row is None else self._result(row, newly_created=False)

    async def _register(
        self,
        command: CreatorExportCommand,
        request_digest: Digest,
    ) -> tuple[UUID, bool]:
        destination = str(self._destination(command.directory_name))
        export_id = uuid7()
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"creator-export:{self._creator_party_id}",),
                )
                existing = await (
                    await connection.execute(
                        """
                        SELECT creator_export_id, directory_name, idempotency_key,
                               request_digest
                        FROM armi.creator_exports
                        WHERE creator_party_id = %s
                          AND (idempotency_key = %s OR directory_name = %s)
                        FOR UPDATE
                        """,
                        (
                            self._creator_party_id,
                            command.idempotency_key.value,
                            command.directory_name,
                        ),
                    )
                ).fetchone()
                if existing is not None:
                    if str(existing[2]) != command.idempotency_key.value:
                        raise CreatorExportViolation("CREATOR-EXPORT-DIRECTORY-EXISTS")
                    if (
                        str(existing[1]) != command.directory_name
                        or str(existing[3]) != request_digest.value
                    ):
                        raise CreatorExportViolation(
                            "CREATOR-EXPORT-IDEMPOTENCY-CONFLICT"
                        )
                    return UUID(str(existing[0])), False
                row = await (
                    await connection.execute(
                        """
                        INSERT INTO armi.creator_exports (
                            creator_export_id, creator_party_id, directory_name,
                            idempotency_key, request_digest, status, destination_path
                        ) VALUES (%s, %s, %s, %s, %s, 'running', %s)
                        RETURNING creator_export_id
                        """,
                        (
                            export_id,
                            self._creator_party_id,
                            command.directory_name,
                            command.idempotency_key.value,
                            request_digest.value,
                            destination,
                        ),
                    )
                ).fetchone()
                if row is None:
                    raise CreatorExportViolation("CREATOR-EXPORT-STATE")
                await unit_of_work.audit.append(
                    self._audit(
                        export_id=export_id,
                        trace_id=command.trace_id,
                        operation="creator.export.requested",
                        status=AuditResultStatus.ACCEPTED,
                    )
                )
                return export_id, True
        except CreatorExportViolation:
            raise
        except DatabaseTransactionError:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def _write_snapshot(self, staging: Path) -> _SnapshotResult:
        database_dir = staging / "database"
        await asyncio.to_thread(database_dir.mkdir)
        tables: list[dict[str, Any]] = []
        artifacts: tuple[_ArtifactSnapshot, ...] = ()
        total_rows = 0
        try:
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.REPEATABLE_READ,
                read_only=True,
            ) as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                snapshot_row = await (
                    await connection.execute("SELECT transaction_timestamp()")
                ).fetchone()
                if snapshot_row is None:
                    raise CreatorExportViolation("CREATOR-EXPORT-SNAPSHOT")
                snapshot_at = str(snapshot_row[0])
                table_rows = await (
                    await connection.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'armi' AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """
                    )
                ).fetchall()
                for (table_name_value,) in table_rows:
                    table_name = str(table_name_value)
                    rows = await (
                        await connection.execute(
                            sql.SQL(
                                "SELECT to_jsonb(source) FROM {} AS source "
                                "ORDER BY to_jsonb(source)::text"
                            ).format(sql.Identifier("armi", table_name))
                        )
                    ).fetchall()
                    payload = b"".join(rfc8785.dumps(row[0]) + b"\n" for row in rows)
                    relative_path = f"database/{table_name}.jsonl"
                    await asyncio.to_thread(
                        (staging / relative_path).write_bytes,
                        payload,
                    )
                    tables.append(
                        {
                            "name": table_name,
                            "role": _table_role(table_name),
                            "path": relative_path,
                            "row_count": len(rows),
                        }
                    )
                    total_rows += len(rows)
                artifact_rows = await (
                    await connection.execute(
                        """
                        SELECT artifact_id, content_digest, byte_size, media_type,
                               logical_kind, privacy_scope, integrity_status
                        FROM armi.artifacts
                        ORDER BY content_digest
                        """
                    )
                ).fetchall()
                artifacts = tuple(_artifact_snapshot(row) for row in artifact_rows)
        except DatabaseTransactionError:
            raise
        return _SnapshotResult(
            tables=tuple(tables),
            artifacts=artifacts,
            row_count=total_rows,
            snapshot_at=snapshot_at,
        )

    async def _copy_artifacts(
        self,
        staging: Path,
        artifacts: tuple[_ArtifactSnapshot, ...],
    ) -> tuple[int, tuple[str, ...]]:
        target = staging / "artifacts"
        await asyncio.to_thread(target.mkdir)
        copied = 0
        missing: list[str] = []
        for artifact in artifacts:
            digest = artifact.ref.content_digest.value
            content = b""
            try:
                async with await self._storage.open_verified(artifact.ref) as stream:
                    content = await stream.read()
            except ArtifactViolation, OSError:
                missing.append(digest)
                continue
            await asyncio.to_thread(
                (target / digest.removeprefix("sha256:")).write_bytes,
                content,
            )
            copied += 1
        return copied, tuple(sorted(set(missing)))

    async def _settle(
        self,
        *,
        export_id: UUID,
        trace_id: TraceId,
        status: CreatorExportStatus,
        table_count: int,
        row_count: int,
        artifact_count: int,
        missing: tuple[str, ...],
        error_code: str | None,
    ) -> CreatorExportResult:
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        """
                        UPDATE armi.creator_exports
                        SET status = %s, table_count = %s,
                            row_count = %s, artifact_count = %s,
                            missing_artifacts = %s::jsonb, error_code = %s,
                            completed_at = clock_timestamp()
                        WHERE creator_export_id = %s AND creator_party_id = %s
                          AND status = 'running'
                        RETURNING creator_export_id, status, directory_name,
                                  destination_path, table_count,
                                  row_count, artifact_count, missing_artifacts,
                                  error_code, created_at, completed_at
                        """,
                        (
                            status.value,
                            table_count,
                            row_count,
                            artifact_count,
                            json.dumps(missing),
                            error_code,
                            export_id,
                            self._creator_party_id,
                        ),
                    )
                ).fetchone()
                if row is None:
                    raise CreatorExportViolation("CREATOR-EXPORT-STATE")
                await unit_of_work.audit.append(
                    self._audit(
                        export_id=export_id,
                        trace_id=trace_id,
                        operation=f"creator.export.{status.value}",
                        status=(
                            AuditResultStatus.COMPLETED
                            if status is CreatorExportStatus.COMPLETED
                            else AuditResultStatus.UNKNOWN
                            if status is CreatorExportStatus.PARTIAL
                            else AuditResultStatus.FAILED
                        ),
                        error_category=(
                            ErrorCategory("integrity")
                            if status is CreatorExportStatus.PARTIAL
                            else ErrorCategory("internal")
                            if status is CreatorExportStatus.FAILED
                            else None
                        ),
                    )
                )
                return self._result(row, newly_created=True)
        except CreatorExportViolation:
            raise
        except DatabaseTransactionError:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def _settle_failed(self, export_id: UUID, trace_id: TraceId) -> None:
        with suppress(CreatorExportViolation):
            await self._settle(
                export_id=export_id,
                trace_id=trace_id,
                status=CreatorExportStatus.FAILED,
                table_count=0,
                row_count=0,
                artifact_count=0,
                missing=(),
                error_code="CREATOR-EXPORT-FAILED",
            )

    def _manifest(
        self,
        *,
        export_id: UUID,
        command: CreatorExportCommand,
        snapshot: _SnapshotResult,
        copied: int,
        missing: tuple[str, ...],
        status: CreatorExportStatus,
    ) -> dict[str, Any]:
        return {
            "format": _EXPORT_FORMAT,
            "export_id": str(export_id),
            "status": status.value,
            "created_at": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "database_snapshot_at": snapshot.snapshot_at,
            "scope": {
                "database": "all_current_armi_base_tables",
                "artifacts": "all_registered_retained_artifacts",
                "includes_derived_data": True,
                "derived_data_is_authoritative": False,
            },
            "exclusions": [],
            "directory_name": command.directory_name,
            "tables": list(snapshot.tables),
            "artifacts": {
                "registered": len(snapshot.artifacts),
                "copied": copied,
                "missing_or_corrupt": list(missing),
                "path": "artifacts/<sha256-hex>",
            },
        }

    def _destination(self, directory_name: str) -> Path:
        destination = self._exports_root / directory_name
        try:
            destination.relative_to(self._exports_root)
        except ValueError:
            raise CreatorExportViolation("CREATOR-EXPORT-PATH") from None
        return destination

    def _prepare_root(self) -> None:
        self._exports_root.mkdir(parents=True, exist_ok=True)
        if self._exports_root.is_symlink() or not self._exports_root.is_dir():
            raise OSError("unsafe export root")

    @staticmethod
    def _create_staging(staging: Path, destination: Path) -> None:
        if destination.exists() or destination.is_symlink() or staging.exists():
            raise CreatorExportViolation("CREATOR-EXPORT-DIRECTORY-EXISTS")
        staging.mkdir(parents=False)

    @staticmethod
    def _result(row: tuple[Any, ...], *, newly_created: bool) -> CreatorExportResult:
        return CreatorExportResult(
            export_id=UUID(str(row[0])),
            status=CreatorExportStatus(str(row[1])),
            directory_name=str(row[2]),
            destination_path=str(row[3]),
            table_count=int(row[4]),
            row_count=int(row[5]),
            artifact_count=int(row[6]),
            missing_artifacts=tuple(str(item) for item in row[7]),
            error_code=None if row[8] is None else str(row[8]),
            created_at=Instant(row[9].astimezone(UTC)),
            completed_at=None if row[10] is None else Instant(row[10].astimezone(UTC)),
            newly_created=newly_created,
        )

    def _audit(
        self,
        *,
        export_id: UUID,
        trace_id: TraceId,
        operation: str,
        status: AuditResultStatus,
        error_category: ErrorCategory | None = None,
    ) -> AuditDraft:
        return AuditDraft(
            audit_event_id=AuditEventId(uuid7()),
            actor=AuditReference("creator", self._creator_party_id),
            purpose=Purpose("creator.data.export"),
            operation=operation,
            target=AuditReference("creator_export", export_id),
            result_status=status,
            trace_id=trace_id,
            sensitivity=AuditSensitivity.RESTRICTED,
            error_category=error_category,
        )


def _artifact_snapshot(row: tuple[Any, ...]) -> _ArtifactSnapshot:
    return _ArtifactSnapshot(
        ref=ArtifactRef(
            artifact_id=ArtifactId(UUID(str(row[0]))),
            content_digest=Digest(str(row[1])),
            byte_size=int(row[2]),
            media_type=str(row[3]),
            logical_kind=str(row[4]),
            privacy_scope=ArtifactPrivacyScope(str(row[5])),
            integrity_status=ArtifactIntegrityStatus(str(row[6])),
        ),
        logical_kind=str(row[4]),
    )


def _table_role(table_name: str) -> str:
    if table_name in {"audit_events", "effect_attempts", "web_evidence_items"}:
        return "audit_or_evidence"
    if table_name.endswith(("_projections", "_snapshots")):
        return "derived_projection"
    if table_name in {"runtime_instances", "runtime_leases", "outbox_entries"}:
        return "runtime_operation"
    return "authoritative_or_durable_record"


def _pretty_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _remove_staging(path: Path, exports_root: Path) -> None:
    if (
        not path.is_absolute()
        or path.parent != exports_root
        or not path.name.startswith(".")
        or not path.name.endswith(".staging")
        or not path.exists()
        or path.is_symlink()
    ):
        return
    shutil.rmtree(path)


def build_creator_export_service(
    conninfo: str,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
) -> CreatorExportService:
    return CreatorExportService(
        creator_party_id=creator_party_id,
        data_root=data_root,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
    )


__all__ = ("CreatorExportService", "build_creator_export_service")
