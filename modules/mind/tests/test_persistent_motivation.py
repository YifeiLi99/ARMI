import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
import rfc8785
from armi_kernel.application import CandidateBasis, CandidateFactClass
from armi_mind.api import (
    CandidateMindDraft,
    MindAppraisal,
    MindHead,
    MindViolation,
    bind_mind_appraisals,
    initial_mind_state,
    mind_context_items,
    mind_editable_state,
    mind_motivation_projection,
    mind_signals,
    prepare_mind_change,
)
from armi_mind.bootstrap import bootstrap_mind_cognition

NOW = datetime(2026, 9, 17, tzinfo=UTC)


def assess(ref="ctx:1", **changes):
    return MindAppraisal.model_validate(
        {
            "object_ref": ref,
            "basis_refs": ("ctx:1",),
            "desired_outcome": "understand",
            "significance": "important",
            "discrepancy": "substantial",
            "understanding": "unexplained",
            "progress": "stalled",
            "opportunity": "available",
            "resolution": "open",
            "explanation": "合成观察尚无解释",
            **changes,
        }
    )


def prepare(head, appraisals, bases, at=NOW):
    bound, ordinals = bind_mind_appraisals(
        appraisals, basis_by_ref=bases, payload=head.canonical_state
    )
    draft = CandidateMindDraft(
        "proposal:1",
        "group:1",
        ordinals or (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        head.version,
        mind_editable_state(head.canonical_state),
        mind_appraisals=bound,
    )
    codec = bootstrap_mind_cognition()
    assert codec.decode(codec.bind(draft).canonical_payload) == draft
    return prepare_mind_change(head, draft, now=at, commit_id=uuid7())


def basis(identity=None, kind="interaction_input"):
    return CandidateBasis(
        1, "interaction", kind, identity or uuid7(), 1, "external_claim", "private"
    )


def test_persistent_appraisal_time_context_feedback_and_consumption():
    head = MindHead(uuid7(), 1, initial_mind_state())
    assert mind_signals(head.canonical_state) == ()
    payload = prepare(head, (assess(),), {"ctx:1": basis()})
    head = MindHead(uuid7(), 2, payload)
    signals = mind_signals(payload)
    assert len(signals) == 1
    assert signals[0].eligible_at == NOW + timedelta(minutes=30)
    assert mind_signals(payload) == signals
    later = NOW + timedelta(hours=2)
    contexts = mind_context_items(
        payload,
        revision_id=head.current_revision_id,
        version=2,
        as_of=later,
        purpose="consider_autonomous_life",
        signals=signals,
    )
    current = next(item for item in contexts if item.item_kind == "current_motivation")
    views = mind_motivation_projection(payload, as_of=later, consumed=frozenset())
    level = views[0]["level"]
    assert isinstance(level, float) and 0 < level < 65
    assert views[0]["condition_state"] == "due"
    consumed = frozenset((signals[0].identity,))
    assert (
        mind_motivation_projection(payload, as_of=later, consumed=consumed)[0][
            "condition_state"
        ]
        == "consumed"
    )
    unchanged = prepare(head, (), {}, at=later)
    assert (
        json.loads(unchanged)["motivation_states"]
        == json.loads(payload)["motivation_states"]
    )
    resolved = prepare(
        head,
        (assess(resolution="satisfied", understanding="sufficient"),),
        {"ctx:1": basis(current.source_ref, "current_motivation")},
        at=later,
    )
    assert mind_signals(resolved) == ()
    assert mind_motivation_projection(resolved, as_of=later, consumed=frozenset()) == []
    assert (
        json.loads(resolved)["motivation_states"][0]["parameters"]["resolution"]
        == "satisfied"
    )
    assert head.canonical_state == payload


@pytest.mark.parametrize("resolution", ["satisfied", "released"])
def test_first_observation_can_find_no_unmet_need_without_inventing_history(resolution):
    head = MindHead(uuid7(), 1, initial_mind_state())
    payload = prepare(head, (assess(resolution=resolution),), {"ctx:1": basis()})
    assert mind_signals(payload) == ()
    assert mind_motivation_projection(payload, as_of=NOW, consumed=frozenset()) == []
    record = json.loads(payload)["motivation_states"][0]
    assert record["anchor_level"] == 0 and record["target_level"] == 0
    assert record["parameters"]["resolution"] == resolution


def test_retained_motivations_do_not_block_new_appraisal_or_later_updates():
    head = MindHead(uuid7(), 1, initial_mind_state())
    for _ in range(6):
        before = json.loads(head.canonical_state)["motivation_states"]
        payload = prepare(head, (assess(),), {"ctx:1": basis()})
        after = json.loads(payload)["motivation_states"]
        assert after[:-1] == before
        head = MindHead(uuid7(), head.version + 1, payload)
    assert len(after) == 6
    unchanged = prepare(head, (), {})
    assert json.loads(unchanged)["motivation_states"] == after
    first_id = mind_signals(payload)[0].object_ref
    resolved = prepare(
        head,
        (assess(resolution="satisfied"),),
        {"ctx:1": basis(first_id, "current_motivation")},
    )
    assert len(mind_signals(resolved)) == 5


def test_followup_evidence_updates_existing_motivation_without_new_slot():
    payload = prepare(
        MindHead(uuid7(), 1, initial_mind_state()),
        (assess(),),
        {"ctx:1": basis()},
    )
    initial = json.loads(payload)["motivation_states"][0]
    for version in range(2, 5):
        payload = prepare(
            MindHead(uuid7(), version, payload),
            (assess("ctx:2", basis_refs=("ctx:1", "ctx:2")),),
            {
                "ctx:1": basis(),
                "ctx:2": replace(
                    basis(UUID(initial["motivation_id"]), "current_motivation"),
                    ordinal=2,
                ),
            },
        )
        records = json.loads(payload)["motivation_states"]
        assert len(records) == 1
        assert records[0]["motivation_id"] == initial["motivation_id"]
        assert records[0]["object_id"] == initial["object_id"]
        assert records[0]["basis_ordinals"] == [1, 2]


def test_invalid_reference_duplicate_and_text_replacement_are_rejected():
    head = MindHead(uuid7(), 1, initial_mind_state())
    with pytest.raises(MindViolation, match="MIND-REFERENCE"):
        prepare(head, (assess(),), {})
    with pytest.raises(MindViolation, match="MIND-MOTIVATION-DUPLICATE"):
        prepare(head, (assess(), assess()), {"ctx:1": basis()})
    for version in range(1, 5):
        head = MindHead(
            uuid7(), version + 1, prepare(head, (assess(),), {"ctx:1": basis()})
        )
    before = head.canonical_state
    draft = CandidateMindDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        head.version,
        initial_mind_state(),
    )
    with pytest.raises(MindViolation, match="MIND-MOTIVATION-REPLACEMENT"):
        prepare_mind_change(head, draft, now=NOW, commit_id=uuid7())
    with pytest.raises(MindViolation, match="MIND-HEAD-STALE"):
        prepare_mind_change(
            head, replace(draft, expected_version=1), now=NOW, commit_id=uuid7()
        )
    assert before == head.canonical_state


@pytest.mark.parametrize("ending", ["satisfied", "released"])
def test_admin_text_and_empty_appraisal_cannot_clear_active_motivation(ending):
    head = MindHead(uuid7(), 1, initial_mind_state())
    payload = prepare(head, (assess(),), {"ctx:1": basis()})
    head = MindHead(uuid7(), 2, payload)
    editable = json.loads(mind_editable_state(payload))
    editable["thoughts"] = ["合成文字更新"]
    draft = CandidateMindDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        2,
        rfc8785.dumps(editable),
    )
    updated = prepare_mind_change(head, draft, now=NOW, commit_id=uuid7())
    assert (
        json.loads(updated)["motivation_states"]
        == json.loads(payload)["motivation_states"]
    )
    record = json.loads(payload)["motivation_states"][0]
    from uuid import UUID

    result = prepare(
        head,
        (assess(resolution=ending),),
        {"ctx:1": basis(UUID(record["motivation_id"]), "current_motivation")},
    )
    assert mind_signals(result) == ()
