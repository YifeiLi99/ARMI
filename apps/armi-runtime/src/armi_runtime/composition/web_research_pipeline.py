"""Inactive S034 bridge from committed research intent to S033 custody."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid7

from armi_kernel.application import (
    ArtifactViolation,
    LockPlan,
    WebObservationDraft,
    WebObservationRequestId,
    WebResearchIntentPort,
    WebResearchViolation,
    WorkViolation,
)

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
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
    """Explicitly callable S034 bridge; composition does not start it before live gate."""

    __slots__ = (
        "_custody",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
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
        self._diagnostic = diagnostic or _ignore_diagnostic

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
        lease = records[0].lease
        assert lease is not None
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit:
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
            async with self._factory.unit_of_work(LockPlan()) as unit:
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
        if not value or snapshot.query_digest != snapshot.query_artifact.content_digest:
            raise WebResearchViolation("WEB-RESEARCH-ARTIFACT")
        return value


__all__ = ("WebResearchAdmissionPipeline",)
