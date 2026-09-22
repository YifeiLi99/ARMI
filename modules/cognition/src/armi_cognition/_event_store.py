"""Cognition owns event evaluation identity, frozen versions and provider usage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import ProviderCallReceipt
from armi_mind.api import GroundedObject, MindEvaluationTarget, MindHead, MindReadPort
from armi_mood.api import MoodAssessment, MoodEvent, MoodReadPort
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction


class PostgreSQLAppraisalRead:
    async def latest(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[Any, ...] | None:
        return await (
            await transaction.execute(
                """SELECT CASE WHEN mood_status='running' AND status IN ('failed','interrupted')
                 THEN status ELSE mood_status END,event_appraisal_id,COALESCE(mood_error,error_code),
                 mood_result->'appraisal' FROM armi.event_appraisals
               WHERE subject_id=%s ORDER BY created_at DESC,event_appraisal_id DESC LIMIT 1""",
                (subject_id,),
            )
        ).fetchone()

    def latest_admin(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> tuple[Any, ...] | None:
        return transaction.execute(
            """SELECT CASE WHEN mood_status='running' AND status IN ('failed','interrupted')
                 THEN status ELSE mood_status END,event_appraisal_id,COALESCE(mood_error,error_code),
                 mood_result->'appraisal' FROM armi.event_appraisals
               WHERE subject_id=%s ORDER BY created_at DESC,event_appraisal_id DESC LIMIT 1""",
            (subject_id,),
        ).fetchone()


@dataclass(frozen=True, slots=True)
class EventAssessment:
    assessment_id: UUID
    status: str
    event: MoodEvent
    mood: MoodAssessment
    mind: MindHead
    targets: tuple[MindEvaluationTarget, ...]


class EventAppraisalStorePort(Protocol):
    async def begin(
        self,
        transaction: PostgreSQLTransaction,
        *,
        event: MoodEvent,
        context: dict[str, Any],
    ) -> EventAssessment: ...

    async def record_provider_call(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        receipt: ProviderCallReceipt,
    ) -> None: ...

    async def record_result(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        owner: Literal["mood", "mind"],
        status: Literal["applied", "unchanged", "failed"],
        revision_id: UUID | None,
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None: ...

    async def finish(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        input_tokens: int,
        output_tokens: int,
    ) -> bool: ...

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        code: str,
        interrupted: bool = False,
    ) -> None: ...


def evaluation_targets(
    event: MoodEvent, context: dict[str, Any]
) -> tuple[MindEvaluationTarget, ...]:
    items = [item for layer in context["layers"] for item in layer["items"]]
    candidates: list[tuple[int, MindEvaluationTarget]] = []
    for kind in ("current_activity", "current_concern", "current_motivation"):
        for item in items:
            if item["item_kind"] != kind or "reference" not in item["source"]:
                continue
            source = item["source"]
            content = json.loads(item["content"])
            obj = GroundedObject(source["kind"], source["reference"])
            if kind == "current_activity":
                obj = GroundedObject("activity", content["activity_id"])
            if kind == "current_motivation":
                value = content["object"]
                obj = GroundedObject(value["source_kind"], value["source_ref"])
            due = content.get(
                "consideration_reason"
            ) == "review_time_reached" or content.get("consideration", {}).get(
                "eligible", False
            )
            rank = 0 if kind == "current_activity" else 2 if due else 3
            candidates.append(
                (
                    rank,
                    MindEvaluationTarget(
                        obj, (source["reference"], str(event.source_ref))
                    ),
                )
            )
    # Prefer a formally linked activity; otherwise the accepted event supplies a
    # new source-bound object. Remaining slots follow the frozen owner window.
    candidates.append(
        (
            1,
            MindEvaluationTarget(
                GroundedObject("event", str(event.source_ref)), (str(event.source_ref),)
            ),
        )
    )
    ordered = [target for _, target in sorted(candidates, key=lambda item: item[0])]
    unique: dict[str, MindEvaluationTarget] = {}
    for target in ordered:
        unique.setdefault(target.object.source_ref, target)
        if len(unique) == 4:
            break
    return tuple(unique.values())


class PostgreSQLEventAppraisalStore:
    def __init__(self, mood: MoodReadPort, mind: MindReadPort) -> None:
        self._mood = mood
        self._mind = mind

    async def begin(
        self,
        transaction: PostgreSQLTransaction,
        *,
        event: MoodEvent,
        context: dict[str, Any],
    ) -> EventAssessment:
        mood = await self._mood.snapshot(transaction, subject_id=event.subject_id)
        mind = await self._mind.current_head(transaction, subject_id=event.subject_id)
        row = await (
            await transaction.execute(
                "SELECT event_appraisal_id,status FROM armi.event_appraisals WHERE subject_id=%s AND event_key=%s",
                (event.subject_id, event.event_key),
            )
        ).fetchone()
        assessment_id, status = (row[0], str(row[1])) if row else (uuid7(), "new")
        targets = evaluation_targets(event, context)
        if row is None:
            await transaction.execute(
                """INSERT INTO armi.event_appraisals
                   (event_appraisal_id,subject_id,event_key,cognitive_episode_id,source_ref,
                    source_version,occurred_at,status,base_mood_version,base_mind_version,
                    context_document,mood_status,mind_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s::jsonb,'running','running')""",
                (
                    assessment_id,
                    event.subject_id,
                    event.event_key,
                    event.episode_id,
                    event.source_ref,
                    event.source_version,
                    event.occurred_at,
                    mood.version,
                    mind.version,
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
        return EventAssessment(
            assessment_id,
            status,
            event,
            MoodAssessment(assessment_id, event, status, mood.version, mood.state),
            mind,
            targets,
        )

    async def record_provider_call(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        receipt: ProviderCallReceipt,
    ) -> None:
        result = await transaction.execute(
            """UPDATE armi.event_appraisals SET provider_calls=jsonb_set(provider_calls,ARRAY[%s],%s::jsonb)
               WHERE event_appraisal_id=%s AND
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
        if result.rowcount != 1:
            raise ValueError("COGNITION-APPRAISAL-STALE")

    async def record_result(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        owner: Literal["mood", "mind"],
        status: Literal["applied", "unchanged", "failed"],
        revision_id: UUID | None,
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        if owner == "mood":
            statement = """UPDATE armi.event_appraisals SET mood_status=%s,mood_revision_id=%s,
                mood_result=%s::jsonb,mood_error=%s WHERE event_appraisal_id=%s AND mood_status='running'"""
        else:
            statement = """UPDATE armi.event_appraisals SET mind_status=%s,mind_revision_id=%s,
                mind_result=%s::jsonb,mind_error=%s WHERE event_appraisal_id=%s AND mind_status='running'"""
        result = await transaction.execute(
            statement,
            (
                status,
                revision_id,
                None if payload is None else rfc8785.dumps(payload).decode(),
                error,
                assessment_id,
            ),
        )
        if result.rowcount != 1:
            raise ValueError("COGNITION-APPRAISAL-PART-STALE")

    async def finish(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        row = await (
            await transaction.execute(
                """UPDATE armi.event_appraisals SET
                status=CASE WHEN mood_status IN ('applied','unchanged') AND mind_status IN ('applied','unchanged')
                    THEN 'applied' ELSE 'failed' END,input_tokens=%s,output_tokens=%s,
                completed_at=statement_timestamp() WHERE event_appraisal_id=%s AND status='running'
                RETURNING status""",
                (input_tokens, output_tokens, assessment_id),
            )
        ).fetchone()
        if row is None:
            raise ValueError("COGNITION-APPRAISAL-STALE")
        return row[0] == "applied"

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        code: str,
        interrupted: bool = False,
    ) -> None:
        await transaction.execute(
            """UPDATE armi.event_appraisals SET status=%s,error_code=%s,
            completed_at=statement_timestamp() WHERE event_appraisal_id=%s AND status='running'""",
            ("interrupted" if interrupted else "failed", code, assessment_id),
        )
