from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_mind.api import (
    DIMENSIONS,
    DimensionEvent,
    DynamicsParameters,
    SocialEvidence,
    contact_drive,
    dimensions_projection,
    exponential_value,
    initial_dimensions,
    update_dimensions,
)

PARAMETERS = DynamicsParameters()


def test_parameter_change_advances_old_curve_before_adopting_new_half_life():
    from armi_mind._state_storage import (
        correct_numeric_mind,
        initial_numeric_mind_state,
        numeric_mind_state,
    )

    previous = initial_numeric_mind_state()
    proposed = numeric_mind_state(previous).model_copy(
        update={"parameters": DynamicsParameters(half_life_seconds=7200.0)}
    )
    changed = numeric_mind_state(
        correct_numeric_mind(
            previous,
            proposed.model_dump_json().encode(),
            correction_id=uuid7(),
            at=datetime.now(UTC),
            active_seconds=14400.0,
        )
    )
    assert changed.dimensions[0].value == 0.5
    assert exponential_value(changed.dimensions[0], 21600.0) == 0.75


def test_previous_payload_is_rejected_instead_of_filled_with_defaults():
    from armi_mind._state_storage import numeric_mind_state

    with pytest.raises(ValueError):
        numeric_mind_state(b'{"schema_kind":"armi.mind","objects":[]}')


def evidence(
    person="a",
    *,
    contact=False,
    quality="unknown",
    importance="unknown",
    cue="not_applicable",
):
    return SocialEvidence.model_validate(
        dict(
            person_ref=person,
            received_contact=contact,
            quality=quality,
            importance=importance,
            cue=cue,
        )
    )


def update(states, event, *, seconds=0.0, key="event"):
    return update_dimensions(
        states,
        evidence=DimensionEvent(social=event),
        event_key=key,
        basis_refs=(key,),
        active_seconds=seconds,
        parameters=PARAMETERS,
    )


def test_time_projects_without_creating_revisions_or_relationships():
    states = initial_dimensions(PARAMETERS)
    before = tuple(s.model_dump_json() for s in states)
    assert len(states) == 1
    for _ in range(20):
        assert (
            contact_drive(states, person_ref="creator", active_seconds=14400.0) == 0.5
        )
        assert dimensions_projection(states, active_seconds=28800.0)[0]["value"] == 75.0
    assert before == tuple(s.model_dump_json() for s in states)
    assert exponential_value(states[0], 0.0) == 0.0


def test_grounded_persons_grow_independently_and_contact_only_satisfies_one():
    states = update(initial_dimensions(PARAMETERS), evidence(importance="level_4"))
    states = update(states, evidence("b", importance="level_2"), key="b")
    before_b = states[2]
    states = update(
        states, evidence(contact=True, quality="level_4"), seconds=14400.0, key="reply"
    )
    assert states[0].value == states[1].value == 0.25
    assert states[2] == before_b
    assert exponential_value(states[2], 14400.0) == 0.25
    assert (
        update(
            states,
            evidence(contact=True, quality="level_4"),
            seconds=14400.0,
            key="reply",
        )
        == states
    )


def test_unknown_and_rejection_have_distinct_grounded_feedback():
    states = initial_dimensions(PARAMETERS)
    unknown = update(states, evidence(contact=True), seconds=14400.0)
    rejection = update(
        states, evidence(contact=True, quality="rejecting"), seconds=14400.0
    )
    assert unknown[0].value == pytest.approx(0.475)
    assert rejection[0].value == 0.5
    assert len(unknown) == len(rejection) == 1
    cue = update(states, evidence(cue="level_4"))
    assert cue[1].value == 0.1
    assert cue[1].equilibrium == 0.0


def test_registry_extension_uses_the_same_projection_and_event_storage(monkeypatch):
    from armi_mind import _state_storage as storage
    from armi_mind.api import (
        Association,
        GroundedObject,
        MindChoice,
        MindEvidence,
        MindVariable,
        Opportunity,
    )

    def react(state, event, _parameters):
        return (
            0.9 if dict(event.choices).get("novelty") == "level_4" else state.value,
            state.equilibrium,
        )

    definition = replace(
        DIMENSIONS["companionship"],
        name="synthetic_need",
        initial_value=0.2,
        reduce=react,
    )
    registry = {**DIMENSIONS, definition.name: definition}
    monkeypatch.setattr(storage, "DIMENSIONS", registry)
    states = initial_dimensions(PARAMETERS, registry=registry)
    projected = dimensions_projection(states, active_seconds=14400.0, registry=registry)
    assert projected[1]["value"] == 60.0
    payload = storage.initial_numeric_mind_state()
    event = MindEvidence(
        GroundedObject("event", str(uuid7())),
        "novel",
        ("new evidence",),
        datetime.now(UTC),
        ((MindVariable.NOVELTY, MindChoice.FULL),),
        Association.ACTIVE,
        Opportunity.AVAILABLE,
        active_seconds=14400.0,
    )
    updated = storage.apply_mind_evidence(payload, (event,))
    result = storage.numeric_mind_state(updated)
    assert result.dimensions[1].value == 0.9
    assert storage.apply_mind_evidence(updated, (event,)) == updated
