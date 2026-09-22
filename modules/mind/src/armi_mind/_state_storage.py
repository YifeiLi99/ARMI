"""Strict numeric Mind storage; derived values are never stored or supplied."""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import ConsiderationSignal, PsychologicalContextItem
from pydantic import BaseModel, ConfigDict

from ._state_algorithm import (
    Association,
    MindEvidence,
    MindObjectState,
    derive_mind,
    mind_attention_weight,
    mind_condition_eligible,
    update_mind_object,
)
from ._state_projection import project_mind_object


class NumericMindState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_kind: Literal["armi.mind"]
    objects: tuple[MindObjectState, ...]


def initial_numeric_mind_state() -> bytes:
    return b'{"objects":[],"schema_kind":"armi.mind"}'


def numeric_mind_state(payload: bytes) -> NumericMindState:
    state = NumericMindState.model_validate_json(payload, strict=True)
    if len({s.object for s in state.objects}) != len(state.objects):
        raise ValueError("MIND-DUPLICATE-OBJECT")
    return state


def apply_mind_evidence(payload: bytes, evidence: tuple[MindEvidence, ...]) -> bytes:
    state = numeric_mind_state(payload)
    if len(evidence) > 4 or len({e.object for e in evidence}) != len(evidence):
        raise ValueError("MIND-EVENT-OBJECTS")
    objects = {s.object: s for s in state.objects}
    for item in evidence:
        objects[item.object] = update_mind_object(
            item, previous=objects.get(item.object), due_review_key=item.due_review_key
        )
    result = NumericMindState(schema_kind="armi.mind", objects=tuple(objects.values()))
    return rfc8785.dumps(cast(Any, result.model_dump(mode="json")))


def correct_numeric_mind(
    previous: bytes, proposed: bytes, *, correction_id: UUID, at: datetime
) -> bytes:
    before, after = numeric_mind_state(previous), numeric_mind_state(proposed)
    old = {item.object: item for item in before.objects}
    if set(old) != {item.object for item in after.objects}:
        raise ValueError("MIND-CORRECTION-SOURCE")
    corrected: list[MindObjectState] = []
    for item in after.objects:
        prior = old[item.object]
        # Management corrects grounded primitive choices; condition versions and
        # derived motives remain algorithm-owned.
        evidence = MindEvidence(
            item.object,
            str(correction_id),
            tuple(
                sorted(
                    {
                        prior.object.source_ref,
                        *(ref for v in prior.variables for ref in v.basis_refs),
                    }
                )
            ),
            at,
            tuple((v.variable, v.quality) for v in item.variables),
            item.association,
            item.opportunity,
        )
        corrected.append(update_mind_object(evidence, previous=prior))
    return rfc8785.dumps(
        cast(
            Any,
            NumericMindState(
                schema_kind="armi.mind", objects=tuple(corrected)
            ).model_dump(mode="json"),
        )
    )


def numeric_mind_projection(
    payload: bytes, *, as_of: datetime, consumed: frozenset[tuple[str, str, str]]
) -> list[dict[str, object]]:
    return [
        project_mind_object(
            s,
            at=as_of,
            consumed_versions=frozenset(
                int(version)
                for owner, ref, version in consumed
                if owner == "mind"
                and ref == s.object.source_ref
                and version.isdecimal()
            ),
        )
        for s in numeric_mind_state(payload).objects
    ]


def numeric_mind_signals(payload: bytes) -> tuple[ConsiderationSignal, ...]:
    return tuple(
        ConsiderationSignal(
            "mind",
            UUID(s.object.source_ref),
            str(s.condition_version),
            cast(
                Literal[
                    "threshold_reached",
                    "material_change",
                    "opportunity_restored",
                    "review_time_reached",
                ],
                s.condition_reason,
            ),
            s.evaluated_at,
            priority=derive_mind(s.variables).priority or 0.0,
            basis_refs=tuple(
                sorted({ref for v in s.variables for ref in v.basis_refs})
            ),
        )
        for s in numeric_mind_state(payload).objects
        if mind_condition_eligible(s, consumed_versions=frozenset())
    )


def numeric_mind_context_items(
    payload: bytes,
    *,
    revision_id: UUID,
    version: int,
    as_of: datetime,
    purpose: str,
    signals: tuple[ConsiderationSignal, ...] = (),
    related_object_refs: frozenset[UUID] = frozenset(),
) -> tuple[PsychologicalContextItem, ...]:
    state = numeric_mind_state(payload)
    due = {str(s.object_ref) for s in signals if s.owner == "mind"}
    related = {str(ref) for ref in related_object_refs}
    selected = sorted(
        (
            s
            for s in state.objects
            if s.association
            not in {Association.RELEASED, Association.INVALID, Association.SATISFIED}
            or s.object.source_ref in related
        ),
        key=lambda s: (
            s.object.source_ref not in related,
            s.object.source_ref not in due,
            -mind_attention_weight(s, at=as_of) if s.object.source_ref in due else 0,
            s.evaluated_at,
            s.object.source_ref,
        ),
    )[:4]
    summary = rfc8785.dumps(
        {"schema_kind": "armi.mind", "assessed_objects": len(state.objects)}
    ).decode()
    return (
        PsychologicalContextItem(
            "mind",
            "mind",
            revision_id,
            version,
            summary,
            purpose != "consider_other_human_input",
            90,
        ),
        *(
            PsychologicalContextItem(
                "current_motivation",
                "mind_object",
                UUID(s.object.source_ref),
                version,
                rfc8785.dumps(
                    cast(
                        Any,
                        project_mind_object(
                            s,
                            at=as_of,
                            consumed_versions=frozenset()
                            if s.object.source_ref in due
                            else frozenset({s.condition_version}),
                        ),
                    )
                ).decode(),
                False,
                95,
            )
            for s in selected
        ),
    )
