"""PostgreSQL owner for S034 research intent and evidence acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_attention.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RuntimeFence,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Purpose, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._observation_contract import WebObservationAttemptId, WebObservationRequestId
from ._research_contract import (
    WebEvidenceAcceptanceResult,
    WebEvidenceSourceId,
    WebResearchIntentId,
    WebResearchViolation,
)
from .api import WebArtifactCatalogPort

_ADMISSION_WORK = "web.observation.admit"


@dataclass(frozen=True, slots=True)
class WebResearchIntentSnapshot:
    intent_id: WebResearchIntentId
    subject_id: SubjectId
    source_opportunity_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    query_artifact: ArtifactRef
    query_digest: Digest
    idempotency_key: IdempotencyKey
    trace_id: TraceId
    runtime_fence: RuntimeFence


class PostgreSQLWebEvidenceRepository:
    """Own fixed SQL for the inactive S034 admission and evidence path."""

    __slots__ = ("_catalog", "_evidence", "_opportunity")

    def __init__(
        self,
        catalog: WebArtifactCatalogPort,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
    ) -> None:
        self._catalog = catalog
        self._evidence = evidence
        self._opportunity = opportunity

    async def fail_admission(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        code: str,
    ) -> None:
        connection = unit_of_work.transaction
        updated = await (
            await connection.execute(
                """
                UPDATE armi.web_research_intents AS intent
                SET status = 'failed', completed_at = statement_timestamp()
                WHERE intent.admission_work_id = %s
                  AND intent.status = 'pending'
                RETURNING intent.web_research_intent_id
                """,
                (lease.work_id.value,),
            )
        ).fetchone()
        if updated is None:
            raise WebResearchViolation("WEB-RESEARCH-WORK-STALE")
        await unit_of_work.work.fail(lease, error_code=code)

    async def intent_snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
    ) -> WebResearchIntentSnapshot:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise WebResearchViolation("WEB-RESEARCH-FENCE")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT intent.web_research_intent_id, intent.subject_id,
                       intent.source_opportunity_id, intent.scene_id,
                       intent.context_party_id, intent.query_artifact_id,
                       intent.query_digest, intent.idempotency_key,
                       intent.trace_id
                FROM armi.web_research_intents AS intent
                WHERE intent.admission_work_id = %s
                  AND intent.status = 'pending'
                FOR UPDATE OF intent
                """,
                (lease.work_id.value,),
            )
        ).fetchone()
        if row is None:
            raise WebResearchViolation("WEB-RESEARCH-WORK-STALE")
        if row[1] != fence.subject_id:
            raise WebResearchViolation("WEB-RESEARCH-FENCE")
        return WebResearchIntentSnapshot(
            WebResearchIntentId(row[0]),
            SubjectId(row[1]),
            row[2],
            row[3],
            row[4],
            await self._catalog.get(unit_of_work, ArtifactId(row[5])),
            Digest(str(row[6])),
            IdempotencyKey(str(row[7])),
            TraceId(str(row[8])),
            fence,
        )

    async def mark_admitted(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebResearchIntentSnapshot,
        request_id: WebObservationRequestId,
    ) -> None:
        connection = unit_of_work.transaction
        updated = await (
            await connection.execute(
                """
                UPDATE armi.web_research_intents
                SET web_observation_request_id = %s, status = 'admitted'
                WHERE web_research_intent_id = %s AND status = 'pending'
                RETURNING web_research_intent_id
                """,
                (request_id.value, snapshot.intent_id.value),
            )
        ).fetchone()
        if updated is None:
            raise WebResearchViolation("WEB-RESEARCH-WORK-STALE")
        await connection.execute(
            """
            UPDATE armi.web_observation_requests
            SET web_research_intent_id = %s
            WHERE web_observation_request_id = %s
              AND web_research_intent_id IS NULL
            """,
            (snapshot.intent_id.value, request_id.value),
        )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("web_observation", request_id.value),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("public_web_research"),
                "web.research.admitted",
                AuditReference("web_research_intent", snapshot.intent_id.value),
                AuditResultStatus.ACCEPTED,
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=snapshot.subject_id,
                request=AuditReference("web_observation", request_id.value),
            )
        )

    async def accept_evidence(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        request_id: WebObservationRequestId,
        attempt_id: WebObservationAttemptId,
        evidence_artifact_id: ArtifactId,
        source_artifact_ids: tuple[ArtifactId, ...],
        sources: tuple[tuple[int, Digest], ...],
    ) -> WebEvidenceAcceptanceResult | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT intent.web_research_intent_id, intent.subject_id,
                       intent.scene_id, intent.context_party_id, intent.trace_id
                FROM armi.web_research_intents AS intent
                WHERE intent.web_observation_request_id = %s
                  AND intent.status = 'admitted'
                FOR UPDATE
                """,
                (request_id.value,),
            )
        ).fetchone()
        if row is None:
            return None
        if len(source_artifact_ids) != len(sources):
            raise WebResearchViolation("WEB-EVIDENCE-SOURCE")
        intent_id = WebResearchIntentId(row[0])
        evidence_id = uuid7()
        await self._evidence.accept(
            unit_of_work,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=row[1],
                scene_id=row[2],
                context_party_id=row[3],
                artifact_id=evidence_artifact_id.value,
                source_kind=EvidenceSourceKind.WEB_SEARCH,
                privacy_scope=EvidencePrivacyScope.PRIVATE,
                web_observation_request_id=request_id.value,
                observation_attempt_id=attempt_id.value,
            ),
        )
        for source, artifact_id in zip(
            sources,
            source_artifact_ids,
            strict=True,
        ):
            await connection.execute(
                """
                INSERT INTO armi.web_evidence_sources (
                    web_evidence_source_id, evidence_id, observation_attempt_id,
                    citation_no, source_artifact_id, canonical_url_digest,
                    acquisition_kind) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    'provider_synthesis_citation')
                """,
                (
                    WebEvidenceSourceId(uuid7()).value,
                    evidence_id,
                    attempt_id.value,
                    source[0],
                    artifact_id.value,
                    source[1].value,
                ),
            )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=row[1],
                scene_id=row[2],
                context_party_id=row[3],
                purpose=OpportunityPurpose.CONSIDER_WEB_EVIDENCE,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise WebResearchViolation("WEB-EVIDENCE-ADMISSION")
        opportunity_id = admitted.opportunity_id
        if opportunity_id is None:
            raise WebResearchViolation("WEB-EVIDENCE-ADMISSION")
        await connection.execute(
            """
            UPDATE armi.web_research_intents
            SET status = 'succeeded', completed_at = statement_timestamp()
            WHERE web_research_intent_id = %s AND status = 'admitted'
            """,
            (intent_id.value,),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("public_web_research"),
                "web.evidence.accepted",
                AuditReference("external_evidence", evidence_id),
                AuditResultStatus.ACCEPTED,
                TraceId(str(row[4])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(row[1]),
                request=AuditReference("web_observation", request_id.value),
            )
        )
        return WebEvidenceAcceptanceResult(
            intent_id,
            request_id,
            evidence_id,
            opportunity_id,
        )


__all__ = ("PostgreSQLWebEvidenceRepository", "WebResearchIntentSnapshot")
