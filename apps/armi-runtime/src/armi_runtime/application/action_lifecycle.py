"""Runtime-only coordination for the multi-owner action lifecycle."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_capability.api import CapabilityViolation
from armi_codex.api import CodexArtifactReadPort, CodexTaskSourceReadPort
from armi_effect.api import EffectRegistrationContext, EffectViolation
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionEffectRoutePort
from armi_kernel.application import (
    ArtifactId,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
    WorkStatus,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


class RuntimeCodexGrantActivation:
    """Turn an accepted Codex grant into Runtime work without owner SQL leakage."""

    __slots__ = ("_expression",)

    def __init__(self, expression: ExpressionIntentReadPort) -> None:
        self._expression = expression

    async def activate_codex_registration(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_commit_id: UUID,
        grant_id: UUID,
        valid_until: datetime,
    ) -> None:
        transaction = unit_of_work.transaction
        intent = await self._expression.delegation_for_commit(
            transaction,
            subject_commit_id=subject_commit_id,
        )
        if intent is None:
            return
        if intent.codex_task_source_id is None or intent.task_manifest_digest is None:
            raise CapabilityViolation("POLICY-CODEX-SOURCE")
        runtime = await (
            await transaction.execute(
                """
                SELECT trace_id, statement_timestamp()
                FROM armi.subject_commits
                WHERE subject_commit_id=%s
                """,
                (subject_commit_id,),
            )
        ).fetchone()
        if runtime is None or valid_until <= runtime[1]:
            raise CapabilityViolation("POLICY-GRANT-NOT-ACTIVE")
        digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": "armi.codex-delegation.v1",
                    "operation_ref": str(intent.operation_ref),
                    "task_source_id": str(intent.codex_task_source_id),
                    "task_manifest_digest": intent.task_manifest_digest.value,
                    "grant_id": str(grant_id),
                    "delivery_state": "not_started",
                }
            )
        )
        work_id = WorkId(uuid7())
        await unit_of_work.work.enqueue(
            WorkDraft(
                work_id,
                "effect.register",
                WorkOwner("action_intent", intent.action_intent_id),
                IdempotencyKey(f"effect-register:{intent.action_intent_id}"),
                digest,
                60,
                Instant(runtime[1]),
                Instant(valid_until),
                2,
                TraceId(str(runtime[0])),
                subject_id=SubjectId(intent.subject_id),
                payload=WorkPayloadRef("action_intent", intent.action_intent_id),
            )
        )


class RuntimeEffectRegistrationContext:
    """Assemble owner snapshots for Effect without exposing owner tables."""

    __slots__ = ("_artifacts", "_codex", "_expression", "_interaction")

    def __init__(
        self,
        *,
        artifacts: ArtifactCatalogPort,
        codex: CodexTaskSourceReadPort,
        expression: ExpressionIntentReadPort,
        interaction: InteractionEffectRoutePort,
    ) -> None:
        self._artifacts = artifacts
        self._codex = codex
        self._expression = expression
        self._interaction = interaction

    async def resolve(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        work: WorkRecord,
    ) -> EffectRegistrationContext:
        if (
            work.status is not WorkStatus.LEASED
            or work.lease is None
            or work.draft.work_kind != "effect.register"
            or work.draft.owner.kind != "action_intent"
        ):
            raise EffectViolation("EFFECT-WORK-STALE")
        transaction = unit_of_work.transaction
        intent = await self._expression.intent_snapshot(
            transaction,
            action_intent_id=work.draft.owner.reference,
        )
        if intent.response_artifact_id is not None:
            artifact_id = intent.response_artifact_id
            digest = intent.response_digest
            effect_kind = "creator_response"
        elif intent.codex_task_source_id is not None:
            source = await self._codex.task_source(
                transaction,
                task_source_id=intent.codex_task_source_id,
            )
            artifact_id = source.task_manifest_artifact_id
            digest = source.task_manifest_digest
            effect_kind = "codex_delegation"
        else:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        if digest is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        artifact = await self._artifacts.retained_ref_in(
            transaction,
            ArtifactId(artifact_id),
        )
        if artifact is None or artifact.content_digest != digest:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        if effect_kind == "creator_response":
            route = await self._interaction.effect_route(
                transaction,
                scene_id=intent.scene_id,
                context_party_id=intent.context_party_id,
            )
            destination_party_id = route.destination_party_id
            destination_kind = route.destination_kind
            destination_binding_id = route.destination_binding_id
        else:
            destination_party_id = intent.context_party_id
            destination_kind = "codex_workspace"
            destination_binding_id = None
        return EffectRegistrationContext(
            intent.operation_ref,
            intent.root_opportunity_id,
            intent.action_intent_revision_id,
            intent.action_intent_id,
            intent.subject_id,
            intent.scene_id,
            intent.context_party_id,
            artifact_id,
            digest,
            artifact.byte_size,
            work.draft.trace_id,
            effect_kind,
            intent.capability_kind,
            intent.operation_class,
            intent.purpose,
            destination_party_id,
            destination_kind,
            destination_binding_id,
        )


class RuntimeCodexArtifactReference:
    __slots__ = ("_artifacts", "_codex")

    def __init__(
        self,
        *,
        artifacts: ArtifactCatalogPort,
        codex: CodexArtifactReadPort,
    ) -> None:
        self._artifacts = artifacts
        self._codex = codex

    async def artifact_reference(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        effect_id: UUID,
        kind: str,
    ) -> tuple[UUID, Digest, int, str]:
        artifact_id = await self._codex.artifact_ref(
            unit_of_work.transaction,
            effect_id=effect_id,
            kind=kind,
        )
        if artifact_id is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        ref = await self._artifacts.retained_ref_in(
            unit_of_work.transaction,
            artifact_id,
        )
        if ref is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return (
            ref.artifact_id.value,
            ref.content_digest,
            ref.byte_size,
            ref.media_type,
        )


__all__ = (
    "RuntimeCodexArtifactReference",
    "RuntimeCodexGrantActivation",
    "RuntimeEffectRegistrationContext",
)
