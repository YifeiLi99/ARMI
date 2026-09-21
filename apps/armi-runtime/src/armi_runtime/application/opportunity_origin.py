"""Resolve authoritative operation ancestry through the responsible owners."""

from uuid import UUID

from armi_attention.api import OpportunityTransitionPort
from armi_codex.api import CodexContextReadPort
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_runtime_foundation import PostgreSQLTransaction, RuntimeTransactionFailure

HUMAN_INPUT_PURPOSES = frozenset(
    {
        "consider_creator_input",
        "consider_creator_voice_input",
        "consider_other_human_input",
        "consider_codex_task",
    }
)


class RuntimeOpportunityOrigin:
    def __init__(
        self,
        *,
        opportunities: OpportunityTransitionPort,
        evidence: EvidenceReadPort,
        codex: CodexContextReadPort,
        effects: EffectOperationReadPort,
        expression: ExpressionIntentReadPort,
    ) -> None:
        self._opportunities = opportunities
        self._evidence = evidence
        self._codex = codex
        self._effects = effects
        self._expression = expression

    async def resolve(
        self, transaction: PostgreSQLTransaction, operation_id: UUID
    ) -> tuple[UUID, str]:
        seen: set[UUID] = set()
        while operation_id not in seen:
            seen.add(operation_id)
            root_id, evidence_id, purpose = await self._opportunities.origin_snapshot(
                transaction, opportunity_id=operation_id
            )
            if root_id != operation_id:
                operation_id = root_id
                continue
            if purpose != "consider_codex_result":
                return operation_id, purpose
            if evidence_id is None:
                break
            evidence = await self._evidence.snapshot(
                transaction, evidence_id=EvidenceId(evidence_id)
            )
            if evidence.codex_verification_id is None:
                break
            effect_id = await self._codex.verification_effect_id(
                transaction, verification_id=evidence.codex_verification_id
            )
            effect = await self._effects.by_effect_id(transaction, effect_id=effect_id)
            if effect is None or effect.action_intent_id is None:
                break
            intent = await self._expression.intent_snapshot(
                transaction, action_intent_id=effect.action_intent_id
            )
            operation_id = intent.root_opportunity_id
        raise RuntimeTransactionFailure("LIFE-AUTONOMY-CALL-ORIGIN")
