"""Explicit, non-startup composition for content-addressed artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactRef,
    ArtifactViolation,
    LockPlan,
)

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
    StorageFinding,
    VerifiedFileStream,
)
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
        if (
            type(storage) is not ContentAddressedArtifactStore
            or type(catalog) is not ArtifactCatalogRepository
            or type(unit_of_work_factory) is not PostgreSQLUnitOfWorkFactory
            or type(orphan_grace_seconds) is not int
            or orphan_grace_seconds <= 0
        ):
            raise ArtifactViolation("ART-DECLARATION")
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
            async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    published,
                )
        except ArtifactViolation:
            raise
        except DatabaseTransactionError as error:
            code = (
                "ART-COMMIT-UNKNOWN"
                if error.code == "DB-TX-COMMIT-UNKNOWN"
                else "ART-DATABASE"
            )
            raise ArtifactViolation(code) from None

    async def open_verified(self, artifact_id: ArtifactId) -> VerifiedFileStream:
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
                async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                    await self._catalog.mark_integrity(
                        unit_of_work,
                        artifact_id,
                        status,
                    )
            except DatabaseTransactionError:
                raise ArtifactViolation("ART-DATABASE") from None
            raise

    async def report_orphans(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> ArtifactOrphanReport:
        now = observed_at or datetime.now(UTC)
        if (
            type(now) is not datetime
            or now.tzinfo is None
            or now.utcoffset() != UTC.utcoffset(now)
        ):
            raise ArtifactViolation("ART-ORPHAN-SCAN")
        refs: tuple[ArtifactRef, ...] = ()
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
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

    async def _get(self, artifact_id: ArtifactId) -> ArtifactRef:
        if type(artifact_id) is not ArtifactId:
            raise ArtifactViolation("ART-DECLARATION")
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._catalog.get(unit_of_work, artifact_id)
        except ArtifactViolation:
            raise
        except DatabaseTransactionError:
            raise ArtifactViolation("ART-DATABASE") from None


__all__ = (
    "ArtifactOrphanReport",
    "ContentAddressedArtifactCoordinator",
)
