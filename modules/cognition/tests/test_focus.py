import json
from datetime import UTC, datetime
from uuid import uuid7

import pytest
import rfc8785
from armi_cognition._focus.api import (
    CandidateFocusDraft,
    CloseConcern,
    CreateConcern,
    FocusHead,
    FocusViolation,
    TimedReview,
    focus_editable_state,
    focus_signals,
    initial_focus_state,
    prepare_focus_change,
)
from armi_cognition.bootstrap import bootstrap_focus_cognition
from armi_kernel.application import CandidateFactClass


def test_focus_owner_draft_round_trip() -> None:
    draft = CandidateFocusDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        1,
        rfc8785.dumps(
            {
                "schema_kind": "armi.focus",
                "concerns": [],
            }
        ),
    )
    cognition = bootstrap_focus_cognition()
    owner = cognition.bind(draft)
    assert owner.owner == "focus"
    assert cognition.decode(owner.canonical_payload) == draft


def test_public_transition_protects_concerns_and_rejects_stale_or_invalid_refs():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    head = FocusHead(uuid7(), 1, initial_focus_state())

    def draft(state, version=1, changes=()):
        return CandidateFocusDraft(
            "proposal:1",
            "group:1",
            (1,),
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            version,
            rfc8785.dumps(json.loads(state)),
            changes,
        )

    created = prepare_focus_change(
        head,
        draft(
            head.canonical_state,
            changes=(
                CreateConcern(
                    operation="create",
                    question="合成问题",
                    reason="已有观察",
                    resolution_condition="解释观察",
                    understanding="没有答案",
                    state="waiting",
                    review=TimedReview(
                        kind="review", after_seconds=60, reason="稍后再考虑"
                    ),
                    basis_refs=("ctx:1",),
                ),
            ),
        ),
        now=now,
        commit_id=uuid7(),
    )
    current = FocusHead(uuid7(), 2, created)
    from armi_cognition._focus._admin import _validate_correction_provenance

    corrected = json.loads(created)
    corrected["concerns"][0]["understanding"] = "管理员校正的认识"
    _validate_correction_provenance(json.loads(created), corrected)
    corrected["concerns"][0]["source_commit_id"] = str(uuid7())
    with pytest.raises(FocusViolation, match="FOCUS-CORRECTION-PROVENANCE"):
        _validate_correction_provenance(json.loads(created), corrected)
    with pytest.raises(FocusViolation, match="FOCUS-HEAD-STALE"):
        prepare_focus_change(
            current, draft(head.canonical_state), now=now, commit_id=uuid7()
        )
    with pytest.raises(FocusViolation, match="FOCUS-REPLACEMENT-FORBIDDEN"):
        prepare_focus_change(
            current, draft(head.canonical_state, 2), now=now, commit_id=uuid7()
        )
    for ref in ("not-an-identity", str(uuid7())):
        with pytest.raises(FocusViolation, match="FOCUS-CONCERN-REFERENCE"):
            prepare_focus_change(
                current,
                draft(
                    focus_editable_state(created),
                    2,
                    (
                        CloseConcern(
                            operation="resolve",
                            concern_ref=ref,
                            conclusion="无效引用",
                            basis_refs=("ctx:1",),
                        ),
                    ),
                ),
                now=now,
                commit_id=uuid7(),
            )
    # A failed tool has not answered the question. No change preserves the concern.
    unchanged = prepare_focus_change(
        current, draft(focus_editable_state(created), 2), now=now, commit_id=uuid7()
    )
    assert json.loads(unchanged)["concerns"] == json.loads(created)["concerns"]
    concern_id = json.loads(created)["concerns"][0]["concern_id"]
    released = prepare_focus_change(
        current,
        draft(
            focus_editable_state(created),
            2,
            (
                CloseConcern(
                    operation="release",
                    concern_ref=concern_id,
                    conclusion="没有新信息,决定停止投入",
                    basis_refs=("ctx:1",),
                ),
            ),
        ),
        now=now,
        commit_id=uuid7(),
    )
    assert focus_signals(released) == ()
    assert json.loads(released)["concerns"][0]["state"] == "released"
    assert current.canonical_state == created
