"""PostgreSQL mappings for channel-neutral external group observations."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_kernel.application import (
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalGroupView,
    ExternalGroupViolation,
    ExternalPartyKey,
    SceneKey,
)

from .other_human_input import OtherHumanInputContext
from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class ExternalGroupInputContext:
    binding_id: UUID
    input: OtherHumanInputContext


class ExternalGroupInputRepository:
    __slots__ = ()

    async def ensure_group(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        conversation_key: ExternalConversationKey,
        display_label: str,
        identity_key: str,
        scene_key: SceneKey,
    ) -> ExternalGroupView:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        group_party = await (
            await connection.execute(
                """
                INSERT INTO armi.parties (
                    party_id, party_kind, display_label, declared_identity_key
                ) VALUES (uuidv7(), 'social_group', %s, %s)
                ON CONFLICT (declared_identity_key)
                    WHERE party_kind = 'social_group'
                DO UPDATE SET display_label = EXCLUDED.display_label
                RETURNING party_id
                """,
                (display_label, identity_key),
            )
        ).fetchone()
        if group_party is None:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-PARTY")
        scene = await (
            await connection.execute(
                """
                INSERT INTO armi.interaction_scenes (
                    scene_id, subject_id, scene_key, scene_kind,
                    primary_party_id, primary_party_kind, audience_scope,
                    current_status
                )
                SELECT uuidv7(), subject_id, %s, 'group_dialogue',
                       %s, 'social_group', 'social_group', 'open'
                FROM armi.subjects
                WHERE singleton_key = 1 AND status = 'active'
                ON CONFLICT (subject_id, primary_party_id, scene_key)
                DO NOTHING
                RETURNING scene_id, subject_id
                """,
                (scene_key.value, group_party[0]),
            )
        ).fetchone()
        if scene is None:
            scene = await (
                await connection.execute(
                    """
                    SELECT scene_id, subject_id
                    FROM armi.interaction_scenes
                    WHERE primary_party_id = %s AND scene_key = %s
                      AND scene_kind = 'group_dialogue'
                      AND audience_scope = 'social_group'
                    """,
                    (group_party[0], scene_key.value),
                )
            ).fetchone()
        if scene is None:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-SCENE")
        await connection.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s, %s, %s, 'primary')
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (scene[0], scene[1], group_party[0]),
        )
        binding = await (
            await connection.execute(
                """
                INSERT INTO armi.external_channel_bindings (
                    external_binding_id, channel_kind, account_key,
                    external_kind, external_key, party_id, party_kind,
                    scene_id, display_label, identity_assurance
                ) VALUES (
                    uuidv7(), %s, %s, 'group', %s, %s, 'social_group',
                    %s, %s, 'platform_observed'
                )
                ON CONFLICT (channel_kind, account_key, external_kind, external_key)
                DO UPDATE SET display_label = EXCLUDED.display_label,
                              last_observed_at = statement_timestamp()
                RETURNING external_binding_id, party_id, scene_id
                """,
                (
                    channel.value,
                    account_key.value,
                    conversation_key.value,
                    group_party[0],
                    scene[0],
                    display_label,
                ),
            )
        ).fetchone()
        if binding is None or binding[1] != group_party[0] or binding[2] != scene[0]:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-BINDING-CONFLICT")
        return ExternalGroupView(binding[0], group_party[0], scene[0], scene_key)

    async def bind_sender(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        conversation_key: ExternalConversationKey,
        sender_key: ExternalPartyKey,
        sender_display_label: str,
        identity_key: str,
    ) -> ExternalGroupInputContext:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        group = await (
            await connection.execute(
                """
                SELECT binding.external_binding_id, scene.subject_id,
                       scene.scene_id
                FROM armi.external_channel_bindings AS binding
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = binding.scene_id
                 AND scene.primary_party_id = binding.party_id
                WHERE binding.channel_kind = %s
                  AND binding.account_key = %s
                  AND binding.external_kind = 'group'
                  AND binding.external_key = %s
                  AND binding.status = 'active'
                  AND scene.scene_kind = 'group_dialogue'
                  AND scene.audience_scope = 'social_group'
                  AND scene.current_status = 'open'
                  AND scene.closed_at IS NULL
                """,
                (channel.value, account_key.value, conversation_key.value),
            )
        ).fetchone()
        if group is None:
            raise ExternalGroupViolation("SCOPE-EXTERNAL-GROUP-NOT-ALLOWED")
        sender = await (
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
                (sender_display_label, identity_key),
            )
        ).fetchone()
        if sender is None:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-SENDER")
        sender_binding = await (
            await connection.execute(
                """
                INSERT INTO armi.external_channel_bindings (
                    external_binding_id, channel_kind, account_key,
                    external_kind, external_key, party_id, party_kind,
                    scene_id, display_label, identity_assurance
                ) VALUES (
                    uuidv7(), %s, %s, 'person', %s, %s, 'other_human',
                    NULL, %s, 'platform_observed'
                )
                ON CONFLICT (channel_kind, account_key, external_kind, external_key)
                DO UPDATE SET display_label = EXCLUDED.display_label,
                              last_observed_at = statement_timestamp()
                RETURNING party_id
                """,
                (
                    channel.value,
                    account_key.value,
                    sender_key.value,
                    sender[0],
                    sender_display_label,
                ),
            )
        ).fetchone()
        if sender_binding is None or sender_binding[0] != sender[0]:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-BINDING-CONFLICT")
        await connection.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s, %s, %s, 'member')
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (group[2], group[1], sender[0]),
        )
        return ExternalGroupInputContext(
            group[0],
            OtherHumanInputContext(group[1], sender[0], group[2]),
        )


__all__ = (
    "ExternalGroupInputContext",
    "ExternalGroupInputRepository",
)
