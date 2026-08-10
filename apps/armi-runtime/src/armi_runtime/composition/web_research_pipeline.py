"""S034 bridge from committed research intent to S033 custody."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import (
    ArtifactViolation,
    RuntimeFence,
    WebObservationDraft,
    WebObservationRequestId,
    WebResearchIntentPort,
    WebResearchViolation,
    WorkLease,
    WorkViolation,
)

from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.persistence.web_evidence import (
    PostgreSQLWebEvidenceRepository,
    WebResearchIntentSnapshot,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .web_search_pipeline import WebSearchPipeline

_WORK_KIND = "web.observation.admit"
Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class WebResearchAdmissionPipeline(WebResearchIntentPort):
    """Admit committed S034 intents when the exact Web binding is active."""

    __slots__ = (
        "_custody",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
        "_stop",
        "_storage",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        custody: WebSearchPipeline,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._custody = custody
        self._repository = PostgreSQLWebEvidenceRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None
        except ArtifactViolation:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def admit_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        try:
            async with self._factory.unit_of_work() as unit:
                snapshot = await self._repository.intent_snapshot(unit, lease)
            query = await self._read_query(snapshot)
            record = await self._custody.admit(
                WebObservationDraft(
                    WebObservationRequestId(uuid7()),
                    snapshot.subject_id,
                    snapshot.runtime_fence,
                    snapshot.idempotency_key,
                    query,
                    snapshot.trace_id,
                )
            )
            async with self._factory.unit_of_work() as unit:
                await self._repository.mark_admitted(
                    unit,
                    lease=lease,
                    snapshot=snapshot,
                    request_id=record.request_id,
                )
            return True
        except WebResearchViolation:
            raise
        except ArtifactViolation:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT") from None
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("web.research.admission.transient_failure")
            return True

    async def _read_query(self, snapshot: WebResearchIntentSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.query_artifact)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT") from None
        if not value:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT")
        return value

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.admit_once()
            except WebResearchViolation:
                worked = False
            await asyncio.sleep(0 if worked else 1)


def build_web_research_admission_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    custody: WebSearchPipeline,
    diagnostic: Diagnostic | None = None,
) -> WebResearchAdmissionPipeline:
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return WebResearchAdmissionPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        custody=custody,
        diagnostic=diagnostic,
    )


__all__ = (
    "WebResearchAdmissionPipeline",
    "build_web_research_admission_pipeline",
)
