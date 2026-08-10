"""Explicit, non-startup composition for content-addressed artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
    StorageFinding,
    VerifiedFileStream,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
)
from armi_kernel.contracts import Purpose, TraceId

from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError


@dataclass(frozen=True, slots=True)
class ArtifactOrphanReport:
    schema_version: str
    findings: tuple[StorageFinding, ...]
    counts: tuple[tuple[str, int], ...]

    def safe_view(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "dry_run",
            "counts": dict(self.counts),
            "findings": [
                {
                    "category": finding.category,
                    "artifact_id": finding.artifact_id,
                    "content_digest": finding.content_digest,
                }
                for finding in self.findings
            ],
        }


@dataclass(frozen=True, slots=True)
class ArtifactCleanupReport:
    schema_version: str
    removed_counts: tuple[tuple[str, int], ...]
    removed_bytes: int
    remaining_counts: tuple[tuple[str, int], ...]

    def safe_view(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "applied",
            "removed_counts": dict(self.removed_counts),
            "removed_bytes": self.removed_bytes,
            "remaining_counts": dict(self.remaining_counts),
        }


class ContentAddressedArtifactCoordinator:
    """Coordinate files outside and metadata inside one short UoW."""

    __slots__ = ("_catalog", "_orphan_grace_seconds", "_storage", "_uow_factory")

    def __init__(
        self,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
        *,
        orphan_grace_seconds: int,
    ) -> None:
        self._storage = storage
        self._catalog = catalog
        self._uow_factory = unit_of_work_factory
        self._orphan_grace_seconds = orphan_grace_seconds

    async def put(
        self,
        source: AsyncIterable[bytes],
        policy: ArtifactPolicy,
    ) -> ArtifactRef:
        staged = await self._storage.stage(source, policy)
        published = await self._storage.publish(staged)
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    published,
                )
                if registration.inserted:
                    await unit_of_work.audit.append(
                        self._audit_draft(
                            operation="artifact.catalog.registered",
                            ref=registration.ref,
                            trace_id=policy.producer_trace_id,
                        )
                    )
                return registration.ref
        except ArtifactViolation:
            raise
        except AuditViolation:
            raise ArtifactViolation("ART-AUDIT") from None
        except DatabaseTransactionError as error:
            code = (
                "ART-COMMIT-UNKNOWN"
                if error.code == "DB-TX-COMMIT-UNKNOWN"
                else "ART-DATABASE"
            )
            raise ArtifactViolation(code) from None

    async def open_verified(
        self,
        artifact_id: ArtifactId,
        *,
        trace_id: TraceId,
    ) -> VerifiedFileStream:
        ref = await self._get(artifact_id)
        if ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED:
            raise ArtifactViolation(
                "ART-MISSING"
                if ref.integrity_status is ArtifactIntegrityStatus.MISSING
                else "ART-CORRUPT"
            )
        try:
            return await self._storage.open_verified(ref)
        except ArtifactViolation as error:
            if error.code not in ("ART-MISSING", "ART-CORRUPT"):
                raise
            status = (
                ArtifactIntegrityStatus.MISSING
                if error.code == "ART-MISSING"
                else ArtifactIntegrityStatus.CORRUPT
            )
            try:
                async with self._uow_factory.unit_of_work() as unit_of_work:
                    changed = await self._catalog.mark_integrity(
                        unit_of_work,
                        artifact_id,
                        status,
                    )
                    if changed:
                        await unit_of_work.audit.append(
                            self._audit_draft(
                                operation=f"artifact.integrity.{status.value}",
                                ref=ref,
                                trace_id=trace_id,
                            )
                        )
            except AuditViolation:
                raise ArtifactViolation("ART-AUDIT") from None
            except DatabaseTransactionError:
                raise ArtifactViolation("ART-DATABASE") from None
            raise

    async def report_orphans(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> ArtifactOrphanReport:
        now = observed_at or datetime.now(UTC)
        refs: tuple[ArtifactRef, ...] = ()
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                refs = await self._catalog.all_refs(unit_of_work)
        except DatabaseTransactionError:
            raise ArtifactViolation("ART-DATABASE") from None
        registered = {ref.content_digest.value: ref for ref in refs}
        findings = await self._storage.scan(
            cutoff=now - timedelta(seconds=self._orphan_grace_seconds),
            registered=registered,
        )
        counts = Counter(finding.category for finding in findings)
        return ArtifactOrphanReport(
            schema_version="armi.artifact-report.v1",
            findings=findings,
            counts=tuple(sorted(counts.items())),
        )

    async def cleanup_orphans(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> ArtifactCleanupReport:
        now = observed_at or datetime.now(UTC)
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                refs = await self._catalog.all_refs(unit_of_work)
        except DatabaseTransactionError:
            raise ArtifactViolation("ART-DATABASE") from None
        registered = {ref.content_digest.value: ref for ref in refs}
        result = await self._storage.cleanup(
            cutoff=now - timedelta(seconds=self._orphan_grace_seconds),
            registered=registered,
        )
        remaining = Counter(finding.category for finding in result.remaining)
        return ArtifactCleanupReport(
            schema_version="armi.artifact-cleanup.v1",
            removed_counts=result.removed_counts,
            removed_bytes=result.removed_bytes,
            remaining_counts=tuple(sorted(remaining.items())),
        )

    async def _get(self, artifact_id: ArtifactId) -> ArtifactRef:
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                return await self._catalog.get(unit_of_work, artifact_id)
        except ArtifactViolation:
            raise
        except DatabaseTransactionError:
            raise ArtifactViolation("ART-DATABASE") from None

    def _audit_draft(
        self,
        *,
        operation: str,
        ref: ArtifactRef,
        trace_id: TraceId,
    ) -> AuditDraft:
        sensitivity = {
            ArtifactPrivacyScope.PRIVATE: AuditSensitivity.PRIVATE,
            ArtifactPrivacyScope.RESTRICTED: AuditSensitivity.RESTRICTED,
        }.get(ref.privacy_scope, AuditSensitivity.INTERNAL)
        return AuditDraft(
            audit_event_id=AuditEventId(uuid7()),
            actor=AuditReference("runtime", self._uow_factory.environment_id),
            purpose=Purpose("artifact.catalog"),
            operation=operation,
            target=AuditReference("artifact", ref.artifact_id.value),
            result_status=AuditResultStatus.APPLIED,
            trace_id=trace_id,
            sensitivity=sensitivity,
        )


__all__ = (
    "ArtifactCleanupReport",
    "ArtifactOrphanReport",
    "ContentAddressedArtifactCoordinator",
)
