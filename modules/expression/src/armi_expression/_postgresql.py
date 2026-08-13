"""PostgreSQL owner for committed intention and expression facts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
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
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    CreatorReplyDraft,
    DeclaredResponseEffectDraft,
    ExpressionCommitContext,
    ExpressionEffectRegistrationPort,
    FormalNoActionDraft,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
    ResponseChoiceDraft,
    ResponseViolation,
)

_RESPONSE_WORK_KIND = "cognition.response.admit"


class PostgreSQLExpressionOwner:
    """Commit expression choices without owning subject transaction lifetime."""

    __slots__ = ("_effect_registration", "_relationship_policy", "_relationships")

    def __init__(
        self,
        relationships: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        effect_registration: ExpressionEffectRegistrationPort,
    ) -> None:
        self._relationships = relationships
        self._relationship_policy = relationship_policy
        self._effect_registration = effect_registration

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
                await self._insert_other_human_change_terminal(
                    unit_of_work,
                    context=context,
                    commit_id=commit_id,
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
        action_id = uuid7()
        revision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.action_intents (
                action_intent_id, subject_id, scene_id,
                context_party_id, root_opportunity_id, purpose,
                current_revision_id, action_kind, operation_ref) VALUES (
                %s, %s, %s, %s, %s, 'respond_to_creator', NULL,
                'party_response', %s)
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
        await self._finish_creator_response(
            unit_of_work,
            context=context,
            commit_id=commit_id,
            reply=reply,
            response_artifact=response_artifact,
            action_id=action_id,
            revision_id=revision_id,
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
            await self._insert_other_human_terminal(
                unit_of_work.transaction,
                context=context,
                application_id=application_id,
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
        rows = await (
            await connection.execute(
                """
                SELECT basis.context_item_id
                FROM armi.cognitive_candidate_basis_links AS basis
                JOIN armi.cognitive_candidate_validation_items AS item
                  ON item.candidate_validation_id = basis.candidate_validation_id
                 AND item.proposal_ref = basis.proposal_ref
                 AND item.validation_status = 'accepted'
                 AND item.owner_kind = 'action'
                WHERE basis.candidate_validation_id = %s
                  AND basis.proposal_ref = %s
                ORDER BY basis.ordinal
                """,
                (context.validation_id, decision.proposal_ref),
            )
        ).fetchall()
        if len(rows) != len(decision.basis_ordinals):
            raise ResponseViolation("SUBJECT-NO-ACTION-BASIS")
        no_action_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id, candidate_application_id,
                candidate_validation_id, proposal_ref, decision_kind,
                reason_class, subject_id, scene_id, context_party_id,
                operation_ref) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                no_action_id,
                context.root_opportunity_id,
                application_id,
                context.validation_id,
                decision.proposal_ref,
                "silence"
                if decision.kind.value == "no_action"
                else decision.kind.value,
                decision.reason.value,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                context.root_opportunity_id,
            ),
        )

    async def _insert_other_human_change_terminal(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        commit_id: UUID,
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
        await unit_of_work.transaction.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                subject_commit_id, subject_id, scene_id, context_party_id,
                decision_kind, operation_ref) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(),
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                commit_id,
                context.subject_id,
                context.scene_id,
                context.other_party_id,
                decision_kind,
                uuid7(),
            ),
        )

    async def _insert_other_human_terminal(
        self,
        connection: Any,
        *,
        context: ExpressionCommitContext,
        application_id: UUID,
        application_status: str,
    ) -> None:
        if (
            context.scene_id is None
            or context.other_party_id is None
            or context.creator_party_id is not None
            or application_status not in {"no_action", "deferred"}
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-TERMINAL")
        await connection.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                candidate_application_id, subject_id, scene_id, context_party_id,
                decision_kind, operation_ref) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(),
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                application_id,
                context.subject_id,
                context.scene_id,
                context.other_party_id,
                "silence" if application_status == "no_action" else "defer",
                uuid7(),
            ),
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
        route = await (
            await connection.execute(
                """
                SELECT scene.scene_kind, scene.primary_party_id,
                       group_binding.external_binding_id,
                       person_binding.external_binding_id,
                       context_party.party_kind
                FROM armi.interaction_scenes AS scene
                JOIN armi.parties AS context_party ON context_party.party_id = %s
                LEFT JOIN armi.external_channel_bindings AS group_binding
                  ON group_binding.scene_id = scene.scene_id
                 AND group_binding.party_id = scene.primary_party_id
                 AND group_binding.external_kind = 'group'
                 AND group_binding.status = 'active'
                LEFT JOIN armi.external_channel_bindings AS person_binding
                  ON person_binding.scene_id = scene.scene_id
                 AND person_binding.party_id = %s
                 AND person_binding.external_kind = 'person'
                 AND person_binding.status = 'active'
                WHERE scene.scene_id = %s AND scene.subject_id = %s
                  AND scene.current_status = 'open'
                  AND scene.scene_kind IN ('other_human_dialogue', 'group_dialogue')
                """,
                (
                    context.other_party_id,
                    context.other_party_id,
                    context.scene_id,
                    context.subject_id,
                ),
            )
        ).fetchone()
        if route is None:
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCENE")
        group_route = str(route[0]) == "group_dialogue"
        private_route = str(route[0]) == "other_human_dialogue" and route[3] is not None
        relationship_scope = (
            "creator_social" if route[4] == "creator" else "other_human_social"
        )
        if group_route:
            if route[2] is None:
                raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCENE")
        elif route[1] != context.other_party_id or route[2] is not None:
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCENE")
        destination_party_id = route[1] if group_route else context.other_party_id
        destination_binding_id = route[2] if group_route else route[3]
        action = replies[0] if replies else endings[0]
        if (
            action.subject_id != context.subject_id
            or action.scene_id != context.scene_id
            or action.other_party_id != context.other_party_id
        ):
            raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCOPE")
        decision_id = uuid7()
        if endings:
            if group_route:
                raise ResponseViolation("SUBJECT-OTHER-HUMAN-GROUP-END")
            if response_artifact is not None:
                raise ResponseViolation("SUBJECT-RESPONSE-ARTIFACT")
            updated = await (
                await connection.execute(
                    """
                    UPDATE armi.interaction_scenes
                    SET current_status = 'closed',
                        closed_at = statement_timestamp(),
                        scene_version = scene_version + 1
                    WHERE scene_id = %s AND subject_id = %s
                      AND primary_party_id = %s
                      AND scene_kind = 'other_human_dialogue'
                      AND current_status = 'open'
                    RETURNING scene_id
                    """,
                    (context.scene_id, context.subject_id, context.other_party_id),
                )
            ).fetchone()
            if updated is None:
                raise ResponseViolation("SUBJECT-OTHER-HUMAN-SCENE")
            await connection.execute(
                """
                INSERT INTO armi.dialogue_decisions (
                    dialogue_decision_id, opportunity_id,
                    cognitive_episode_id, candidate_validation_id,
                    subject_commit_id, subject_id, scene_id, context_party_id,
                    decision_kind, operation_ref) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    'end_conversation', %s)
                """,
                (
                    decision_id,
                    context.opportunity_id,
                    context.episode_id,
                    context.validation_id,
                    commit_id,
                    context.subject_id,
                    context.scene_id,
                    context.other_party_id,
                    uuid7(),
                ),
            )
            return

        reply = replies[0]
        if response_artifact is None:
            raise ResponseViolation("SUBJECT-RESPONSE-ARTIFACT")
        relationship = await self._relationships.current_for_party(
            unit_of_work.transaction,
            subject_id=context.subject_id,
            generation_id=context.generation_id,
            other_party_id=context.other_party_id,
            scope=relationship_scope,
        )
        if (
            relationship is not None
            and not self._relationship_policy.allows_snapshot_contact(relationship)
        ):
            raise ResponseViolation("SUBJECT-RELATIONSHIP-BOUNDARY")
        action_id = uuid7()
        revision_id = uuid7()
        operation_ref = uuid7()
        capability_kind = (
            "external.group.message.send"
            if group_route
            else "external.private.message.send"
            if private_route
            else "local.other-human-inbox.deliver"
        )
        audience_scope = "social_group" if group_route else "other_human"
        effect_kind = (
            "external_group_delivery"
            if group_route
            else "external_private_delivery"
            if private_route
            else "local_inbox_delivery"
        )
        authorization_basis = (
            "runtime_configuration"
            if group_route or private_route
            else "runtime_builtin"
        )
        destination_kind = (
            "external_group"
            if group_route
            else "external_private"
            if private_route
            else "other_human_inbox"
        )
        await connection.execute(
            """
            INSERT INTO armi.action_intents (
                action_intent_id, subject_id, scene_id, context_party_id,
                root_opportunity_id, purpose, current_revision_id, action_kind,
                operation_ref)
            VALUES (%s, %s, %s, %s, %s, 'respond_to_other_human', NULL,
                    'party_response', %s)
            """,
            (
                action_id,
                context.subject_id,
                context.scene_id,
                context.other_party_id,
                context.root_opportunity_id,
                operation_ref,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.action_intent_revisions (
                action_intent_revision_id, action_intent_id,
                revision_no, response_artifact_id, response_digest, response_bytes,
                media_type, capability_kind, operation_class, audience_scope,
                data_scope, purpose, candidate_validation_id, proposal_ref,
                subject_commit_id) VALUES (
                %s, %s, 1, %s, %s, %s, 'text/plain', %s, 'send', %s,
                'declared_party_response', 'respond_to_other_human', %s, %s, %s)
            """,
            (
                revision_id,
                action_id,
                response_artifact.artifact_id.value,
                response_artifact.content_digest.value,
                len(reply.content_bytes),
                capability_kind,
                audience_scope,
                context.validation_id,
                reply.proposal_ref,
                commit_id,
            ),
        )
        await connection.execute(
            "UPDATE armi.action_intents SET current_revision_id = %s "
            "WHERE action_intent_id = %s",
            (revision_id, action_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                subject_commit_id, subject_id, scene_id, context_party_id,
                proposal_ref, decision_kind, action_intent_id, effect_id,
                operation_ref) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, 'reply', %s, NULL, %s)
            """,
            (
                decision_id,
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                commit_id,
                context.subject_id,
                context.scene_id,
                context.other_party_id,
                reply.proposal_ref,
                action_id,
                operation_ref,
            ),
        )
        effect_id = await self._effect_registration.register_declared_response(
            connection,
            DeclaredResponseEffectDraft(
                action_intent_revision_id=revision_id,
                action_intent_id=action_id,
                operation_ref=operation_ref,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.other_party_id,
                payload_artifact_id=response_artifact.artifact_id.value,
                payload_digest=response_artifact.content_digest,
                payload_bytes=len(reply.content_bytes),
                effect_kind=effect_kind,
                capability_kind=capability_kind,
                audience_scope=audience_scope,
                authorization_basis=authorization_basis,
                destination_kind=destination_kind,
                destination_party_id=destination_party_id,
                destination_binding_id=destination_binding_id,
                trace_id=context.trace_id,
                max_attempts=1 if group_route or private_route else 2,
            ),
        )
        await connection.execute(
            "UPDATE armi.dialogue_decisions SET effect_id = %s "
            "WHERE dialogue_decision_id = %s AND effect_id IS NULL",
            (effect_id, decision_id),
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
        revision_id: UUID,
    ) -> None:
        connection = unit_of_work.transaction
        decision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.action_intent_revisions (
                action_intent_revision_id, action_intent_id, revision_no,
                response_artifact_id, response_digest, response_bytes,
                media_type, capability_kind, operation_class, audience_scope,
                data_scope, purpose, candidate_validation_id, proposal_ref,
                subject_commit_id) VALUES (
                %s, %s, 1, %s, %s, %s, 'text/plain',
                'creator.scene.reply', 'send', 'creator',
                'creator_visible_response', 'respond_to_creator', %s, %s, %s)
            """,
            (
                revision_id,
                action_id,
                response_artifact.artifact_id.value,
                response_artifact.content_digest.value,
                len(reply.content_bytes),
                context.validation_id,
                reply.proposal_ref,
                commit_id,
            ),
        )
        await connection.execute(
            "UPDATE armi.action_intents SET current_revision_id = %s "
            "WHERE action_intent_id = %s",
            (revision_id, action_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id, cognitive_episode_id,
                candidate_validation_id, subject_commit_id, subject_id, scene_id,
                context_party_id, proposal_ref, decision_kind, action_intent_id,
                operation_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'reply', %s, %s)
            """,
            (
                decision_id,
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                commit_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                reply.proposal_ref,
                action_id,
                context.root_opportunity_id,
            ),
        )
        now_row = await (
            await connection.execute("SELECT statement_timestamp()")
        ).fetchone()
        if now_row is None:
            raise ResponseViolation("SUBJECT-DATABASE")
        work_id = WorkId(uuid7())
        await unit_of_work.work.enqueue(
            WorkDraft(
                work_id,
                _RESPONSE_WORK_KIND,
                WorkOwner("action_intent", action_id),
                IdempotencyKey(f"response-admit:{action_id}"),
                response_artifact.content_digest,
                50,
                Instant(now_row[0]),
                Instant(now_row[0] + timedelta(seconds=3600)),
                2,
                context.trace_id,
                SubjectId(context.subject_id),
                WorkPayloadRef("action_intent", action_id),
            )
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
