"""PostgreSQL owner for S034 research intent and evidence acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RuntimeFence,
    WebEvidenceAcceptanceResult,
    WebEvidenceSourceId,
    WebObservationAttemptId,
    WebObservationRequestId,
    WebResearchIntentId,
    WebResearchViolation,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork

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

    __slots__ = ()

    async def intent_snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> WebResearchIntentSnapshot:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise WebResearchViolation("WEB-RESEARCH-FENCE")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT intent.web_research_intent_id, intent.subject_id,
                       intent.source_opportunity_id, intent.scene_id,
                       intent.context_party_id, intent.query_artifact_id,
                       intent.query_digest, intent.idempotency_key,
                       intent.trace_id
                FROM armi.durable_work AS work
                JOIN armi.web_research_intents AS intent
                  ON intent.admission_work_id = work.work_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'web.observation.admit'
                  AND work.owner_kind = 'web_research_intent'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND intent.status = 'pending'
                FOR UPDATE OF work, intent
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
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
            await _artifact_ref(connection, row[5]),
            Digest(str(row[6])),
            IdempotencyKey(str(row[7])),
            TraceId(str(row[8])),
            fence,
        )

    async def mark_admitted(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebResearchIntentSnapshot,
        request_id: WebObservationRequestId,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
                request_digest=snapshot.query_digest,
            )
        )

    async def accept_evidence(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        request_id: WebObservationRequestId,
        attempt_id: WebObservationAttemptId,
        evidence_artifact_id: ArtifactId,
        source_artifact_ids: tuple[ArtifactId, ...],
        evidence_digest: Digest,
        sources: tuple[tuple[int, Digest, Digest, Digest], ...],
    ) -> WebEvidenceAcceptanceResult | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        opportunity_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, interaction_id, subject_id, scene_id,
                creator_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status, web_observation_request_id,
                observation_attempt_id, schema_version
            ) VALUES (
                %s, NULL, %s, %s, %s, %s, 'web_search', 'external_claim',
                'private', 'accepted', %s, %s, 1
            )
            """,
            (
                evidence_id,
                row[1],
                row[2],
                row[3],
                evidence_artifact_id.value,
                request_id.value,
                attempt_id.value,
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
                    title_digest, citation_digest, acquisition_kind, schema_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    'provider_synthesis_citation', 1
                )
                """,
                (
                    WebEvidenceSourceId(uuid7()).value,
                    evidence_id,
                    attempt_id.value,
                    source[0],
                    artifact_id.value,
                    source[1].value,
                    source[2].value,
                    source[3].value,
                ),
            )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, source_kind, source_ref,
                source_version, source_digest, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no, schema_version
            ) VALUES (
                %s, %s, %s, %s, %s, 'consider_web_evidence',
                'external_evidence', %s, 1, %s,
                'eligible', 'open', %s, NULL, 0, 1
            )
            """,
            (
                opportunity_id,
                evidence_id,
                row[1],
                row[2],
                row[3],
                evidence_id,
                evidence_digest.value,
                opportunity_id,
            ),
        )
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
                response_digest=evidence_digest,
                artifact_digest=evidence_digest,
            )
        )
        return WebEvidenceAcceptanceResult(
            intent_id,
            request_id,
            evidence_id,
            opportunity_id,
            evidence_digest,
        )


async def _artifact_ref(connection: Any, artifact_id: UUID) -> ArtifactRef:
    row = await (
        await connection.execute(
            """
            SELECT artifact_id, content_digest, media_type, byte_size,
                   logical_kind, privacy_scope, integrity_status
            FROM armi.artifacts
            WHERE artifact_id = %s AND retention_status = 'retained'
            """,
            (artifact_id,),
        )
    ).fetchone()
    if row is None:
        raise WebResearchViolation("WEB-RESEARCH-ARTIFACT")
    return ArtifactRef(
        ArtifactId(row[0]),
        Digest(str(row[1])),
        int(row[3]),
        str(row[2]),
        str(row[4]),
        ArtifactPrivacyScope(str(row[5])),
        ArtifactIntegrityStatus(str(row[6])),
        1,
    )


__all__ = ("PostgreSQLWebEvidenceRepository", "WebResearchIntentSnapshot")
