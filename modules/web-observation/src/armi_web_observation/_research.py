"""S034 bridge from committed research intent to S033 custody."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast
from uuid import uuid7

from armi_attention.api import OpportunityAdmissionPort
from armi_evidence.api import EvidenceWritePort
from armi_kernel.application import (
    ArtifactViolation,
    DurableWorkPort,
    WorkLease,
    WorkViolation,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._evidence_postgresql import (
    PostgreSQLWebEvidenceRepository,
    WebResearchIntentSnapshot,
)
from ._observation_contract import (
    WebObservationAdmissionPort,
    WebObservationDraft,
    WebObservationRequestId,
)
from ._research_contract import WebResearchIntentPort, WebResearchViolation
from .api import WebArtifactCatalogPort, WebArtifactStorePort

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
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: WebArtifactStorePort,
        catalog: WebArtifactCatalogPort,
        work: DurableWorkPort,
        custody: WebObservationAdmissionPort,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._custody = custody
        self._repository = PostgreSQLWebEvidenceRepository(
            catalog, evidence, opportunity
        )
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()

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
        except WebResearchViolation as error:
            if error.code == "WEB-RESEARCH-WORK-STALE":
                return True
            await self._fail(lease, error.code)
            return True
        except ArtifactViolation:
            await self._fail(lease, "WEB-RESEARCH-ARTIFACT")
            return True
        except RuntimeTransactionFailure, WorkViolation:
            self._diagnostic("web.research.admission.transient_failure")
            return True

    async def _fail(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work() as unit:
                await self._repository.fail_admission(
                    unit,
                    lease=lease,
                    code=code,
                )
        except RuntimeTransactionFailure, WebResearchViolation, WorkViolation:
            self._diagnostic("web.research.admission.settlement_deferred")

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


__all__ = ("WebResearchAdmissionPipeline",)
