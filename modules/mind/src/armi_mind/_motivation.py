"""Mind-owned binding, persistent records and consideration of motivations."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid7

from armi_kernel.application import CandidateBasis, ConsiderationSignal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ._appraisal import (
    MindAppraisal,
    MindAppraisalParameters,
    MotivationalState,
    evolve_motivation,
    project_motivation,
)


class BoundMindAppraisal(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", strict=True)
    object_id: UUID
    object_kind: str
    parameters: MindAppraisalParameters


class MotivationRecord(BoundMindAppraisal, frozen=True):
    motivation_id: UUID
    anchor_at: datetime
    anchor_level: float = Field(ge=0, le=100)
    target_level: float = Field(ge=0, le=100)
    review_at: datetime | None
    source_commit_id: UUID
    basis_ordinals: tuple[int, ...]

    def state(self) -> MotivationalState:
        return MotivationalState(
            str(self.object_id),
            self.parameters.desired_outcome,
            self.parameters,
            self.anchor_at,
            self.anchor_level,
            self.target_level,
        )


MOTIVATION_RECORDS = TypeAdapter(tuple[MotivationRecord, ...])
BOUND_APPRAISALS = TypeAdapter(tuple[BoundMindAppraisal, ...])


def bind_mind_appraisals(
    appraisals: tuple[MindAppraisal, ...],
    *,
    basis_by_ref: dict[str, CandidateBasis],
    payload: bytes,
) -> tuple[tuple[BoundMindAppraisal, ...], tuple[int, ...]]:
    from .api import MindViolation

    if not appraisals:
        return (), ()
    records = MOTIVATION_RECORDS.validate_json(
        json.dumps(json.loads(payload)["motivation_states"]), strict=True
    )
    result: list[BoundMindAppraisal] = []
    ordinals: set[int] = set()
    for index, appraisal in enumerate(appraisals):
        for ref in (appraisal.object_ref, *appraisal.basis_refs):
            if ref not in basis_by_ref:
                raise MindViolation(
                    "MIND-REFERENCE", ("mind_appraisals", index, "basis_refs")
                )
            ordinals.add(basis_by_ref[ref].ordinal)
        basis = basis_by_ref[appraisal.object_ref]
        if basis.source_ref is None:
            raise MindViolation(
                "MIND-REFERENCE", ("mind_appraisals", index, "object_ref")
            )
        object_id, object_kind = basis.source_ref, basis.item_kind
        if object_kind != "current_motivation":
            # A model may put the follow-up evidence in object_ref while explicitly
            # citing the ongoing wish as its basis. Preserve that owner's identity.
            linked = {
                r.motivation_id: r
                for ref in appraisal.basis_refs
                if basis_by_ref[ref].item_kind == "current_motivation"
                for r in records
                if r.motivation_id == basis_by_ref[ref].source_ref
                and r.parameters.resolution == "open"
                and r.parameters.desired_outcome == appraisal.desired_outcome
            }
            if len(linked) > 1:
                raise MindViolation(
                    "MIND-MOTIVATION-REFERENCE",
                    ("mind_appraisals", index, "object_ref"),
                )
            if linked:
                object_id = next(iter(linked))
                object_kind = "current_motivation"
        if object_kind == "current_motivation":
            previous = next((r for r in records if r.motivation_id == object_id), None)
            if (
                previous is None
                or previous.parameters.desired_outcome != appraisal.desired_outcome
            ):
                raise MindViolation(
                    "MIND-MOTIVATION-REFERENCE",
                    ("mind_appraisals", index, "object_ref"),
                )
            object_id, object_kind = previous.object_id, previous.object_kind
        result.append(
            BoundMindAppraisal(
                object_id=object_id,
                object_kind=object_kind,
                parameters=MindAppraisalParameters.model_validate(
                    appraisal.model_dump(exclude={"object_ref", "basis_refs"})
                ),
            )
        )
    keys = {(item.object_id, item.parameters.desired_outcome) for item in result}
    if len(keys) != len(result):
        raise MindViolation("MIND-MOTIVATION-DUPLICATE", ("mind_appraisals",))
    return tuple(result), tuple(sorted(ordinals))


def apply_mind_appraisals(
    current: tuple[MotivationRecord, ...],
    changes: tuple[BoundMindAppraisal, ...],
    *,
    now: datetime,
    commit_id: UUID,
    basis_ordinals: tuple[int, ...],
    new_identity: Callable[[], UUID] = uuid7,
) -> tuple[MotivationRecord, ...]:
    records = {
        (r.object_id, r.parameters.desired_outcome): r
        for r in current
        if r.parameters.resolution == "open"
    }
    for item in changes:
        key = (item.object_id, item.parameters.desired_outcome)
        previous = records.get(key)
        state = evolve_motivation(
            item.parameters,
            object_id=str(item.object_id),
            at=now,
            previous=None if previous is None else previous.state(),
        )
        records[key] = MotivationRecord(
            **item.model_dump(),
            motivation_id=new_identity()
            if previous is None
            else previous.motivation_id,
            anchor_at=now,
            anchor_level=state.anchor_level,
            target_level=state.target_level,
            review_at=now + timedelta(minutes=30)
            if item.parameters.resolution == "open" and state.target_level > 0
            else None,
            source_commit_id=commit_id,
            basis_ordinals=basis_ordinals,
        )
    # The per-turn appraisal bound is not a lifetime record cap; see DESIGN.md.
    # Retained motivations must not block an otherwise valid Subject Commit.
    return tuple(records.values())


def motivation_signals(
    records: tuple[MotivationRecord, ...],
) -> tuple[ConsiderationSignal, ...]:
    return tuple(
        ConsiderationSignal(
            "mind",
            r.motivation_id,
            str(r.source_commit_id),
            "review_time_reached",
            r.review_at,
            r.source_commit_id,
        )
        for r in records
        if r.review_at is not None and r.parameters.resolution == "open"
    )


def motivation_view(record: MotivationRecord, *, as_of: datetime) -> dict[str, object]:
    view = project_motivation(record.state(), at=as_of)
    return {
        "motivation_id": str(record.motivation_id),
        "object_kind": record.object_kind,
        "assessment": record.parameters.model_dump(mode="json"),
        "tendency": view.tendency,
        "level": round(view.level, 6),
        "uncertain": view.uncertain,
        "review_at": None if record.review_at is None else record.review_at.isoformat(),
    }
