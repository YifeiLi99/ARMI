import json
from datetime import UTC, datetime
from uuid import uuid7

import pytest
import rfc8785
from armi_kernel.application import CandidateFactClass
from armi_mind.api import (
    CandidateMindDraft,
    CloseConcern,
    CreateConcern,
    MindHead,
    MindViolation,
    TimedReview,
    initial_mind_state,
    mind_editable_state,
    mind_signals,
    prepare_mind_change,
)
from armi_mind.bootstrap import bootstrap_mind_cognition


def test_mind_owner_draft_round_trip() -> None:
    draft = CandidateMindDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        1,
        rfc8785.dumps(
            {
                "schema_kind": "armi.mind",
                "understanding": [],
                "attention": [],
                "thoughts": [],
                "wishes": [],
                "motivations": [],
            }
        ),
    )
    cognition = bootstrap_mind_cognition()
    owner = cognition.bind(draft)
    assert owner.owner == "mind"
    assert cognition.decode(owner.canonical_payload) == draft


def test_public_transition_protects_concerns_and_rejects_stale_or_invalid_refs():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    head = MindHead(uuid7(), 1, initial_mind_state())

    def draft(state, version=1, changes=()):
        return CandidateMindDraft(
            "proposal:1",
            "group:1",
            (1,),
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            version,
            rfc8785.dumps(json.loads(state)),
            changes,
        )

    created = prepare_mind_change(
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
    current = MindHead(uuid7(), 2, created)
    with pytest.raises(MindViolation, match="MIND-HEAD-STALE"):
        prepare_mind_change(
            current, draft(head.canonical_state), now=now, commit_id=uuid7()
        )
    with pytest.raises(MindViolation, match="MIND-CONCERN-REPLACEMENT"):
        prepare_mind_change(
            current, draft(head.canonical_state, 2), now=now, commit_id=uuid7()
        )
    for ref in ("not-an-identity", str(uuid7())):
        with pytest.raises(MindViolation, match="MIND-CONCERN-REFERENCE"):
            prepare_mind_change(
                current,
                draft(
                    mind_editable_state(created),
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
    unchanged = prepare_mind_change(
        current, draft(mind_editable_state(created), 2), now=now, commit_id=uuid7()
    )
    assert json.loads(unchanged)["concerns"] == json.loads(created)["concerns"]
    concern_id = json.loads(created)["concerns"][0]["concern_id"]
    released = prepare_mind_change(
        current,
        draft(
            mind_editable_state(created),
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
    assert mind_signals(released) == ()
    assert json.loads(released)["concerns"][0]["state"] == "released"
    assert current.canonical_state == created
