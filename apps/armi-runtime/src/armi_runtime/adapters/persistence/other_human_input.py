"""PostgreSQL owner for caller-declared other-human parties, scenes and input."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_kernel.application import (
    EvidenceId,
    OpportunityId,
    OtherHumanInputAcceptance,
    OtherHumanInputViolation,
    OtherHumanInteractionId,
    OtherHumanPartyKey,
    OtherHumanPartyView,
    OtherHumanSceneView,
    SceneKey,
    SceneStatus,
)
from armi_kernel.contracts import Digest

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class OtherHumanInputContext:
    subject_id: UUID
    party_id: UUID
    scene_id: UUID


class OtherHumanInputRepository:
    __slots__ = ()

    async def register_party(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        party_key: OtherHumanPartyKey,
        display_label: str,
    ) -> OtherHumanPartyView:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        party_key: OtherHumanPartyKey,
        scene_key: SceneKey,
        target_status: SceneStatus,
    ) -> OtherHumanSceneView:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
                    current_status, schema_version
                )
                SELECT uuidv7(), subject_id, %s, 'other_human_dialogue',
                       %s, 'other_human', 'other_human', 'open', 1
                FROM armi.subjects
                WHERE singleton_key = 1 AND status = 'active'
                ON CONFLICT (subject_id, primary_party_id, scene_key)
                DO UPDATE SET current_status = 'open', closed_at = NULL
                """,
                (scene_key.value, party[0]),
            )
        else:
            cursor = await connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = 'closed', closed_at = statement_timestamp()
                WHERE primary_party_id = %s AND scene_key = %s
                  AND scene_kind = 'other_human_dialogue'
                  AND audience_scope = 'other_human'
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
        return OtherHumanSceneView(row[0], row[1], scene_key, SceneStatus(row[2]))

    async def context(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        party_key: OtherHumanPartyKey,
        scene_key: SceneKey,
        lock: bool = False,
    ) -> OtherHumanInputContext:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        suffix = " FOR UPDATE OF scene" if lock else ""
        row = await (
            await connection.execute(
                """
                SELECT subject.subject_id, party.party_id, scene.scene_id
                FROM armi.subjects AS subject
                JOIN armi.parties AS party
                  ON party.party_kind = 'other_human'
                 AND party.creator_role IS NULL
                 AND party.declared_identity_key = %s
                 AND party.status = 'active'
                JOIN armi.interaction_scenes AS scene
                  ON scene.subject_id = subject.subject_id
                 AND scene.primary_party_id = party.party_id
                 AND scene.scene_key = %s
                 AND scene.scene_kind = 'other_human_dialogue'
                 AND scene.audience_scope = 'other_human'
                 AND scene.current_status = 'open' AND scene.closed_at IS NULL
                WHERE subject.singleton_key = 1 AND subject.status = 'active'
                """
                + suffix,
                (party_key.value, scene_key.value),
            )
        ).fetchone()
        if row is None:
            raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-SCENE-NOT-VISIBLE")
        return OtherHumanInputContext(row[0], row[1], row[2])

    async def existing(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: OtherHumanInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> OtherHumanInputAcceptance | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT interaction.other_human_interaction_id, evidence.evidence_id,
                       opportunity.opportunity_id, interaction.request_digest,
                       interaction.content_digest
                FROM armi.other_human_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.other_human_interaction_id = interaction.other_human_interaction_id
                JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id = evidence.evidence_id
                 AND opportunity.purpose = 'consider_other_human_input'
                WHERE interaction.other_party_id = %s AND interaction.scene_id = %s
                  AND interaction.purpose = 'other_human_message'
                  AND interaction.idempotency_key = %s
                """,
                (context.party_id, context.scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if row[3] != request_digest.value:
            raise OtherHumanInputViolation("IDEMPOTENCY-OTHER-HUMAN-INPUT-MISMATCH")
        return OtherHumanInputAcceptance(
            context.party_id,
            context.scene_id,
            OtherHumanInteractionId(row[0]),
            EvidenceId(row[1]),
            OpportunityId(row[2]),
            Digest(row[3]),
            Digest(row[4]),
            False,
        )

    async def create(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: OtherHumanInputContext,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        artifact_id: UUID,
        trace_id: str,
    ) -> OtherHumanInputAcceptance:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        interaction_id, evidence_id, opportunity_id, timeline_id = (
            uuid7(),
            uuid7(),
            uuid7(),
            uuid7(),
        )
        await connection.execute(
            """
            INSERT INTO armi.other_human_input_interactions (
                other_human_interaction_id, subject_id, scene_id, other_party_id,
                purpose, idempotency_key, request_digest, content_digest, trace_id
            ) VALUES (%s,%s,%s,%s,'other_human_message',%s,%s,%s,%s)
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
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, creator_interaction_id, other_human_interaction_id,
                subject_id, scene_id, creator_party_id, other_party_id, artifact_id,
                source_kind, trust_status, privacy_scope, acceptance_status
            ) VALUES (%s,NULL,%s,%s,%s,NULL,%s,%s,
                      'other_human_input','external_claim','private','accepted')
            """,
            (
                evidence_id,
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.party_id,
                artifact_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, other_party_id, purpose, eligibility_status,
                current_disposition, source_kind, source_ref, source_version,
                source_digest, reconsideration_no, schema_version
            ) VALUES (%s,%s,%s,%s,NULL,%s,'consider_other_human_input',
                      'eligible','open','external_evidence',%s,1,%s,0,1)
            """,
            (
                opportunity_id,
                evidence_id,
                context.subject_id,
                context.scene_id,
                context.party_id,
                evidence_id,
                content_digest.value,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at, schema_version
            ) VALUES (%s,%s,'other_human_input',%s,1,'accepted',statement_timestamp(),1)
            """,
            (timeline_id, context.scene_id, interaction_id),
        )
        await connection.execute(
            """UPDATE armi.interaction_scenes SET recent_context_boundary = %s
               WHERE scene_id = %s AND current_status = 'open'""",
            (timeline_id, context.scene_id),
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
