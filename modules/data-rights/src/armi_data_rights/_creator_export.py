"""Creator-owned local complete-data export with explicit completeness semantics."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    TransactionIsolation,
)
from armi_kernel.contracts import Digest, ErrorCategory, Instant, Purpose, TraceId
from armi_runtime_foundation import RuntimeTransactionFailure

from .api import (
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResult,
    CreatorExportStatus,
    CreatorExportViolation,
    DataRightsArtifactStorePort,
    DataRightsExportScope,
    DataRightsOwnerIdentity,
    DataRightsParticipant,
    DataRightsUnitOfWorkFactory,
)

_EXPORT_FORMAT = "armi.creator-export.v2"


@dataclass(frozen=True, slots=True)
class _ArtifactSnapshot:
    ref: ArtifactRef
    logical_kind: str


@dataclass(frozen=True, slots=True)
class _SegmentSnapshot:
    owner: DataRightsOwnerIdentity
    schema_version: int
    name: str
    path: str
    media_type: str
    record_count: int
    digest: Digest


@dataclass(frozen=True, slots=True)
class _SnapshotResult:
    segments: tuple[_SegmentSnapshot, ...]
    artifacts: tuple[_ArtifactSnapshot, ...]
    record_count: int
    snapshot_at: str


class CreatorExportService(CreatorExportPort):
    """Persist an idempotent export record and materialize one restricted directory."""

    __slots__ = (
        "_creator_party_id",
        "_exports_root",
        "_participants",
        "_storage",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        data_root: Path,
        storage: DataRightsArtifactStorePort,
        unit_of_work_factory: DataRightsUnitOfWorkFactory,
        participants: tuple[DataRightsParticipant, ...],
    ) -> None:
        if creator_party_id.version != 7 or not data_root.is_absolute():
            raise CreatorExportViolation("CREATOR-EXPORT-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._exports_root = data_root / "exports"
        self._storage = storage
        self._uow_factory = unit_of_work_factory
        self._participants = participants

    async def open(self) -> None:
        try:
            await asyncio.to_thread(self._prepare_root)
            async with self._uow_factory.unit_of_work() as unit_of_work:
                await unit_of_work.transaction.execute(
                    """UPDATE armi.creator_exports
                       SET status = 'failed',
                           error_code = 'CREATOR-EXPORT-INTERRUPTED',
                           completed_at = statement_timestamp()
                       WHERE creator_party_id = %s AND status = 'running'""",
                    (self._creator_party_id,),
                )
        except RuntimeTransactionFailure, OSError:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def close(self) -> None:
        return None

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
                segment_count=len(snapshot.segments),
                record_count=snapshot.record_count,
                artifact_count=copied,
                missing=missing,
                error_code=None,
            )
        except CreatorExportViolation:
            await self._settle_failed(export_id, command.trace_id)
            raise
        except ArtifactViolation, RuntimeTransactionFailure, OSError, ValueError:
            await self._settle_failed(export_id, command.trace_id)
            raise CreatorExportViolation("CREATOR-EXPORT-FAILED") from None
        finally:
            await asyncio.to_thread(_remove_staging, staging, self._exports_root)

    async def get(self, export_id: UUID) -> CreatorExportResult | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
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
        except RuntimeTransactionFailure:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None
        if row is None:
            return None
        result = self._result(row, newly_created=False)
        if result.status in {
            CreatorExportStatus.COMPLETED,
            CreatorExportStatus.PARTIAL,
        }:
            await asyncio.to_thread(self._verify_published_format, result)
        return result

    async def _register(
        self,
        command: CreatorExportCommand,
        request_digest: Digest,
    ) -> tuple[UUID, bool]:
        destination = str(self._destination(command.directory_name))
        export_id = uuid7()
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                connection = unit_of_work.transaction
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
        except RuntimeTransactionFailure:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def _write_snapshot(self, staging: Path) -> _SnapshotResult:
        owners_dir = staging / "owners"
        await asyncio.to_thread(owners_dir.mkdir)
        segments: list[_SegmentSnapshot] = []
        artifacts: tuple[_ArtifactSnapshot, ...] = ()
        total_rows = 0
        artifact_by_id: dict[UUID, _ArtifactSnapshot] = {}
        seen_paths: set[str] = set()
        try:
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.REPEATABLE_READ,
                read_only=True,
            ) as unit_of_work:
                connection = unit_of_work.transaction
                snapshot_row = await (
                    await connection.execute("SELECT transaction_timestamp()")
                ).fetchone()
                if snapshot_row is None:
                    raise CreatorExportViolation("CREATOR-EXPORT-SNAPSHOT")
                snapshot_at = str(snapshot_row[0])
                scope = DataRightsExportScope(self._creator_party_id)
                for participant in self._participants:
                    owner = participant.owner_identity
                    owner_dir = owners_dir / owner.value
                    await asyncio.to_thread(owner_dir.mkdir, exist_ok=True)
                    for segment in await participant.export(connection, scope):
                        if segment.owner_identity != owner:
                            raise CreatorExportViolation("CREATOR-EXPORT-OWNER")
                        relative_path = (
                            f"owners/{owner.value}/{segment.segment_name}.jsonl"
                        )
                        if relative_path in seen_paths:
                            raise CreatorExportViolation("CREATOR-EXPORT-SEGMENT")
                        seen_paths.add(relative_path)
                        records: list[bytes] = []
                        while batch := await segment.records.read_batch():
                            records.extend(record.value for record in batch)
                        payload = b"".join(records)
                        await asyncio.to_thread(
                            (staging / relative_path).write_bytes, payload
                        )
                        segments.append(
                            _SegmentSnapshot(
                                owner,
                                segment.schema_version.value,
                                segment.segment_name,
                                relative_path,
                                segment.media_type,
                                len(records),
                                Digest.from_bytes(payload),
                            )
                        )
                        total_rows += len(records)
                        for ref in segment.artifact_refs:
                            artifact_by_id[ref.artifact_id.value] = _ArtifactSnapshot(
                                ref, ref.logical_kind
                            )
                artifacts = tuple(
                    artifact_by_id[key] for key in sorted(artifact_by_id, key=str)
                )
        except RuntimeTransactionFailure:
            raise
        return _SnapshotResult(
            segments=tuple(segments),
            artifacts=artifacts,
            record_count=total_rows,
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
        segment_count: int,
        record_count: int,
        artifact_count: int,
        missing: tuple[str, ...],
        error_code: str | None,
    ) -> CreatorExportResult:
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                connection = unit_of_work.transaction
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
                            segment_count,
                            record_count,
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
        except RuntimeTransactionFailure:
            raise CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE") from None

    async def _settle_failed(self, export_id: UUID, trace_id: TraceId) -> None:
        await self._settle(
            export_id=export_id,
            trace_id=trace_id,
            status=CreatorExportStatus.FAILED,
            segment_count=0,
            record_count=0,
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
    ) -> dict[str, object]:
        return {
            "format": _EXPORT_FORMAT,
            "export_id": str(export_id),
            "status": status.value,
            "created_at": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "database_snapshot_at": snapshot.snapshot_at,
            "scope": "owner-authored-current-local-data",
            "directory_name": command.directory_name,
            "segments": [
                {
                    "owner": segment.owner.value,
                    "schema_version": segment.schema_version,
                    "path": segment.path,
                    "media_type": segment.media_type,
                    "record_count": segment.record_count,
                    "digest": segment.digest.value,
                }
                for segment in snapshot.segments
            ],
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

    def _verify_published_format(self, result: CreatorExportResult) -> None:
        manifest_path = self._destination(result.directory_name) / "manifest.json"
        try:
            manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            raise CreatorExportViolation("CREATOR-EXPORT-FORMAT-UNSUPPORTED") from None
        if not isinstance(manifest_value, dict):
            raise CreatorExportViolation("CREATOR-EXPORT-FORMAT-UNSUPPORTED")
        manifest = cast(dict[str, object], manifest_value)
        if manifest.get("format") != _EXPORT_FORMAT:
            raise CreatorExportViolation("CREATOR-EXPORT-FORMAT-UNSUPPORTED")

    @staticmethod
    def _create_staging(staging: Path, destination: Path) -> None:
        if destination.exists() or destination.is_symlink() or staging.exists():
            raise CreatorExportViolation("CREATOR-EXPORT-DIRECTORY-EXISTS")
        staging.mkdir(parents=False)

    @staticmethod
    def _result(row: tuple[object, ...], *, newly_created: bool) -> CreatorExportResult:
        missing_artifacts = cast(tuple[str, ...] | list[str], row[7])
        created_at = cast(datetime, row[9])
        completed_at = cast(datetime | None, row[10])
        return CreatorExportResult(
            export_id=UUID(str(row[0])),
            status=CreatorExportStatus(str(row[1])),
            directory_name=str(row[2]),
            destination_path=str(row[3]),
            segment_count=int(cast(int | str, row[4])),
            record_count=int(cast(int | str, row[5])),
            artifact_count=int(cast(int | str, row[6])),
            missing_artifacts=tuple(missing_artifacts),
            error_code=None if row[8] is None else str(row[8]),
            created_at=Instant(created_at.astimezone(UTC)),
            completed_at=(
                None if completed_at is None else Instant(completed_at.astimezone(UTC))
            ),
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


def _pretty_json(value: dict[str, object]) -> bytes:
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


__all__ = ("CreatorExportService", "_ArtifactSnapshot")
