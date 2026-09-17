"""Shared semantic changes and owner-owned persistent concerns."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid7

from armi_kernel.application import ConsiderationSignal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

Text = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Reference = Annotated[str, StringConstraints(min_length=1, max_length=80)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TimedReview(_Strict):
    kind: Literal["review"]
    after_seconds: int = Field(ge=60, le=21600)
    reason: Text


class CreatorInputReview(_Strict):
    kind: Literal["creator_input"]
    reason: Text


class ActivityReview(_Strict):
    kind: Literal["activity_result"]
    activity_ref: Reference = Field(
        description="Frozen Context ctx reference for the related current activity"
    )
    reason: Text


ReviewCondition = Annotated[
    TimedReview | CreatorInputReview | ActivityReview, Field(discriminator="kind")
]


class ConcernContent(_Strict):
    question: Text
    reason: Text
    resolution_condition: Text
    understanding: Text = Field(
        description="Current understanding; distinguish newly learned facts from no new information. Repeated expression is not progress."
    )
    state: Literal["open", "waiting"]
    review: ReviewCondition


class CreateConcern(ConcernContent):
    operation: Literal["create"]
    basis_refs: tuple[Reference, ...] = Field(
        min_length=1,
        max_length=8,
        description="Frozen Context ctx references grounding this concern; do not invent identities",
    )


class UpdateConcern(ConcernContent):
    operation: Literal["update"]
    concern_ref: Reference = Field(
        description="Frozen Context ctx reference of a current_concern item, not its UUID"
    )
    basis_refs: tuple[Reference, ...] = Field(min_length=1, max_length=8)


class CloseConcern(_Strict):
    operation: Literal["resolve", "release"]
    concern_ref: Reference = Field(
        description="Frozen Context ctx reference of a current_concern item, not its UUID"
    )
    conclusion: Text = Field(
        description="For resolve, explain how the cited evidence meets the existing resolution condition. For release, explain why further investment is no longer worthwhile. Delivery, failed tools and empty results are not answers."
    )
    basis_refs: tuple[Reference, ...] = Field(min_length=1, max_length=8)


ConcernChange = Annotated[
    CreateConcern | UpdateConcern | CloseConcern, Field(discriminator="operation")
]
CONCERN_CHANGES = TypeAdapter(tuple[ConcernChange, ...])


class ConcernRecord(_Strict):
    concern_id: UUID
    question: Text
    reason: Text
    resolution_condition: Text
    understanding: Text
    state: Literal["open", "waiting", "resolved", "released"]
    review: ReviewCondition | None
    review_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_commit_id: UUID
    basis_ordinals: tuple[int, ...]


CONCERN_RECORDS = TypeAdapter(tuple[ConcernRecord, ...])


def concern_attention_status(
    records: tuple[ConcernRecord, ...],
    *,
    as_of: datetime,
    consumed: frozenset[tuple[str, str, str]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in records:
        if item.state not in {"open", "waiting"} or item.review is None:
            continue
        state = "waiting_for_event"
        if item.review_at is not None:
            state = (
                "consumed"
                if ("mind", str(item.concern_id), str(item.source_commit_id))
                in consumed
                else "due"
                if item.review_at <= as_of
                else "scheduled"
            )
        result.append(
            {
                "concern_id": str(item.concern_id),
                "question": item.question,
                "state": item.state,
                "review_kind": item.review.kind,
                "review_reason": item.review.reason,
                "review_at": None
                if item.review_at is None
                else item.review_at.isoformat(),
                "condition_state": state,
            }
        )
    return result


def apply_concern_changes(
    current: tuple[ConcernRecord, ...],
    changes: tuple[ConcernChange, ...],
    *,
    now: datetime,
    commit_id: UUID,
    basis_ordinals: tuple[int, ...],
    new_identity: Callable[[], UUID] = uuid7,
) -> tuple[ConcernRecord, ...]:
    records = {
        item.concern_id: item for item in current if item.state in {"open", "waiting"}
    }
    touched: set[UUID] = set()
    for change in changes:
        try:
            concern_id = (
                new_identity()
                if isinstance(change, CreateConcern)
                else UUID(change.concern_ref)
            )
        except ValueError:
            raise ValueError("MIND-CONCERN-REFERENCE") from None
        previous = records.get(concern_id)
        if concern_id in touched or (
            not isinstance(change, CreateConcern) and previous is None
        ):
            raise ValueError("MIND-CONCERN-REFERENCE")
        touched.add(concern_id)
        if isinstance(change, CloseConcern):
            assert previous is not None
            records[concern_id] = previous.model_copy(
                update={
                    "state": "resolved"
                    if change.operation == "resolve"
                    else "released",
                    "understanding": change.conclusion,
                    "review": None,
                    "review_at": None,
                    "updated_at": now,
                    "source_commit_id": commit_id,
                    "basis_ordinals": basis_ordinals,
                }
            )
        else:
            records[concern_id] = ConcernRecord(
                concern_id=concern_id,
                question=change.question,
                reason=change.reason,
                resolution_condition=change.resolution_condition,
                understanding=change.understanding,
                state=change.state,
                review=change.review,
                review_at=now + timedelta(seconds=change.review.after_seconds)
                if isinstance(change.review, TimedReview)
                else None,
                created_at=now if previous is None else previous.created_at,
                updated_at=now,
                source_commit_id=commit_id,
                basis_ordinals=basis_ordinals,
            )
    if sum(item.state in {"open", "waiting"} for item in records.values()) > 4:
        raise ValueError("MIND-CONCERN-CAPACITY")
    return tuple(records.values())


def concern_signals(
    records: tuple[ConcernRecord, ...],
    *,
    event_purpose: str | None = None,
    event_ref: UUID | None = None,
    event_at: datetime | None = None,
    activity_id: UUID | None = None,
) -> tuple[ConsiderationSignal, ...]:
    signals: list[ConsiderationSignal] = []
    for item in records:
        if item.state not in {"open", "waiting"} or item.review is None:
            continue
        if item.review_at is not None:
            signals.append(
                ConsiderationSignal(
                    "mind",
                    item.concern_id,
                    str(item.source_commit_id),
                    "review_time_reached",
                    item.review_at,
                    item.source_commit_id,
                )
            )
        elif (
            event_ref is not None
            and event_at is not None
            and event_at > item.updated_at
        ):
            if isinstance(item.review, CreatorInputReview) and event_purpose in {
                "consider_creator_input",
                "consider_creator_voice_input",
            }:
                reason = "creator_input"
            elif (
                isinstance(item.review, ActivityReview)
                and event_purpose
                in {
                    "consider_codex_result",
                    "consider_web_evidence",
                    "consider_life_query_result",
                    "consider_requested_visual_observation",
                    "consider_visual_observation",
                    "consider_activity_internal_work",
                }
                and item.review.activity_ref == str(activity_id)
            ):
                reason = "activity_result"
            else:
                continue
            signals.append(
                ConsiderationSignal(
                    "mind",
                    item.concern_id,
                    f"{item.source_commit_id}:{event_ref}",
                    reason,
                    event_at,
                    item.source_commit_id,
                )
            )
    return tuple(signals)
