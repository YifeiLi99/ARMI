"""Runtime application assembler for the Creator action projection."""

from __future__ import annotations

from uuid import UUID

from armi_capability.api import (
    CapabilityAuthorizationOutcome,
    CapabilityOperationReadPort,
    CapabilityPolicyDecisionSnapshot,
)
from armi_codex.api import CodexExecutionReadPort, CodexTaskSourceReadPort
from armi_cognition.api import CognitionOperationReadPort
from armi_effect.api import EffectOperationReadPort, EffectStatus
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort, ExpressionOperationSnapshot
from armi_interaction.api import (
    CreatorCodexExecutionSummary,
    CreatorInputTransactionPort,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorOperationQueryPort,
    OpportunityId,
)
from armi_opportunity.api import OpportunityOperationReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory


class RuntimeCreatorOperationAssembler(CreatorOperationQueryPort):
    """Combine owner-authored snapshots inside one read transaction."""

    __slots__ = (
        "_capability",
        "_codex",
        "_codex_executions",
        "_cognition",
        "_creator_party_id",
        "_effect",
        "_evidence",
        "_expression",
        "_factory",
        "_interaction",
        "_opportunity",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        creator_party_id: UUID,
        opportunity: OpportunityOperationReadPort,
        cognition: CognitionOperationReadPort,
        interaction: CreatorInputTransactionPort,
        evidence: EvidenceReadPort,
        expression: ExpressionIntentReadPort,
        capability: CapabilityOperationReadPort,
        effect: EffectOperationReadPort,
        codex: CodexTaskSourceReadPort,
        codex_executions: CodexExecutionReadPort,
    ) -> None:
        self._factory = factory
        self._creator_party_id = creator_party_id
        self._opportunity = opportunity
        self._cognition = cognition
        self._interaction = interaction
        self._evidence = evidence
        self._expression = expression
        self._capability = capability
        self._effect = effect
        self._codex = codex
        self._codex_executions = codex_executions

    async def get(self, opportunity_id: OpportunityId) -> CreatorOperation:
        async with self._factory.unit_of_work(read_only=True) as unit_of_work:
            transaction = unit_of_work.transaction
            opportunity = await self._opportunity.operation_snapshot(
                transaction,
                root_opportunity_id=opportunity_id.value,
                context_party_id=self._creator_party_id,
            )
            if opportunity is None:
                raise CreatorInputViolation("SCOPE-OPERATION-NOT-VISIBLE")
            evidence = await self._evidence.snapshot(
                transaction,
                evidence_id=EvidenceId(opportunity.evidence_id),
            )
            codex_digest = None
            if evidence.codex_task_source_id is not None:
                task = await self._codex.task_source(
                    transaction,
                    task_source_id=evidence.codex_task_source_id,
                )
                codex_digest = task.task_manifest_digest
            acceptance = await self._interaction.operation_acceptance(
                transaction,
                interaction_id=evidence.interaction_id,
                scene_id=opportunity.scene_id,
                creator_party_id=self._creator_party_id,
                codex_content_digest=codex_digest,
                evidence_id=opportunity.evidence_id,
                opportunity_id=opportunity.root_opportunity_id,
            )
            if acceptance is None:
                raise CreatorInputViolation("SCOPE-OPERATION-NOT-VISIBLE")
            cognition = await self._cognition.operation_snapshot(
                transaction,
                opportunity_id=opportunity.current_opportunity_id,
            )
            expression = await self._expression.operation_snapshot(
                transaction,
                operation_ref=opportunity.root_opportunity_id,
            )
            policy = None
            effect = None
            if expression is not None and expression.intent_revision_id is not None:
                policy = await self._capability.policy_for_revision(
                    transaction,
                    action_intent_revision_id=expression.intent_revision_id,
                )
            if expression is not None and expression.intent_id is not None:
                effect = await self._effect.by_action_intent(
                    transaction,
                    action_intent_id=expression.intent_id,
                )
            phase, failure_code = _derive_phase(
                disposition=opportunity.disposition,
                reconsideration_no=opportunity.reconsideration_no,
                episode_status=cognition.episode_status,
                cognition_failure=cognition.failure_code,
                application_resolution=cognition.application_resolution,
                expression=expression,
                policy=policy,
                effect_status=None if effect is None else effect.status,
            )
            codex_execution = None
            if (
                effect is not None
                and evidence.codex_task_source_id is not None
                and _operation_kind(expression) == "codex_delegation"
            ):
                execution = await self._codex_executions.execution_for_effect(
                    transaction,
                    effect_id=effect.effect_id,
                    task_source_id=evidence.codex_task_source_id,
                )
                if execution is not None:
                    codex_execution = CreatorCodexExecutionSummary(
                        execution.task_source_id,
                        execution.verification_id,
                        execution.execution_status,
                        execution.model_id,
                        execution.sdk_identity,
                        execution.validator_id,
                        execution.source_tree_digest,
                        execution.final_tree_digest,
                    )
            return CreatorOperation(
                acceptance=acceptance,
                phase=phase,
                failure_code=failure_code,
                subject_version=(
                    cognition.observed_subject_version
                    if phase is CreatorOperationPhase.APPLIED
                    else None
                ),
                effect_ref=(
                    None
                    if effect is None or not _phase_has_effect(phase)
                    else effect.effect_id
                ),
                intent_ref=None if expression is None else expression.intent_id,
                dialogue_decision_ref=(
                    None if expression is None else expression.dialogue_decision_id
                ),
                policy_decision_ref=(
                    None if policy is None else policy.policy_decision_id
                ),
                operation_kind=_operation_kind(expression),
                codex_execution=codex_execution,
            )


def _derive_phase(
    *,
    disposition: str,
    reconsideration_no: int,
    episode_status: str | None,
    cognition_failure: str | None,
    application_resolution: str | None,
    expression: ExpressionOperationSnapshot | None,
    policy: CapabilityPolicyDecisionSnapshot | None,
    effect_status: EffectStatus | None,
) -> tuple[CreatorOperationPhase, str | None]:
    if expression is not None:
        decision_kind = expression.decision_kind
        action_kind = expression.action_kind
        if decision_kind == "decline":
            return CreatorOperationPhase.FORMAL_DECLINED, None
        if decision_kind == "silence":
            return CreatorOperationPhase.FORMAL_NO_ACTION, None
        if decision_kind == "defer":
            return CreatorOperationPhase.DEFERRED, None
        if decision_kind == "end_conversation":
            return CreatorOperationPhase.COMPLETED, None
        if action_kind is not None:
            if policy is None:
                return (
                    CreatorOperationPhase.CODEX_CAPABILITY_DECISION
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.RESPONSE_ADMISSION,
                    None,
                )
            outcome = policy.outcome
            reason_code = policy.reason_code
            if outcome is CapabilityAuthorizationOutcome.DENIED:
                return CreatorOperationPhase.RESPONSE_UNAUTHORIZED, reason_code
            if outcome is CapabilityAuthorizationOutcome.UNAVAILABLE:
                return CreatorOperationPhase.RESPONSE_UNAVAILABLE, reason_code
            if effect_status is None:
                return CreatorOperationPhase.EFFECT_REGISTRATION, None
            phases = {
                EffectStatus.REGISTERED: CreatorOperationPhase.EFFECT_REGISTERED,
                EffectStatus.DISPATCHING: (
                    CreatorOperationPhase.CODEX_DISPATCHING
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.EFFECT_DISPATCHING
                ),
                EffectStatus.COMPLETED: (
                    CreatorOperationPhase.CODEX_COMPLETED
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.EFFECT_COMPLETED
                ),
                EffectStatus.FAILED: (
                    CreatorOperationPhase.CODEX_FAILED
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.EFFECT_FAILED
                ),
                EffectStatus.UNKNOWN: (
                    CreatorOperationPhase.CODEX_UNKNOWN
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.EFFECT_UNKNOWN
                ),
                EffectStatus.CANCELLED: (
                    CreatorOperationPhase.CODEX_CANCELLED
                    if action_kind == "codex_delegation"
                    else CreatorOperationPhase.EFFECT_CANCELLED
                ),
            }
            phase = phases[effect_status]
            return (
                phase,
                "ACTION-EFFECT-FAILED"
                if effect_status in {EffectStatus.FAILED, EffectStatus.UNKNOWN}
                else None,
            )
    cognition_phases = {
        "preparing": CreatorOperationPhase.CONTEXT_PREPARING,
        "prepared": CreatorOperationPhase.CONTEXT_PREPARED,
        "calling_model": CreatorOperationPhase.MODEL_CALLING,
        "model_returned": CreatorOperationPhase.MODEL_RETURNED,
        "validating": CreatorOperationPhase.CANDIDATE_VALIDATING,
        "candidate_validated": CreatorOperationPhase.CANDIDATE_VALIDATED,
        "committing": CreatorOperationPhase.SUBJECT_COMMITTING,
        "candidate_rejected": CreatorOperationPhase.CANDIDATE_REJECTED,
    }
    if disposition == "open" and episode_status is None:
        return CreatorOperationPhase.ACCEPTED, None
    if episode_status in cognition_phases:
        phase = cognition_phases[episode_status]
        return (
            phase,
            cognition_failure
            if phase is CreatorOperationPhase.CANDIDATE_REJECTED
            else None,
        )
    if disposition == "resolved" and application_resolution == "applied":
        return CreatorOperationPhase.APPLIED, None
    if disposition == "resolved" and application_resolution in {
        "no_change",
        "declined",
    }:
        return CreatorOperationPhase.COMPLETED, None
    if disposition == "resolved" and application_resolution == "deferred":
        return CreatorOperationPhase.DEFERRED, None
    if disposition == "resolved" and application_resolution == "need_information":
        return CreatorOperationPhase.NEED_INFORMATION, None
    if (
        disposition == "resolved"
        and application_resolution == "stale"
        and reconsideration_no == 1
    ):
        return CreatorOperationPhase.STALE_CONFLICT, "CONFLICT_SUBJECT_STATE_STALE"
    if disposition in {"selected", "resolved", "cancelled"} and episode_status in {
        "failed",
        "cancelled",
    }:
        return CreatorOperationPhase.FAILED, cognition_failure
    raise CreatorInputViolation("DB-INPUT-STATE")


def _phase_has_effect(phase: CreatorOperationPhase) -> bool:
    return phase in {
        CreatorOperationPhase.EFFECT_REGISTERED,
        CreatorOperationPhase.EFFECT_DISPATCHING,
        CreatorOperationPhase.EFFECT_COMPLETED,
        CreatorOperationPhase.EFFECT_FAILED,
        CreatorOperationPhase.EFFECT_UNKNOWN,
        CreatorOperationPhase.EFFECT_CANCELLED,
        CreatorOperationPhase.CODEX_DISPATCHING,
        CreatorOperationPhase.CODEX_VERIFYING,
        CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE,
        CreatorOperationPhase.CODEX_RESULT_REJECTED,
        CreatorOperationPhase.CODEX_COMPLETED,
        CreatorOperationPhase.CODEX_FAILED,
        CreatorOperationPhase.CODEX_UNKNOWN,
        CreatorOperationPhase.CODEX_CANCELLED,
    }


def _operation_kind(expression: ExpressionOperationSnapshot | None) -> str:
    if expression is None:
        return "cognition"
    if expression.dialogue_decision_id is not None and expression.intent_id is None:
        return "formal_dialogue"
    if expression.action_kind == "codex_delegation":
        return "codex_delegation"
    if expression.action_kind == "party_response":
        return "creator_response"
    return "subject_change"
