"""PostgreSQL owner for caller-declared other-human parties, scenes and input."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_attention.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceReadPort,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from ._creator_contract import OpportunityId
from ._other_human_contract import (
    OtherHumanInputAcceptance,
    OtherHumanInputViolation,
    OtherHumanInteractionId,
    OtherHumanPartyKey,
    OtherHumanPartyView,
    OtherHumanSceneView,
)
from ._scene_contract import SceneKey, SceneStatus
from .api import (
    InteractionOtherHumanPartySnapshot,
    InteractionOtherHumanSceneSnapshot,
    InteractionOtherHumanTimelineSource,
)


@dataclass(frozen=True, slots=True)
class OtherHumanInputContext:
    subject_id: UUID
    party_id: UUID
    scene_id: UUID


class OtherHumanInputRepository:
    __slots__ = ("_evidence", "_evidence_read", "_opportunity")

    def __init__(
        self,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        opportunity: OpportunityAdmissionPort,
    ) -> None:
        self._evidence = evidence
        self._evidence_read = evidence_read
        self._opportunity = opportunity

    async def list_other_human_parties(
        self, transaction: PostgreSQLTransaction, *, before_id: UUID | None, limit: int
    ) -> tuple[InteractionOtherHumanPartySnapshot, ...]:
        rows = cast(
            list[tuple[object, ...]],
            await (
                await transaction.execute(
                    """
                SELECT party.party_id, party.declared_identity_key,
                       party.display_label, count(DISTINCT scene.scene_id),
                       count(item.timeline_item_id), max(item.occurred_at)
                FROM armi.parties AS party
                JOIN armi.interaction_scenes AS scene
                  ON scene.primary_party_id = party.party_id
                 AND scene.scene_kind = 'other_human_dialogue'
                JOIN armi.scene_timeline_items AS item
                  ON item.scene_id = scene.scene_id
                 AND item.source_kind IN ('other_human_input','other_human_response')
                WHERE party.party_kind = 'other_human'
                  AND (%s::uuid IS NULL OR party.party_id < %s::uuid)
                GROUP BY party.party_id, party.declared_identity_key,
                         party.display_label
                ORDER BY party.party_id DESC LIMIT %s
                """,
                    (before_id, before_id, limit),
                )
            ).fetchall(),
        )
        return tuple(self._party_snapshot(row) for row in rows)

    async def other_human_party(
        self, transaction: PostgreSQLTransaction, *, party_id: UUID
    ) -> InteractionOtherHumanPartySnapshot | None:
        rows = await self.list_other_human_parties(
            transaction, before_id=None, limit=10000
        )
        return next((item for item in rows if item.party_id == party_id), None)

    async def list_other_human_scenes(
        self,
        transaction: PostgreSQLTransaction,
        *,
        party_id: UUID,
        before_id: UUID | None,
        limit: int,
    ) -> tuple[InteractionOtherHumanSceneSnapshot, ...]:
        rows = cast(
            list[tuple[object, ...]],
            await (
                await transaction.execute(
                    """
                SELECT scene.scene_id, scene.scene_key, scene.current_status,
                       count(item.timeline_item_id), max(item.occurred_at)
                FROM armi.interaction_scenes AS scene
                JOIN armi.scene_timeline_items AS item
                  ON item.scene_id = scene.scene_id
                 AND item.source_kind IN ('other_human_input','other_human_response')
                WHERE scene.primary_party_id = %s
                  AND scene.scene_kind = 'other_human_dialogue'
                  AND (%s::uuid IS NULL OR scene.scene_id < %s::uuid)
                GROUP BY scene.scene_id, scene.scene_key, scene.current_status
                ORDER BY scene.scene_id DESC LIMIT %s
                """,
                    (party_id, before_id, before_id, limit),
                )
            ).fetchall(),
        )
        return tuple(
            InteractionOtherHumanSceneSnapshot(
                cast(UUID, row[0]),
                str(row[1]),
                str(row[2]),
                cast(int, row[3]),
                cast(datetime | None, row[4]),
            )
            for row in rows
        )

    async def other_human_scene_exists(
        self, transaction: PostgreSQLTransaction, *, party_id: UUID, scene_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """
                SELECT 1 FROM armi.interaction_scenes
                WHERE scene_id = %s AND primary_party_id = %s
                  AND scene_kind = 'other_human_dialogue'
                """,
                (scene_id, party_id),
            )
        ).fetchone()
        return row is not None

    async def other_human_timeline(
        self,
        transaction: PostgreSQLTransaction,
        *,
        party_id: UUID,
        scene_id: UUID,
        before_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> tuple[InteractionOtherHumanTimelineSource, ...]:
        rows = cast(
            list[tuple[object, ...]],
            await (
                await transaction.execute(
                    """
                SELECT item.timeline_item_id, item.source_kind, item.source_ref,
                       item.result_status, item.occurred_at
                FROM armi.scene_timeline_items AS item
                JOIN armi.interaction_scenes AS scene ON scene.scene_id = item.scene_id
                WHERE scene.primary_party_id = %s AND scene.scene_id = %s
                  AND scene.scene_kind = 'other_human_dialogue'
                  AND item.source_kind IN ('other_human_input','other_human_response')
                  AND (%s::timestamptz IS NULL OR
                       (item.occurred_at, item.timeline_item_id) <
                       (%s::timestamptz, %s::uuid))
                ORDER BY item.occurred_at DESC, item.timeline_item_id DESC LIMIT %s
                """,
                    (party_id, scene_id, before_at, before_at, before_id, limit),
                )
            ).fetchall(),
        )
        return tuple(
            InteractionOtherHumanTimelineSource(
                cast(UUID, row[0]),
                str(row[1]),
                cast(UUID, row[2]),
                str(row[3]),
                cast(datetime, row[4]),
            )
            for row in rows
        )

    @staticmethod
    def _party_snapshot(row: Sequence[object]) -> InteractionOtherHumanPartySnapshot:
        return InteractionOtherHumanPartySnapshot(
            cast(UUID, row[0]),
            str(row[1]),
            str(row[2]),
            cast(int, row[3]),
            cast(int, row[4]),
            cast(datetime | None, row[5]),
        )

    async def register_party(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        party_key: OtherHumanPartyKey,
        display_label: str,
    ) -> OtherHumanPartyView:
        connection = unit_of_work.transaction
        await connection.execute(
            """
            INSERT INTO armi.parties (
                party_id, party_kind, display_label, declared_identity_key
            ) VALUES (%s, 'other_human', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (uuid7(), display_label, party_key.value),
        )
        row = await (
            await connection.execute(
                """
                SELECT party_id, display_label
                FROM armi.parties
                WHERE party_kind = 'other_human'
                  AND creator_role IS NULL
                  AND declared_identity_key = %s
                  AND status = 'active'
                """,
                (party_key.value,),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-PARTY")
        if row[1] != display_label:
            raise OtherHumanInputViolation("IDEMPOTENCY-OTHER-HUMAN-PARTY-MISMATCH")
        return OtherHumanPartyView(row[0], party_key, row[1])

    async def set_scene(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        party_key: OtherHumanPartyKey,
        scene_key: SceneKey,
        target_status: SceneStatus,
    ) -> OtherHumanSceneView:
        connection = unit_of_work.transaction
        party = await (
            await connection.execute(
                """
                SELECT party_id FROM armi.parties
                WHERE party_kind = 'other_human' AND creator_role IS NULL
                  AND declared_identity_key = %s AND status = 'active'
                """,
                (party_key.value,),
            )
        ).fetchone()
        if party is None:
            raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-PARTY-NOT-VISIBLE")
        if target_status is SceneStatus.OPEN:
            await connection.execute(
                """
                INSERT INTO armi.interaction_scenes (
                    scene_id, subject_id, scene_key, scene_kind,
                    primary_party_id, primary_party_kind, audience_scope,
                    current_status
                )
                VALUES (uuidv7(), %s, %s, 'other_human_dialogue',
                       %s, 'other_human', 'other_human', 'open')
                ON CONFLICT (subject_id, primary_party_id, scene_key)
                DO UPDATE SET current_status = 'open', closed_at = NULL,
                              scene_version = interaction_scenes.scene_version + 1
                WHERE interaction_scenes.current_status IS DISTINCT FROM 'open'
                   OR interaction_scenes.closed_at IS NOT NULL
                """,
                (subject_id, scene_key.value, party[0]),
            )
        else:
            cursor = await connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = 'closed', closed_at = statement_timestamp(),
                    scene_version = scene_version + 1
                WHERE primary_party_id = %s AND scene_key = %s
                  AND scene_kind = 'other_human_dialogue'
                  AND audience_scope = 'other_human'
                  AND current_status IS DISTINCT FROM 'closed'
                """,
                (party[0], scene_key.value),
            )
            if cursor.rowcount != 1:
                raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-SCENE-NOT-VISIBLE")
        row = await (
            await connection.execute(
                """
                SELECT scene_id, primary_party_id, current_status
                FROM armi.interaction_scenes
                WHERE primary_party_id = %s AND scene_key = %s
                  AND scene_kind = 'other_human_dialogue'
                  AND audience_scope = 'other_human'
                """,
                (party[0], scene_key.value),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-SCENE")
        await connection.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            )
            SELECT scene.scene_id, scene.subject_id, scene.primary_party_id, 'primary'
            FROM armi.interaction_scenes AS scene
            WHERE scene.scene_id = %s
            ON CONFLICT (scene_id, party_id)
            DO UPDATE SET last_observed_at = statement_timestamp()
            """,
            (row[0],),
        )
        return OtherHumanSceneView(row[0], row[1], scene_key, SceneStatus(row[2]))

    async def context(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        party_key: OtherHumanPartyKey,
        scene_key: SceneKey,
        lock: bool = False,
    ) -> OtherHumanInputContext:
        connection = unit_of_work.transaction
        suffix = " FOR UPDATE OF scene" if lock else ""
        row = await (
            await connection.execute(
                """
                SELECT scene.subject_id, party.party_id, scene.scene_id
                FROM armi.parties AS party
                JOIN armi.interaction_scenes AS scene
                  ON scene.subject_id = %s
                 AND party.party_kind = 'other_human'
                 AND party.creator_role IS NULL
                 AND party.declared_identity_key = %s
                 AND party.status = 'active'
                 AND scene.primary_party_id = party.party_id
                 AND scene.scene_key = %s
                 AND scene.scene_kind = 'other_human_dialogue'
                 AND scene.audience_scope = 'other_human'
                 AND scene.current_status = 'open' AND scene.closed_at IS NULL
                """
                + suffix,
                (subject_id, party_key.value, scene_key.value),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-SCENE-NOT-VISIBLE")
        return OtherHumanInputContext(row[0], row[1], row[2])

    async def existing(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: OtherHumanInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> OtherHumanInputAcceptance | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT interaction.interaction_id, interaction.request_digest,
                       COALESCE(interaction.cognition_content_digest,
                                interaction.content_digest)
                FROM armi.party_input_interactions AS interaction
                WHERE interaction.source_party_id = %s AND interaction.scene_id = %s
                  AND interaction.purpose = 'other_human_message'
                  AND interaction.idempotency_key = %s
                """,
                (context.party_id, context.scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if row[1] != request_digest.value:
            raise OtherHumanInputViolation("IDEMPOTENCY-OTHER-HUMAN-INPUT-MISMATCH")
        evidence_id = await self._evidence_read.find_by_interaction(
            connection, interaction_id=row[0]
        )
        if evidence_id is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-INPUT")
        opportunity = await self._opportunity.find_external_evidence(
            connection,
            evidence_id=evidence_id.value,
            purpose=OpportunityPurpose.CONSIDER_OTHER_HUMAN_INPUT,
        )
        if opportunity is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-INPUT")
        return OtherHumanInputAcceptance(
            context.party_id,
            context.scene_id,
            OtherHumanInteractionId(row[0]),
            evidence_id,
            OpportunityId(opportunity.value),
            Digest(row[1]),
            Digest(row[2]),
            False,
        )

    async def create(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: OtherHumanInputContext,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        artifact_id: UUID,
        trace_id: str,
        external_binding_id: UUID | None = None,
        external_message_key: str | None = None,
        addressed_to_subject: bool | None = None,
    ) -> OtherHumanInputAcceptance:
        connection = unit_of_work.transaction
        interaction_id, evidence_id, timeline_id = (
            uuid7(),
            uuid7(),
            uuid7(),
        )
        await connection.execute(
            """
            INSERT INTO armi.party_input_interactions (
                interaction_id, subject_id, scene_id, source_party_id,
                purpose, idempotency_key, request_digest, content_digest, trace_id,
                external_binding_id, external_message_key, addressed_to_subject
            ) VALUES (%s,%s,%s,%s,'other_human_message',%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.party_id,
                idempotency_key,
                request_digest.value,
                content_digest.value,
                trace_id,
                external_binding_id,
                external_message_key,
                addressed_to_subject,
            ),
        )
        await self._evidence.accept(
            unit_of_work,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.party_id,
                artifact_id=artifact_id,
                source_kind=EvidenceSourceKind.OTHER_HUMAN_INPUT,
                privacy_scope=EvidencePrivacyScope.PRIVATE,
                interaction_id=interaction_id,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.party_id,
                purpose=OpportunityPurpose.CONSIDER_OTHER_HUMAN_INPUT,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-INPUT")
        opportunity_id = admitted.opportunity_id
        if opportunity_id is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-INPUT")
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at) VALUES (%s,%s,'other_human_input',%s,1,'accepted',statement_timestamp())
            """,
            (timeline_id, context.scene_id, interaction_id),
        )
        await connection.execute(
            """UPDATE armi.interaction_scenes
               SET recent_context_boundary = %s,
                   scene_version = scene_version + 1
               WHERE scene_id = %s AND current_status = 'open'
                 AND recent_context_boundary IS DISTINCT FROM %s""",
            (timeline_id, context.scene_id, timeline_id),
        )
        return OtherHumanInputAcceptance(
            context.party_id,
            context.scene_id,
            OtherHumanInteractionId(interaction_id),
            EvidenceId(evidence_id),
            OpportunityId(opportunity_id),
            request_digest,
            content_digest,
            True,
        )


__all__ = ("OtherHumanInputContext", "OtherHumanInputRepository")
