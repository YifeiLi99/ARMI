"""PostgreSQL owner for caller-declared other-human parties, scenes and input."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.contracts import Digest
from armi_opportunity.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

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


@dataclass(frozen=True, slots=True)
class OtherHumanInputContext:
    subject_id: UUID
    party_id: UUID
    scene_id: UUID


class OtherHumanInputRepository:
    __slots__ = ("_evidence", "_opportunity")

    def __init__(
        self,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
    ) -> None:
        self._evidence = evidence
        self._opportunity = opportunity

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
                SELECT uuidv7(), subject_id, %s, 'other_human_dialogue',
                       %s, 'other_human', 'other_human', 'open'
                FROM armi.subjects
                WHERE singleton_key = 1 AND status = 'active'
                ON CONFLICT (subject_id, primary_party_id, scene_key)
                DO UPDATE SET current_status = 'open', closed_at = NULL,
                              scene_version = interaction_scenes.scene_version + 1
                WHERE interaction_scenes.current_status IS DISTINCT FROM 'open'
                   OR interaction_scenes.closed_at IS NOT NULL
                """,
                (scene_key.value, party[0]),
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
        party_key: OtherHumanPartyKey,
        scene_key: SceneKey,
        lock: bool = False,
    ) -> OtherHumanInputContext:
        connection = unit_of_work.transaction
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
                SELECT interaction.interaction_id, evidence.evidence_id,
                       interaction.request_digest,
                       COALESCE(interaction.cognition_content_digest,
                                interaction.content_digest)
                FROM armi.party_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id = interaction.interaction_id
                WHERE interaction.source_party_id = %s AND interaction.scene_id = %s
                  AND interaction.purpose = 'other_human_message'
                  AND interaction.idempotency_key = %s
                """,
                (context.party_id, context.scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if row[2] != request_digest.value:
            raise OtherHumanInputViolation("IDEMPOTENCY-OTHER-HUMAN-INPUT-MISMATCH")
        opportunity = await self._opportunity.find_external_evidence(
            connection,
            evidence_id=row[1],
            purpose=OpportunityPurpose.CONSIDER_OTHER_HUMAN_INPUT,
        )
        if opportunity is None:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-INPUT")
        return OtherHumanInputAcceptance(
            context.party_id,
            context.scene_id,
            OtherHumanInteractionId(row[0]),
            EvidenceId(row[1]),
            OpportunityId(opportunity.value),
            Digest(row[2]),
            Digest(row[3]),
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
