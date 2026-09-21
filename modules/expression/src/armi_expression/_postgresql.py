"""PostgreSQL owner for committed intention and expression facts."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from armi_interaction.api import (
    InteractionEffectRoutePort,
    InteractionSceneTransitionPort,
)
from armi_kernel.application import (
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Purpose, SubjectId
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    CodexEffectDraft,
    CreatorReplyDraft,
    DeclaredResponseEffectDraft,
    DelegatedActionIntentDraft,
    DialogueDecisionRecordPort,
    ExpressionCommitContext,
    ExpressionEffectRegistrationPort,
    ExpressionVoiceRoutePort,
    FormalNoActionDraft,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
    ResponseChoiceDraft,
    ResponseViolation,
)


class PostgreSQLExpressionOwner:
    """Commit expression choices without owning subject transaction lifetime."""

    __slots__ = (
        "_decisions",
        "_effect_registration",
        "_interaction_routes",
        "_interaction_scenes",
        "_relationship_policy",
        "_relationships",
        "_voice",
    )

    def __init__(
        self,
        relationships: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        effect_registration: ExpressionEffectRegistrationPort,
        interaction_routes: InteractionEffectRoutePort,
        interaction_scenes: InteractionSceneTransitionPort,
        voice: ExpressionVoiceRoutePort,
        decisions: DialogueDecisionRecordPort,
    ) -> None:
        self._relationships = relationships
        self._relationship_policy = relationship_policy
        self._effect_registration = effect_registration
        self._interaction_routes = interaction_routes
        self._interaction_scenes = interaction_scenes
        self._voice = voice
        self._decisions = decisions

    async def commit(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        commit_id: UUID,
        choices: tuple[ResponseChoiceDraft, ...],
        response_artifact: ArtifactRef | None,
    ) -> None:
        if type(commit_id) is not UUID or commit_id.version != 7:
            raise ResponseViolation("SUBJECT-RESPONSE-SCOPE")
        other_replies = tuple(
            item for item in choices if isinstance(item, OtherHumanReplyDraft)
        )
        endings = tuple(
            item for item in choices if isinstance(item, OtherHumanEndConversationDraft)
        )
        if context.opportunity_purpose == "consider_other_human_input":
            if other_replies or endings:
                await self._insert_other_human_action(
                    unit_of_work,
                    context=context,
                    commit_id=commit_id,
                    replies=other_replies,
                    endings=endings,
                    response_artifact=response_artifact,
                )
            else:
                await self._record_other_human_change_terminal(
                    unit_of_work,
                    context=context,
                    choices=choices,
                    response_artifact=response_artifact,
                )
            return

        replies = tuple(item for item in choices if isinstance(item, CreatorReplyDraft))
        if not replies:
            if response_artifact is not None:
                raise ResponseViolation("SUBJECT-RESPONSE-ARTIFACT")
            return
        if len(replies) != 1 or response_artifact is None:
            raise ResponseViolation("SUBJECT-RESPONSE-COUNT")
        reply = replies[0]
        if (
            reply.subject_id != context.subject_id
            or reply.scene_id != context.scene_id
            or reply.creator_party_id != context.creator_party_id
        ):
            raise ResponseViolation("SUBJECT-RESPONSE-SCOPE")
        connection = unit_of_work.transaction
        if context.opportunity_purpose == "consider_autonomous_life":
            relationship = await self._relationships.current_for_party(
                connection,
                subject_id=context.subject_id,
                other_party_id=reply.creator_party_id,
                scope="creator_social",
            )
            if (
                relationship is not None
                and not self._relationship_policy.allows_snapshot_outreach(relationship)
            ):
                raise ResponseViolation("SUBJECT-RELATIONSHIP-BOUNDARY")
        # DESIGN.md: committed intent is immutable; a changed action gets a new ID.
        action_id = uuid7()
        await self._finish_creator_response(
            unit_of_work,
            context=context,
            commit_id=commit_id,
            reply=reply,
            response_artifact=response_artifact,
            action_id=action_id,
        )

    async def commit_delegation(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        commit_id: UUID,
        draft: DelegatedActionIntentDraft,
    ) -> None:
        connection = unit_of_work.transaction
        action_id = uuid7()
        await self._effect_registration.register_codex_delegation(
            connection, CodexEffectDraft(action_id, draft, commit_id)
        )

    async def record_terminal(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        application_id: UUID,
        application_status: str,
        choices: tuple[ResponseChoiceDraft, ...],
        activity_owned: bool,
    ) -> None:
        if type(application_id) is not UUID or application_id.version != 7:
            raise ResponseViolation("SUBJECT-NO-ACTION-SCOPE")
        if context.opportunity_purpose == "consider_other_human_input":
            await self._record_other_human_terminal(
                unit_of_work.transaction,
                context=context,
                application_status=application_status,
            )
            return
        if activity_owned or application_status not in {"declined", "no_action"}:
            return
        decisions = tuple(
            item for item in choices if isinstance(item, FormalNoActionDraft)
        )
        if len(decisions) != 1:
            raise ResponseViolation("SUBJECT-NO-ACTION-COUNT")
        decision = decisions[0]
        connection = unit_of_work.transaction
        await self._decisions.record_dialogue_decision(
            connection,
            context=context,
            decision_kind="silence"
            if decision.kind.value == "no_action"
            else decision.kind.value,
            operation_ref=context.root_opportunity_id,
            proposal_ref=decision.proposal_ref,
            reason_class=decision.reason.value,
        )

    async def _record_other_human_change_terminal(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        choices: tuple[ResponseChoiceDraft, ...],
        response_artifact: ArtifactRef | None,
    ) -> None:
        no_actions = tuple(
            item for item in choices if isinstance(item, FormalNoActionDraft)
        )
        if (
            context.scene_id is None
            or context.other_party_id is None
            or context.creator_party_id is not None
            or response_artifact is not None
            or len(no_actions) > 1
            or len(no_actions) != len(choices)
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-TERMINAL")
        decision_kind = "silence" if no_actions else "defer"
        await self._decisions.record_dialogue_decision(
            unit_of_work.transaction,
            context=context,
            decision_kind=decision_kind,
            operation_ref=uuid7(),
        )

    async def _record_other_human_terminal(
        self,
        connection: Any,
        *,
        context: ExpressionCommitContext,
        application_status: str,
    ) -> None:
        if (
            context.scene_id is None
            or context.other_party_id is None
            or context.creator_party_id is not None
            or application_status not in {"no_action", "deferred"}
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-TERMINAL")
        await self._decisions.record_dialogue_decision(
            connection,
            context=context,
            decision_kind="silence" if application_status == "no_action" else "defer",
            operation_ref=uuid7(),
        )

    async def _insert_other_human_action(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        commit_id: UUID,
        replies: tuple[OtherHumanReplyDraft, ...],
        endings: tuple[OtherHumanEndConversationDraft, ...],
        response_artifact: ArtifactRef | None,
    ) -> None:
        if (
            context.scene_id is None
            or context.other_party_id is None
            or context.creator_party_id is not None
            or len(replies) + len(endings) != 1
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCOPE")
        connection = unit_of_work.transaction
        route = await self._interaction_routes.effect_route(
            connection,
            scene_id=context.scene_id,
            context_party_id=context.other_party_id,
        )
        group_route = route.destination_kind == "external_group"
        private_route = route.destination_kind == "external_private"
        relationship_scope = "other_human_social"
        destination_party_id = route.destination_party_id
        destination_binding_id = route.destination_binding_id
        action = replies[0] if replies else endings[0]
        if (
            action.subject_id != context.subject_id
            or action.scene_id != context.scene_id
            or action.other_party_id != context.other_party_id
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCOPE")
        if endings:
            if group_route:
                raise ResponseViolation("SUBJECT-OTHER-HUMAN-GROUP-END")
            if response_artifact is not None:
                raise ResponseViolation("SUBJECT-RESPONSE-ARTIFACT")
            await self._interaction_scenes.close_other_human_scene(
                connection,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                other_party_id=context.other_party_id,
            )
            await self._decisions.record_dialogue_decision(
                connection,
                context=context,
                decision_kind="end_conversation",
                operation_ref=uuid7(),
            )
            return

        reply = replies[0]
        if response_artifact is None:
            raise ResponseViolation("SUBJECT-RESPONSE-ARTIFACT")
        relationship = await self._relationships.current_for_party(
            unit_of_work.transaction,
            subject_id=context.subject_id,
            other_party_id=context.other_party_id,
            scope=relationship_scope,
        )
        if (
            relationship is not None
            and not self._relationship_policy.allows_snapshot_contact(relationship)
        ):
            raise ResponseViolation("SUBJECT-RELATIONSHIP-BOUNDARY")
        action_id = uuid7()
        operation_ref = uuid7()
        effect_kind = (
            "external_group_delivery"
            if group_route
            else "external_private_delivery"
            if private_route
            else "local_inbox_delivery"
        )
        destination_kind = (
            "external_group"
            if group_route
            else "external_private"
            if private_route
            else "other_human_inbox"
        )
        effect_id = await self._effect_registration.register_declared_response(
            connection,
            DeclaredResponseEffectDraft(
                action_intent_id=action_id,
                root_opportunity_id=context.root_opportunity_id,
                candidate_validation_id=context.validation_id,
                proposal_ref=reply.proposal_ref,
                subject_commit_id=commit_id,
                operation_ref=operation_ref,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.other_party_id,
                payload_artifact_id=response_artifact.artifact_id.value,
                payload_digest=response_artifact.content_digest,
                payload_bytes=len(reply.content_bytes),
                effect_kind=effect_kind,
                destination_kind=destination_kind,
                destination_party_id=destination_party_id,
                destination_binding_id=destination_binding_id,
                trace_id=context.trace_id,
                max_attempts=1 if group_route or private_route else 2,
            ),
        )
        await self._decisions.record_dialogue_decision(
            connection,
            context=context,
            decision_kind=reply.decision_kind,
            operation_ref=operation_ref,
            proposal_ref=reply.proposal_ref,
            effect_id=effect_id,
        )

    async def _finish_creator_response(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        commit_id: UUID,
        reply: CreatorReplyDraft,
        response_artifact: ArtifactRef,
        action_id: UUID,
    ) -> None:
        connection = unit_of_work.transaction
        turn_id = await self._voice.turn_for_opportunity(
            connection, opportunity_id=context.root_opportunity_id
        )
        route = await self._interaction_routes.effect_route(
            connection,
            scene_id=reply.scene_id,
            context_party_id=reply.creator_party_id,
            intended_destination_kind="creator_inbox" if turn_id is not None else None,
        )
        if route.destination_kind not in {"creator_inbox", "external_private"}:
            raise ResponseViolation("SUBJECT-RESPONSE-SCOPE")
        effect_id = await self._effect_registration.register_declared_response(
            connection,
            DeclaredResponseEffectDraft(
                action_intent_id=action_id,
                root_opportunity_id=context.root_opportunity_id,
                candidate_validation_id=context.validation_id,
                proposal_ref=reply.proposal_ref,
                subject_commit_id=commit_id,
                operation_ref=context.root_opportunity_id,
                subject_id=context.subject_id,
                scene_id=reply.scene_id,
                context_party_id=reply.creator_party_id,
                payload_artifact_id=response_artifact.artifact_id.value,
                payload_digest=response_artifact.content_digest,
                payload_bytes=len(reply.content_bytes),
                effect_kind="creator_response",
                destination_kind="live_voice_audio"
                if turn_id is not None
                else route.destination_kind,
                destination_party_id=route.destination_party_id,
                destination_binding_id=route.destination_binding_id,
                trace_id=context.trace_id,
                max_attempts=1
                if turn_id is not None or route.destination_binding_id is not None
                else 2,
                live_voice_turn_id=turn_id,
            ),
        )
        await self._decisions.record_dialogue_decision(
            connection,
            context=context,
            decision_kind=reply.decision_kind,
            operation_ref=context.root_opportunity_id,
            proposal_ref=reply.proposal_ref,
            effect_id=effect_id,
        )
        await unit_of_work.audit.append(
            _audit(
                unit_of_work,
                context,
                "cognition.response.intent.recorded",
                "action_intent",
                action_id,
                AuditResultStatus.ACCEPTED,
            )
        )


def _audit(
    unit_of_work: PostgreSQLRuntimeUnitOfWork,
    context: ExpressionCommitContext,
    operation: str,
    target_kind: str,
    target_ref: UUID,
    result: AuditResultStatus,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.subject"),
        operation,
        AuditReference(target_kind, target_ref),
        result,
        context.trace_id,
        AuditSensitivity.PRIVATE,
        subject_id=SubjectId(context.subject_id),
        request=AuditReference("cognitive_episode", context.episode_id),
    )


__all__ = ("PostgreSQLExpressionOwner",)
