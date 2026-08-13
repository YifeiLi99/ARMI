"""Validate Codex-owned sources and delegate Expression-owned intent writes."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_expression.api import DelegatedActionIntentDraft, ExpressionCommitPort
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
from .api import CodexCommitContext, CodexTaskSourceReadPort


class PostgreSQLCodexCommit:
    __slots__ = ("_expression", "_sources")

    def __init__(
        self,
        sources: CodexTaskSourceReadPort,
        expression: ExpressionCommitPort,
    ) -> None:
        self._sources = sources
        self._expression = expression

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
        source = await self._sources.task_source(
            unit_of_work.transaction,
            task_source_id=draft.task_source_id.value,
        )
        if (
            source.subject_id != context.subject_id
            or source.task_manifest_digest != draft.task_manifest_digest
            or source.validator_id != draft.validator_id
        ):
            raise CodexDelegationViolation("CODEX-DELEGATION-VALIDATION")
        if context.scene_id is None or context.creator_party_id is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-CONTEXT")
        await self._expression.commit_delegation(
            unit_of_work,
            commit_id=commit_id,
            draft=DelegatedActionIntentDraft(
                context.root_opportunity_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                context.root_opportunity_id,
                context.validation_id,
                draft.proposal_ref,
                draft.task_source_id.value,
                draft.task_manifest_digest,
                draft.validator_id,
            ),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("subject.commit"),
                "codex.delegation.intent.recorded",
                AuditReference("codex_task_source", draft.task_source_id.value),
                AuditResultStatus.ACCEPTED,
                context.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(context.subject_id),
                request=AuditReference("cognitive_episode", context.episode_id),
            )
        )


__all__ = ("PostgreSQLCodexCommit",)
