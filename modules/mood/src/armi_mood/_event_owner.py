"""Mood-owned independent, versioned event state commits."""

from datetime import datetime
from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from ._evaluation_contract import MoodAssessment
from ._psychology import MoodDynamics, apply_appraisal
from ._questions import EvaluatedAppraisal
from .api import MoodViolation


class MoodEventOwner:
    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment: MoodAssessment,
        result: EvaluatedAppraisal,
        at: datetime,
    ) -> tuple[bool, UUID, bool]:
        row = await (
            await transaction.execute(
                """SELECT mood_revision_id,mood_version,semantic_payload FROM armi.mood_revisions
               WHERE subject_id=%s AND is_current FOR UPDATE""",
                (assessment.event.subject_id,),
            )
        ).fetchone()
        if row is None or int(row[1]) != assessment.mood_version:
            raise MoodViolation("MOOD-HEAD-STALE")
        state = MoodDynamics.model_validate(row[2])
        updated = apply_appraisal(
            state,
            event_id=str(assessment.assessment_id),
            situation_id=result.situation_id,
            appraisal=result.appraisal,
            at=at,
            summary=assessment.event.summary,
        )
        # A successful no-effect evaluation is still a fact, unlike a failed call.
        changed = updated.episodes != state.episodes
        affected = tuple(
            episode
            for candidate in (state, updated)
            for episode in candidate.episodes
            if episode.situation_id == result.situation_id
        )
        emotional_change = changed and any(
            episode.response.affect.valence != 0
            or episode.response.affect.arousal != 0
            or episode.response.emotions
            for episode in affected
        )
        revision_id = row[0]
        if changed:
            revision_id = uuid7()
            await transaction.execute(
                """UPDATE armi.mood_revisions SET is_current=false
                   WHERE mood_revision_id=%s AND is_current""",
                (row[0],),
            )
            await transaction.execute(
                """INSERT INTO armi.mood_revisions
                   (mood_revision_id,subject_id,mood_version,previous_revision_id,
                    origin_kind,origin_ref,semantic_payload,is_current)
                   VALUES (%s,%s,%s,%s,'event_appraisal',%s,%s::jsonb,true)""",
                (
                    revision_id,
                    assessment.event.subject_id,
                    int(row[1]) + 1,
                    row[0],
                    assessment.assessment_id,
                    updated.model_dump_json(),
                ),
            )
        return changed, revision_id, emotional_change
