"""Owner-only scene routing used by Expression and Effect."""

from __future__ import annotations

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction

from ._other_human_contract import OtherHumanInputViolation
from .api import InteractionEffectRoute


class PostgreSQLInteractionActionOwner:
    __slots__ = ()

    async def effect_route(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        context_party_id: UUID,
        intended_destination_kind: str | None = None,
    ) -> InteractionEffectRoute:
        row = await (
            await transaction.execute(
                """
                SELECT scene.scene_id, scene.scene_key, scene.scene_kind,
                       scene.primary_party_id, party.party_kind,
                       group_binding.external_binding_id,
                       group_binding.channel_kind, group_binding.account_key,
                       group_binding.external_key,
                       person_binding.external_binding_id,
                       person_binding.channel_kind, person_binding.account_key,
                       person_binding.external_key
                FROM armi.interaction_scenes AS scene
                JOIN armi.parties AS party ON party.party_id=%s
                LEFT JOIN armi.external_channel_bindings AS group_binding
                  ON group_binding.scene_id=scene.scene_id
                 AND group_binding.party_id=scene.primary_party_id
                 AND group_binding.external_kind='group'
                 AND group_binding.status='active'
                LEFT JOIN armi.external_channel_bindings AS person_binding
                  ON person_binding.scene_id=scene.scene_id
                 AND person_binding.party_id=%s
                 AND person_binding.external_kind='person'
                 AND person_binding.status='active'
                WHERE scene.scene_id=%s AND scene.current_status='open'
                """,
                (context_party_id, context_party_id, scene_id),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("OTHER-HUMAN-SCENE")
        scene_kind = str(row[2])
        if intended_destination_kind == "creator_inbox":
            destination_kind = "creator_inbox"
            destination_party = context_party_id
            binding_index = None
        elif scene_kind == "group_dialogue":
            destination_kind = "external_group"
            destination_party = row[3]
            binding_index = 5
        elif row[9] is not None:
            destination_kind = "external_private"
            destination_party = context_party_id
            binding_index = 9
        elif str(row[4]) == "creator":
            destination_kind = "creator_inbox"
            destination_party = context_party_id
            binding_index = None
        else:
            destination_kind = "other_human_inbox"
            destination_party = context_party_id
            binding_index = None
        if (
            intended_destination_kind is not None
            and destination_kind != intended_destination_kind
        ):
            raise OtherHumanInputViolation("OTHER-HUMAN-SCENE")
        binding_id = None if binding_index is None else row[binding_index]
        channel = None if binding_index is None else str(row[binding_index + 1])
        account = None if binding_index is None else str(row[binding_index + 2])
        conversation = None if binding_index is None else str(row[binding_index + 3])
        if (
            destination_kind in {"external_group", "external_private"}
            and binding_id is None
        ):
            raise OtherHumanInputViolation("OTHER-HUMAN-SCENE")
        return InteractionEffectRoute(
            scene_id=row[0],
            scene_key=str(row[1]),
            scene_kind=scene_kind,
            destination_party_id=destination_party,
            destination_kind=destination_kind,
            destination_binding_id=binding_id,
            external_channel=channel,
            external_account_key=account,
            external_conversation_key=conversation,
        )

    async def close_other_human_scene(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        scene_id: UUID,
        other_party_id: UUID,
    ) -> None:
        row = await (
            await transaction.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status='closed', closed_at=statement_timestamp(),
                    scene_version=scene_version+1
                WHERE scene_id=%s AND subject_id=%s
                  AND primary_party_id=%s
                  AND scene_kind='other_human_dialogue'
                  AND current_status='open'
                RETURNING scene_id
                """,
                (scene_id, subject_id, other_party_id),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("OTHER-HUMAN-SCENE")


__all__ = ("PostgreSQLInteractionActionOwner",)
