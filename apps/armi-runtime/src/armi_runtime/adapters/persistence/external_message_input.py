"""PostgreSQL mappings for channel-neutral external conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid7

from armi_kernel.application import (
    ConfigureExternalCreatorCommand,
    ExternalConversationKind,
    ExternalCreatorBinding,
    ExternalMessageInputAcceptance,
    ExternalMessageInteractionId,
    ExternalMessageViolation,
    ObservedExternalMessage,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId

from .creator_input import CreatorInputContext
from .other_human_input import OtherHumanInputContext
from .unit_of_work import PostgreSQLUnitOfWork

_PersonBinding = tuple[UUID, UUID, Literal["creator", "other_human"], UUID | None]


@dataclass(frozen=True, slots=True)
class ExternalMessageInputContext:
    conversation_binding_id: UUID
    sender_party_kind: Literal["creator", "other_human"]
    creator_input: CreatorInputContext | None
    other_input: OtherHumanInputContext | None

    @property
    def subject_id(self) -> UUID:
        value = self.creator_input or self.other_input
        assert value is not None
        return value.subject_id

    @property
    def scene_id(self) -> UUID:
        value = self.creator_input or self.other_input
        assert value is not None
        return value.scene_id

    @property
    def sender_party_id(self) -> UUID:
        if self.creator_input is not None:
            return self.creator_input.creator_party_id
        assert self.other_input is not None
        return self.other_input.party_id


class ExternalMessageInputRepository:
    __slots__ = ()

    async def configure_creator(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        command: ConfigureExternalCreatorCommand,
        scene_key: str,
    ) -> ExternalCreatorBinding:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        creator = await (
            await connection.execute(
                """
                SELECT party.party_id, subject.subject_id
                FROM armi.parties AS party
                JOIN armi.subjects AS subject
                  ON subject.singleton_key = 1 AND subject.status = 'active'
                WHERE party.party_kind = 'creator'
                  AND party.creator_role = 'unique_primary_creator'
                  AND party.status = 'active'
                """
            )
        ).fetchone()
        if creator is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-CREATOR")
        await connection.execute(
            """
            INSERT INTO armi.interaction_scenes (
                scene_id, subject_id, scene_key, scene_kind,
                primary_party_id, primary_party_kind, audience_scope,
                current_status
            ) VALUES (uuidv7(), %s, %s, 'creator_dialogue',
                      %s, 'creator', 'creator', 'open')
            ON CONFLICT (subject_id, primary_party_id, scene_key)
            DO UPDATE SET current_status = 'open', closed_at = NULL
            """,
            (creator[1], scene_key, creator[0]),
        )
        scene = await (
            await connection.execute(
                """
                SELECT scene_id FROM armi.interaction_scenes
                WHERE subject_id = %s AND primary_party_id = %s
                  AND scene_key = %s AND scene_kind = 'creator_dialogue'
                  AND audience_scope = 'creator' AND current_status = 'open'
                """,
                (creator[1], creator[0], scene_key),
            )
        ).fetchone()
        if scene is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-CREATOR-SCENE")
        await connection.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s, %s, %s, 'primary')
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (scene[0], creator[1], creator[0]),
        )
        await connection.execute(
            """
            INSERT INTO armi.external_channel_bindings (
                external_binding_id, channel_kind, account_key,
                external_kind, external_key, party_id, party_kind,
                scene_id, display_label, identity_assurance
            ) VALUES (uuidv7(), %s, %s, 'person', %s, %s, 'creator',
                      %s, %s, 'runtime_configuration')
            ON CONFLICT (channel_kind, account_key, external_kind, external_key)
            DO NOTHING
            """,
            (
                command.channel.value,
                command.account_key.value,
                command.creator_key.value,
                creator[0],
                scene[0],
                command.display_label,
            ),
        )
        binding = await (
            await connection.execute(
                """
                SELECT external_binding_id, party_id, party_kind, scene_id,
                       identity_assurance
                FROM armi.external_channel_bindings
                WHERE channel_kind = %s AND account_key = %s
                  AND external_kind = 'person' AND external_key = %s
                  AND status = 'active'
                """,
                (
                    command.channel.value,
                    command.account_key.value,
                    command.creator_key.value,
                ),
            )
        ).fetchone()
        if binding is None or binding[1:] != (
            creator[0],
            "creator",
            scene[0],
            "runtime_configuration",
        ):
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-BINDING-CONFLICT")
        return ExternalCreatorBinding(binding[0], creator[0], scene[0])

    async def bind_message(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        command: ObservedExternalMessage,
        person_identity_key: str,
        conversation_identity_key: str,
        scene_key: str,
    ) -> ExternalMessageInputContext:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        person = await (
            await connection.execute(
                """
                SELECT external_binding_id, party_id, party_kind, scene_id
                FROM armi.external_channel_bindings
                WHERE channel_kind = %s AND account_key = %s
                  AND external_kind = 'person' AND external_key = %s
                  AND status = 'active'
                """,
                (
                    command.channel.value,
                    command.account_key.value,
                    command.sender_key.value,
                ),
            )
        ).fetchone()
        if person is None:
            party = await (
                await connection.execute(
                    """
                    INSERT INTO armi.parties (
                        party_id, party_kind, display_label, declared_identity_key
                    ) VALUES (uuidv7(), 'other_human', %s, %s)
                    ON CONFLICT (declared_identity_key)
                        WHERE party_kind = 'other_human'
                    DO UPDATE SET display_label = EXCLUDED.display_label
                    RETURNING party_id
                    """,
                    (command.sender_display_label, person_identity_key),
                )
            ).fetchone()
            if party is None:
                raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-PARTY")
            person = await (
                await connection.execute(
                    """
                    INSERT INTO armi.external_channel_bindings (
                        external_binding_id, channel_kind, account_key,
                        external_kind, external_key, party_id, party_kind,
                        scene_id, display_label, identity_assurance
                    ) VALUES (uuidv7(), %s, %s, 'person', %s, %s,
                              'other_human', NULL, %s, 'platform_observed')
                    RETURNING external_binding_id, party_id, party_kind, scene_id
                    """,
                    (
                        command.channel.value,
                        command.account_key.value,
                        command.sender_key.value,
                        party[0],
                        command.sender_display_label,
                    ),
                )
            ).fetchone()
        if person is None or str(person[2]) not in {"creator", "other_human"}:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-BINDING-CONFLICT")
        person_binding = cast(_PersonBinding, person)
        if command.conversation_kind is ExternalConversationKind.DIRECT:
            return await self._bind_direct(
                connection,
                command=command,
                person=person_binding,
                scene_key=scene_key,
            )
        return await self._bind_group(
            connection,
            command=command,
            person=person_binding,
            conversation_identity_key=conversation_identity_key,
            scene_key=scene_key,
        )

    async def existing_external(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: ExternalMessageInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> ExternalMessageInputAcceptance | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT interaction.interaction_id,
                       evidence.evidence_id,
                       opportunity.opportunity_id,
                       interaction.request_digest,
                       COALESCE(interaction.cognition_content_digest,
                                interaction.content_digest)
                FROM armi.party_input_interactions AS interaction
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id = interaction.interaction_id
                LEFT JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id = evidence.evidence_id
                 AND opportunity.root_opportunity_id = opportunity.opportunity_id
                WHERE interaction.source_party_id = %s
                  AND interaction.scene_id = %s
                  AND interaction.idempotency_key = %s
                """,
                (context.sender_party_id, context.scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[3]) != request_digest.value:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-IDEMPOTENCY-MISMATCH")
        from armi_kernel.application import EvidenceId, OpportunityId

        return ExternalMessageInputAcceptance(
            context.conversation_binding_id,
            context.sender_party_id,
            context.sender_party_kind,
            context.scene_id,
            ExternalMessageInteractionId(row[0]),
            None if row[1] is None else EvidenceId(row[1]),
            None if row[2] is None else OpportunityId(row[2]),
            request_digest,
            Digest(str(row[4])),
            False,
        )

    async def add_parts(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        interaction_id: UUID,
        command: ObservedExternalMessage,
        media_status: str,
    ) -> tuple[UUID, ...]:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        part_ids: list[UUID] = []
        for ordinal, part in enumerate(command.parts, start=1):
            part_id = uuid7()
            status = media_status if part.requires_recognition else "not_required"
            settled_at = datetime.now(UTC) if status == "skipped" else None
            await connection.execute(
                """
                INSERT INTO armi.external_message_parts (
                    external_message_part_id, interaction_id, ordinal, part_kind,
                    text_value, target_key, external_locator, declared_file_name,
                    declared_media_type, declared_byte_size, processing_status,
                    settled_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    part_id,
                    interaction_id,
                    ordinal,
                    part.kind.value,
                    part.text,
                    part.target_key,
                    part.locator,
                    part.file_name,
                    part.media_type,
                    part.byte_size,
                    status,
                    settled_at,
                ),
            )
            part_ids.append(part_id)
        return tuple(part_ids)

    async def create_deferred(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: ExternalMessageInputContext,
        command: ObservedExternalMessage,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
        content_digest: Digest,
        recognition_status: str,
    ) -> ExternalMessageInputAcceptance:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        interaction_id = uuid7()
        purpose = (
            "creator_message"
            if context.creator_input is not None
            else "other_human_message"
        )
        await connection.execute(
            """
            INSERT INTO armi.party_input_interactions (
                interaction_id, subject_id, scene_id, source_party_id, purpose,
                idempotency_key, request_digest, content_digest, trace_id,
                external_binding_id, external_message_key, addressed_to_subject,
                recognition_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.sender_party_id,
                purpose,
                idempotency_key.value,
                request_digest.value,
                content_digest.value,
                command.trace_id.value,
                context.conversation_binding_id,
                command.message_key.value,
                command.addressed_to_subject,
                recognition_status,
            ),
        )
        await self.add_parts(
            unit_of_work,
            interaction_id=interaction_id,
            command=command,
            media_status="pending" if recognition_status == "pending" else "skipped",
        )
        if recognition_status == "pending":
            now = Instant(datetime.now(UTC))
            await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    "external.content.recognize",
                    WorkOwner("external_message", interaction_id),
                    idempotency_key,
                    request_digest,
                    80,
                    now,
                    Instant(now.value + timedelta(hours=1)),
                    1,
                    command.trace_id,
                    subject_id=SubjectId(context.subject_id),
                    payload=WorkPayloadRef("external_message", interaction_id),
                )
            )
        return ExternalMessageInputAcceptance(
            context.conversation_binding_id,
            context.sender_party_id,
            context.sender_party_kind,
            context.scene_id,
            ExternalMessageInteractionId(interaction_id),
            None,
            None,
            request_digest,
            content_digest,
            True,
        )

    async def _bind_direct(
        self,
        connection: Any,
        *,
        command: ObservedExternalMessage,
        person: _PersonBinding,
        scene_key: str,
    ) -> ExternalMessageInputContext:
        execute = connection.execute
        subject = await (
            await execute(
                "SELECT subject_id FROM armi.subjects WHERE singleton_key = 1 AND status = 'active'"
            )
        ).fetchone()
        if subject is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-SUBJECT")
        scene_kind = (
            "creator_dialogue" if person[2] == "creator" else "other_human_dialogue"
        )
        audience = "creator" if person[2] == "creator" else "other_human"
        if person[3] is None:
            await execute(
                """
                INSERT INTO armi.interaction_scenes (
                    scene_id, subject_id, scene_key, scene_kind,
                    primary_party_id, primary_party_kind, audience_scope,
                    current_status
                ) VALUES (uuidv7(), %s, %s, %s, %s, %s, %s, 'open')
                ON CONFLICT (subject_id, primary_party_id, scene_key) DO NOTHING
                """,
                (subject[0], scene_key, scene_kind, person[1], person[2], audience),
            )
            scene = await (
                await execute(
                    """
                    SELECT scene_id FROM armi.interaction_scenes
                    WHERE subject_id = %s AND primary_party_id = %s
                      AND scene_key = %s AND scene_kind = %s
                      AND audience_scope = %s AND current_status = 'open'
                    """,
                    (subject[0], person[1], scene_key, scene_kind, audience),
                )
            ).fetchone()
            if scene is None:
                raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-SCENE")
            updated = await execute(
                """
                UPDATE armi.external_channel_bindings SET scene_id = %s,
                    display_label = %s, last_observed_at = statement_timestamp()
                WHERE external_binding_id = %s AND scene_id IS NULL
                """,
                (scene[0], command.sender_display_label, person[0]),
            )
            if updated.rowcount != 1:
                raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-BINDING-CONFLICT")
            scene_id = scene[0]
        else:
            scene_id = person[3]
        await execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s, %s, %s, 'primary')
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (scene_id, subject[0], person[1]),
        )
        if person[2] == "creator":
            return ExternalMessageInputContext(
                person[0],
                "creator",
                CreatorInputContext(subject[0], scene_id, person[1]),
                None,
            )
        return ExternalMessageInputContext(
            person[0],
            "other_human",
            None,
            OtherHumanInputContext(subject[0], person[1], scene_id),
        )

    async def _bind_group(
        self,
        connection: Any,
        *,
        command: ObservedExternalMessage,
        person: _PersonBinding,
        conversation_identity_key: str,
        scene_key: str,
    ) -> ExternalMessageInputContext:
        execute = connection.execute
        group_party = await (
            await execute(
                """
                INSERT INTO armi.parties (
                    party_id, party_kind, display_label, declared_identity_key
                ) VALUES (uuidv7(), 'social_group', %s, %s)
                ON CONFLICT (declared_identity_key) WHERE party_kind = 'social_group'
                DO UPDATE SET display_label = EXCLUDED.display_label
                RETURNING party_id
                """,
                (command.conversation_display_label, conversation_identity_key),
            )
        ).fetchone()
        if group_party is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-GROUP")
        await execute(
            """
            INSERT INTO armi.interaction_scenes (
                scene_id, subject_id, scene_key, scene_kind,
                primary_party_id, primary_party_kind, audience_scope, current_status
            ) SELECT uuidv7(), subject_id, %s, 'group_dialogue', %s,
                     'social_group', 'social_group', 'open'
              FROM armi.subjects WHERE singleton_key = 1 AND status = 'active'
            ON CONFLICT (subject_id, primary_party_id, scene_key) DO NOTHING
            """,
            (scene_key, group_party[0]),
        )
        scene = await (
            await execute(
                """
                SELECT scene_id, subject_id FROM armi.interaction_scenes
                WHERE primary_party_id = %s AND scene_key = %s
                  AND scene_kind = 'group_dialogue'
                  AND audience_scope = 'social_group' AND current_status = 'open'
                """,
                (group_party[0], scene_key),
            )
        ).fetchone()
        if scene is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-SCENE")
        await execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s,%s,%s,'primary'),(%s,%s,%s,'member')
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (scene[0], scene[1], group_party[0], scene[0], scene[1], person[1]),
        )
        await execute(
            """
            INSERT INTO armi.external_channel_bindings (
                external_binding_id, channel_kind, account_key, external_kind,
                external_key, party_id, party_kind, scene_id, display_label,
                identity_assurance
            ) VALUES (uuidv7(), %s, %s, 'group', %s, %s, 'social_group',
                      %s, %s, 'platform_observed')
            ON CONFLICT (channel_kind, account_key, external_kind, external_key)
            DO UPDATE SET display_label = EXCLUDED.display_label,
                          last_observed_at = statement_timestamp()
            """,
            (
                command.channel.value,
                command.account_key.value,
                command.conversation_key.value,
                group_party[0],
                scene[0],
                command.conversation_display_label,
            ),
        )
        binding = await (
            await execute(
                """
                SELECT external_binding_id FROM armi.external_channel_bindings
                WHERE channel_kind = %s AND account_key = %s
                  AND external_kind = 'group' AND external_key = %s
                  AND party_id = %s AND scene_id = %s AND status = 'active'
                """,
                (
                    command.channel.value,
                    command.account_key.value,
                    command.conversation_key.value,
                    group_party[0],
                    scene[0],
                ),
            )
        ).fetchone()
        if binding is None:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-BINDING-CONFLICT")
        return ExternalMessageInputContext(
            binding[0],
            person[2],
            None,
            OtherHumanInputContext(scene[1], person[1], scene[0]),
        )


__all__ = ("ExternalMessageInputContext", "ExternalMessageInputRepository")
