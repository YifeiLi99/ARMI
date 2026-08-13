"""Runtime coordination for opportunity selection and Context episode creation."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid7

import rfc8785
from armi_codex.api import CodexContextReadPort, CodexTaskSourceReadPort
from armi_cognition.api import (
    CognitionContextEpisodeDraft,
    CognitionContextEpisodeSnapshot,
    CognitionContextLifecyclePort,
    CognitionRuntimeStateSnapshot,
)
from armi_context.api import (
    ContextEpisodeState,
    ContextRuntimeSubjectSnapshot,
    ContextViolation,
)
from armi_data_rights.api import DataRightsCognitionGate
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionCognitionReadPort
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CognitiveEpisodeId,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)
from armi_opportunity.api import (
    OpportunityCognitionCandidate,
    OpportunityCognitionSelectionPort,
    OpportunityCognitionSelectionScope,
    OpportunitySelectionCursor,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
)
from armi_sleep.api import MaintenancePhase, SleepReadPort
from armi_web_observation.api import WebContextReadPort

_MECHANISM = "armi.context-compiler.layered-v2"


class RuntimeCognitionState:
    async def current_subject(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> ContextRuntimeSubjectSnapshot:
        row = await (
            await transaction.execute(
                """SELECT subject_id, subject_version, state_epoch,
                      current_generation_id, current_bundle_activation_id
               FROM armi.subjects WHERE subject_id=%s AND singleton_key=1
                 AND status='active'""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise ContextViolation("CTX-SUBJECT-NOT-ACTIVE")
        return ContextRuntimeSubjectSnapshot(
            row[0], int(row[1]), int(row[2]), row[3], row[4]
        )

    async def current_state(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> CognitionRuntimeStateSnapshot:
        value = await self.current_subject(transaction, subject_id=subject_id)
        return CognitionRuntimeStateSnapshot(
            value.subject_id,
            value.subject_version,
            value.state_epoch,
            value.generation_id,
            value.bundle_activation_id,
        )


class RuntimeContextEpisodeAdapter:
    def __init__(self, owner: CognitionContextLifecyclePort) -> None:
        self._owner = owner

    async def context_episode(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> ContextEpisodeState:
        return _context_episode(
            await self._owner.context_episode(transaction, episode_id=episode_id)
        )

    async def mark_context_prepared(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        manifest_artifact_id: UUID,
        compiled_artifact_id: UUID,
        context_digest: Digest,
    ) -> ContextEpisodeState:
        return _context_episode(
            await self._owner.mark_context_prepared(
                transaction,
                episode_id=episode_id,
                manifest_artifact_id=manifest_artifact_id,
                compiled_artifact_id=compiled_artifact_id,
                context_digest=context_digest,
            )
        )

    async def fail_context(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID, error_code: str
    ) -> ContextEpisodeState:
        return _context_episode(
            await self._owner.fail_context(
                transaction, episode_id=episode_id, error_code=error_code
            )
        )


class RuntimeCognitionCycleSelector:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        opportunities: OpportunityCognitionSelectionPort,
        episodes: CognitionContextLifecyclePort,
        sleep: SleepReadPort,
        data_rights: DataRightsCognitionGate,
        evidence: EvidenceReadPort,
        interaction: InteractionCognitionReadPort,
        web: WebContextReadPort,
        codex_context: CodexContextReadPort,
        codex_sources: CodexTaskSourceReadPort,
        effects: EffectOperationReadPort,
        expression: ExpressionIntentReadPort,
    ) -> None:
        self._factory = factory
        self._opportunities = opportunities
        self._episodes = episodes
        self._sleep = sleep
        self._data_rights = data_rights
        self._evidence = evidence
        self._interaction = interaction
        self._web = web
        self._codex_context = codex_context
        self._codex_sources = codex_sources
        self._effects = effects
        self._expression = expression

    async def select_once(self) -> CognitiveEpisodeId | None:
        async with self._factory.unit_of_work() as unit:
            fence = unit.runtime_fence
            if fence is None:
                raise ContextViolation("CTX-RUNTIME-FENCE-REQUIRED")
            state = await RuntimeCognitionState().current_subject(
                unit.transaction, subject_id=fence.subject_id
            )
            maintenance = await self._sleep.active_maintenance(
                unit.transaction, subject_id=fence.subject_id
            )
            purpose = (
                None
                if maintenance is None
                else {
                    MaintenancePhase.MEMORY_MAINTENANCE: "maintain_subjective_memory",
                    MaintenancePhase.SELF_CHECK: "perform_subject_self_check",
                }.get(maintenance.phase)
            )
            scope = OpportunityCognitionSelectionScope(
                fence.subject_id,
                None if maintenance is None else maintenance.current_revision_id,
                None if maintenance is None else maintenance.head_version,
                purpose,
            )
            cursor = None
            while True:
                candidate = await self._opportunities.next_candidate(
                    unit.transaction, scope=scope, after=cursor
                )
                if candidate is None:
                    return None
                cursor = OpportunitySelectionCursor(
                    candidate.available_after, candidate.opportunity_id
                )
                if (
                    candidate.context_party_id is not None
                    and await self._data_rights.blocks_cognition(
                        unit,
                        requester_party_id=candidate.context_party_id,
                        opportunity_purpose=candidate.purpose,
                    )
                ):
                    continue
                if not await self._opportunities.select_for_cognition(
                    unit.transaction, opportunity_id=candidate.opportunity_id
                ):
                    continue
                episode_id = uuid7()
                trace = await self._trace(unit.transaction, candidate)
                if not await self._episodes.create_context_episode(
                    unit.transaction,
                    CognitionContextEpisodeDraft(
                        episode_id,
                        candidate.opportunity_id,
                        candidate.subject_id,
                        candidate.scene_id,
                        candidate.context_party_id,
                        candidate.purpose,
                        state.subject_version,
                        state.state_epoch,
                        state.bundle_activation_id,
                        _MECHANISM,
                        trace,
                    ),
                ):
                    raise ContextViolation("CTX-EPISODE-DUPLICATE")
                now_row = await (
                    await unit.transaction.execute("SELECT statement_timestamp()")
                ).fetchone()
                if now_row is None:
                    raise ContextViolation("CTX-RUNTIME-CLOCK-UNAVAILABLE")
                now = Instant(now_row[0])
                work_digest = Digest.from_bytes(
                    rfc8785.dumps(
                        {
                            "episode_id": str(episode_id),
                            "opportunity_id": str(candidate.opportunity_id),
                        }
                    )
                )
                await unit.work.enqueue(
                    WorkDraft(
                        WorkId(uuid7()),
                        "cognition.context.prepare",
                        WorkOwner("cognitive_episode", episode_id),
                        IdempotencyKey(f"context:{candidate.opportunity_id}"),
                        work_digest,
                        50,
                        now,
                        Instant(now.value + timedelta(seconds=3600)),
                        2,
                        trace,
                        SubjectId(candidate.subject_id),
                        WorkPayloadRef("cognitive_episode", episode_id),
                    )
                )
                await unit.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", unit.environment_id),
                        Purpose("cognition.context"),
                        "opportunity.selected",
                        AuditReference("opportunity", candidate.opportunity_id),
                        AuditResultStatus.APPLIED,
                        trace,
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(candidate.subject_id),
                        request=AuditReference("cognitive_episode", episode_id),
                    )
                )
                return CognitiveEpisodeId(episode_id)

    async def _trace(
        self,
        transaction: PostgreSQLTransaction,
        candidate: OpportunityCognitionCandidate,
    ) -> TraceId:
        if candidate.evidence_id is None:
            return TraceId(candidate.opportunity_id.hex)
        evidence = await self._evidence.snapshot(
            transaction, evidence_id=EvidenceId(candidate.evidence_id)
        )
        if evidence.interaction_id is not None:
            return await self._interaction.interaction_trace(
                transaction, interaction_id=evidence.interaction_id
            )
        if evidence.web_observation_request_id is not None:
            return await self._web.request_trace(
                transaction, request_id=evidence.web_observation_request_id
            )
        if evidence.codex_task_source_id is not None:
            return (
                await self._codex_sources.task_source(
                    transaction, task_source_id=evidence.codex_task_source_id
                )
            ).trace_id
        if evidence.codex_verification_id is not None:
            effect_id = await self._codex_context.verification_effect_id(
                transaction, verification_id=evidence.codex_verification_id
            )
            effect = await self._effects.by_effect_id(transaction, effect_id=effect_id)
            if effect is None:
                raise ContextViolation("CTX-CODEX-EFFECT-MISSING")
            intent = await self._expression.revision_snapshot(
                transaction,
                action_intent_revision_id=effect.action_intent_revision_id,
            )
            if intent.codex_task_source_id is None:
                raise ContextViolation("CTX-CODEX-SOURCE-MISSING")
            return (
                await self._codex_sources.task_source(
                    transaction, task_source_id=intent.codex_task_source_id
                )
            ).trace_id
        raise ContextViolation("CTX-EVIDENCE-SOURCE-MISSING")


def _context_episode(value: CognitionContextEpisodeSnapshot) -> ContextEpisodeState:
    return ContextEpisodeState(
        value.episode_id,
        value.opportunity_id,
        value.subject_id,
        value.scene_id,
        value.context_party_id,
        value.purpose,
        value.base_subject_version,
        value.base_state_epoch,
        value.bundle_activation_id,
        value.mechanism_identity,
        value.trace_id,
        value.life_query_intent_id,
        value.life_query_result_artifact_id,
    )


__all__ = (
    "RuntimeCognitionCycleSelector",
    "RuntimeCognitionState",
    "RuntimeContextEpisodeAdapter",
)
