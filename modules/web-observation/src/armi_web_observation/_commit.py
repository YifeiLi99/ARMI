"""Commit web-research intents inside the caller-owned subject transaction."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import IdempotencyKey, Instant, Purpose, SubjectId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._research_contract import WebResearchRequestDraft, WebResearchViolation
from .api import WebResearchCommitContext


class PostgreSQLWebResearchCommit:
    __slots__ = ()

    async def commit_requests(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: WebResearchCommitContext,
        commit_id: UUID,
        requests: tuple[WebResearchRequestDraft, ...],
        query_artifact: ArtifactRef | None,
    ) -> None:
        if type(commit_id) is not UUID or commit_id.version != 7:
            raise WebResearchViolation("WEB-RESEARCH-COMMIT-ID")
        if not requests:
            if query_artifact is not None:
                raise WebResearchViolation("WEB-RESEARCH-ARTIFACT")
            return
        if len(requests) != 1 or query_artifact is None:
            raise WebResearchViolation("WEB-RESEARCH-COUNT")
        request = requests[0]
        connection = unit_of_work.transaction
        now_row = await (
            await connection.execute("SELECT statement_timestamp()")
        ).fetchone()
        if now_row is None:
            raise WebResearchViolation("WEB-RESEARCH-DATABASE")
        intent_id = uuid7()
        work_id = WorkId(uuid7())
        await unit_of_work.work.enqueue(
            WorkDraft(
                work_id,
                "web.observation.admit",
                WorkOwner("web_research_intent", intent_id),
                IdempotencyKey(f"web-intent:{context.opportunity_id}"),
                query_artifact.content_digest,
                40,
                Instant(now_row[0]),
                Instant(now_row[0] + timedelta(seconds=3600)),
                2,
                context.trace_id,
                SubjectId(context.subject_id),
                WorkPayloadRef("artifact", query_artifact.artifact_id.value),
            )
        )
        await connection.execute(
            """
            INSERT INTO armi.web_research_intents (
                web_research_intent_id, subject_commit_id, source_opportunity_id,
                subject_id, scene_id, creator_party_id, proposal_ref, purpose,
                operation_class, query_artifact_id, query_digest, idempotency_key,
                admission_work_id, status, trace_id) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 'public_web_research',
                'search_read_public', %s, %s, %s, %s, 'pending', %s)
            """,
            (
                intent_id,
                commit_id,
                context.opportunity_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                request.proposal_ref,
                query_artifact.artifact_id.value,
                query_artifact.content_digest.value,
                f"intent:{intent_id}",
                work_id.value,
                context.trace_id.value,
            ),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("subject.commit"),
                "web.research.intent.recorded",
                AuditReference("web_research_intent", intent_id),
                AuditResultStatus.ACCEPTED,
                context.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(context.subject_id),
                request=AuditReference("cognitive_episode", context.episode_id),
            )
        )


__all__ = ("PostgreSQLWebResearchCommit",)
