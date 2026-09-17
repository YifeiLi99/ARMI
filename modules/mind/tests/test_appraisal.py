from datetime import UTC, datetime, timedelta

import pytest
from armi_mind.api import MindAppraisal, evaluate_motivation, project_motivation

NOW = datetime(2026, 9, 17, tzinfo=UTC)
REFS = {"ctx:1": "synthetic-person", "ctx:2": "synthetic-evidence"}


def appraisal(**changes):
    return MindAppraisal.model_validate(
        dict(
            object_ref="ctx:1",
            basis_refs=("ctx:2",),
            desired_outcome="connect",
            significance="important",
            discrepancy="substantial",
            understanding="sufficient",
            progress="unknown",
            opportunity="later",
            resolution="open",
            explanation="有想分享的具体内容,知道对方在忙。",
        )
        | changes
    )


def test_frequency_does_not_accelerate_motivation():
    value = appraisal()
    original = evaluate_motivation(value, references=REFS, at=NOW)
    frequent = original
    for minute in range(1, 121):
        frequent = evaluate_motivation(
            value,
            references=REFS,
            at=NOW + timedelta(minutes=minute),
            previous=frequent,
        )
    later = NOW + timedelta(hours=2)
    assert project_motivation(frequent, at=later).level == pytest.approx(
        project_motivation(original, at=later).level
    )
    assert 0 < project_motivation(original, at=later).level < 65


def test_resolved_or_released_stops_and_unknown_does_not_erase():
    old = evaluate_motivation(appraisal(), references=REFS, at=NOW)
    later = NOW + timedelta(hours=1)
    unknown = evaluate_motivation(
        appraisal(significance="unknown"), references=REFS, at=later, previous=old
    )
    assert project_motivation(unknown, at=later).uncertain
    assert unknown.target_level == old.target_level
    for ending in ("satisfied", "released"):
        ended = evaluate_motivation(
            appraisal(resolution=ending), references=REFS, at=later, previous=old
        )
        assert project_motivation(ended, at=later + timedelta(days=2)).level == 0


@pytest.mark.parametrize(
    "outcome,field,value",
    [
        ("understand", "understanding", "sufficient"),
        ("engage", "progress", "advancing"),
        ("connect", "discrepancy", "none"),
    ],
)
def test_time_alone_cannot_create_unmet_motive(outcome, field, value):
    state = evaluate_motivation(
        appraisal(desired_outcome=outcome, **{field: value}), references=REFS, at=NOW
    )
    assert project_motivation(state, at=NOW + timedelta(days=100)).level == 0


def test_reference_identity_and_time_are_owned_by_host():
    with pytest.raises(ValueError, match="REFERENCE"):
        evaluate_motivation(appraisal(), references={}, at=NOW)
    state = evaluate_motivation(appraisal(), references=REFS, at=NOW)
    with pytest.raises(ValueError, match="OBJECT"):
        evaluate_motivation(
            appraisal(), references=REFS | {"ctx:1": "other"}, at=NOW, previous=state
        )
    with pytest.raises(ValueError, match="TIME"):
        project_motivation(state, at=NOW - timedelta(seconds=1))


def test_no_opportunity_does_not_erase_wish_or_force_action():
    state = evaluate_motivation(
        appraisal(opportunity="unavailable"), references=REFS, at=NOW
    )
    view = project_motivation(state, at=NOW + timedelta(hours=2))
    assert view.level > 0
    assert view.opportunity == "unavailable"


def test_new_feedback_reduces_target_and_ends_the_same_object():
    curious = appraisal(desired_outcome="understand", understanding="unexplained")
    state = evaluate_motivation(curious, references=REFS, at=NOW)
    later = NOW + timedelta(hours=1)
    initial_level = project_motivation(state, at=later).level
    # An unsuccessful tool result does not change the still-unexplained situation.
    failed = evaluate_motivation(curious, references=REFS, at=later, previous=state)
    assert project_motivation(failed, at=later).level == initial_level
    partial = evaluate_motivation(
        appraisal(
            desired_outcome="understand", understanding="partial", discrepancy="small"
        ),
        references=REFS,
        at=later,
        previous=failed,
    )
    assert (
        project_motivation(partial, at=later + timedelta(hours=1)).level < initial_level
    )
    answered = evaluate_motivation(
        appraisal(
            desired_outcome="understand",
            understanding="sufficient",
            discrepancy="none",
            resolution="satisfied",
        ),
        references=REFS,
        at=later + timedelta(hours=1),
        previous=partial,
    )
    assert answered.object_id == state.object_id
    assert project_motivation(answered, at=later + timedelta(days=1)).level == 0
