"""Commit accepted Codex delegation intents in the caller's subject transaction."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Purpose, SubjectId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._delegation_contract import CodexDelegationDraft, CodexDelegationViolation
from .api import CodexCommitContext


class PostgreSQLCodexCommit:
    __slots__ = ()

    async def commit_delegations(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CodexCommitContext,
        commit_id: UUID,
        delegations: tuple[CodexDelegationDraft, ...],
    ) -> None:
        if type(commit_id) is not UUID or commit_id.version != 7:
            raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-ID")
        if not delegations:
            return
        if len(delegations) != 1:
            raise CodexDelegationViolation("CODEX-DELEGATION-COUNT")
        draft = delegations[0]
        connection = unit_of_work.transaction
        validation = await (
            await connection.execute(
                """
                SELECT validation_status
                FROM armi.cognitive_candidate_validation_items
                WHERE candidate_validation_id = %s AND proposal_ref = %s
                  AND owner_kind = 'codex_delegation'
                """,
                (context.validation_id, draft.proposal_ref),
            )
        ).fetchone()
        source = await (
            await connection.execute(
                """
                SELECT task_manifest_digest, validator_id
                FROM armi.codex_task_sources
                WHERE codex_task_source_id = %s AND subject_id = %s
                """,
                (draft.task_source_id.value, context.subject_id),
            )
        ).fetchone()
        if (
            validation is None
            or str(validation[0]) != "accepted"
            or source is None
            or str(source[0]) != draft.task_manifest_digest.value
            or str(source[1]) != draft.validator_id
        ):
            raise CodexDelegationViolation("CODEX-DELEGATION-VALIDATION")
        action_id = uuid7()
        revision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.action_intents (
                action_intent_id, subject_id, scene_id,
                context_party_id, root_opportunity_id, purpose,
                action_kind, current_revision_id, operation_ref) VALUES (
                %s, %s, %s, %s, %s, 'delegate_codex_work',
                'codex_delegation', NULL, %s)
            """,
            (
                action_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                context.root_opportunity_id,
                context.root_opportunity_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.action_intent_revisions (
                action_intent_revision_id, action_intent_id, revision_no,
                capability_kind, operation_class, purpose,
                candidate_validation_id, proposal_ref, subject_commit_id,
                codex_task_source_id, task_manifest_digest, validator_id) VALUES (
                %s, %s, 1, 'codex.delegated-work', 'execute',
                'delegate_codex_work', %s, %s, %s, %s, %s, %s)
            """,
            (
                revision_id,
                action_id,
                context.validation_id,
                draft.proposal_ref,
                commit_id,
                draft.task_source_id.value,
                draft.task_manifest_digest.value,
                draft.validator_id,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.action_intents
            SET current_revision_id = %s
            WHERE action_intent_id = %s
            """,
            (revision_id, action_id),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("subject.commit"),
                "codex.delegation.intent.recorded",
                AuditReference("action_intent", action_id),
                AuditResultStatus.ACCEPTED,
                context.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(context.subject_id),
                request=AuditReference("cognitive_episode", context.episode_id),
            )
        )


__all__ = ("PostgreSQLCodexCommit",)
