"""Mood-owned assessment receipts and independent, versioned state commits."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import ProviderCallReceipt
from armi_runtime_foundation import PostgreSQLTransaction

from ._evaluation_contract import MoodAssessment, MoodEvent
from ._psychology import MoodDynamics, apply_appraisal
from ._questions import EvaluatedAppraisal
from .api import MoodViolation


class MoodEventOwner:
    async def record_provider_call(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        receipt: ProviderCallReceipt,
    ) -> None:
        changed = await transaction.execute(
            """UPDATE armi.mood_assessments
               SET provider_calls=jsonb_set(provider_calls,ARRAY[%s],%s::jsonb)
               WHERE mood_assessment_id=%s AND
                 ((%s AND status='running' AND NOT provider_calls ? %s)
                  OR (NOT %s AND provider_calls ? %s))""",
            (
                receipt.call_id,
                rfc8785.dumps(cast(Any, receipt.document())).decode(),
                assessment_id,
                receipt.registration,
                receipt.call_id,
                receipt.registration,
                receipt.call_id,
            ),
        )
        if changed.rowcount != 1:
            raise MoodViolation("MOOD-ASSESSMENT-STALE")

    async def begin(
        self,
        transaction: PostgreSQLTransaction,
        *,
        event: MoodEvent,
        context: dict[str, Any],
    ) -> MoodAssessment:
        row = await (
            await transaction.execute(
                """SELECT mood_version,semantic_payload FROM armi.mood_revisions
               WHERE subject_id=%s AND is_current FOR UPDATE""",
                (event.subject_id,),
            )
        ).fetchone()
        if row is None:
            raise MoodViolation("MOOD-MISSING")
        state = MoodDynamics.model_validate(row[1])
        receipt = await (
            await transaction.execute(
                """SELECT mood_assessment_id,status FROM armi.mood_assessments
               WHERE subject_id=%s AND event_key=%s""",
                (event.subject_id, event.event_key),
            )
        ).fetchone()
        if receipt is not None:
            return MoodAssessment(receipt[0], event, receipt[1], int(row[0]), state)
        assessment_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.mood_assessments
               (mood_assessment_id,subject_id,event_key,cognitive_episode_id,source_ref,
                source_version,occurred_at,status,base_mood_version,context_document)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'running',%s,%s::jsonb)""",
            (
                assessment_id,
                event.subject_id,
                event.event_key,
                event.episode_id,
                event.source_ref,
                event.source_version,
                event.occurred_at,
                row[0],
                rfc8785.dumps(
                    {
                        "event": {
                            "content": event.summary,
                            "source_ref": str(event.source_ref),
                            "source_version": event.source_version,
                        },
                        "context": context,
                    }
                ).decode(),
            ),
        )
        return MoodAssessment(assessment_id, event, "new", int(row[0]), state)

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment: MoodAssessment,
        result: EvaluatedAppraisal,
        at: datetime,
    ) -> bool:
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
        result_row = await (
            await transaction.execute(
                """UPDATE armi.mood_assessments SET status=%s,mood_revision_id=%s,
                   appraisal=%s::jsonb,answers=%s::jsonb,input_tokens=%s,output_tokens=%s,
                   completed_at=statement_timestamp()
               WHERE mood_assessment_id=%s AND status='running' RETURNING mood_assessment_id""",
                (
                    "applied" if emotional_change else "unchanged",
                    revision_id,
                    result.appraisal.model_dump_json(),
                    rfc8785.dumps(result.answers).decode(),
                    result.input_tokens,
                    result.output_tokens,
                    assessment.assessment_id,
                ),
            )
        ).fetchone()
        if result_row is None:
            raise MoodViolation("MOOD-ASSESSMENT-STALE")
        return changed

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        code: str,
        interrupted: bool = False,
    ) -> None:
        await transaction.execute(
            """UPDATE armi.mood_assessments SET status=%s,error_code=%s,
                   completed_at=statement_timestamp()
               WHERE mood_assessment_id=%s AND status='running'""",
            ("interrupted" if interrupted else "failed", code, assessment_id),
        )
