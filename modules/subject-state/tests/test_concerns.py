from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_subject_state._concerns import apply_concern_changes
from armi_subject_state.api import (
    CloseConcern,
    CreateConcern,
    TimedReview,
    UpdateConcern,
    concern_attention_status,
)


def creation(question: str = "为什么叶片朝光转动") -> CreateConcern:
    return CreateConcern(
        operation="create",
        question=question,
        reason="我对观察到的变化有兴趣",
        resolution_condition="能解释朝向改变的原因",
        understanding="目前只观察到朝向改变",
        state="open",
        review=TimedReview(kind="review", after_seconds=300, reason="稍后比较已有资料"),
        basis_refs=("ctx:1",),
    )


def test_concern_survives_elapsed_time_and_can_finish_without_recreation() -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    commit = uuid7()
    records = apply_concern_changes(
        (), (creation(),), now=now, commit_id=commit, basis_ordinals=(1,)
    )
    concern = records[0]
    assert concern.created_at == now
    assert concern.review_at == now + timedelta(minutes=5)
    unchanged = apply_concern_changes(
        records,
        (),
        now=now + timedelta(hours=6),
        commit_id=uuid7(),
        basis_ordinals=(1,),
    )
    assert unchanged == records
    close = CloseConcern(
        operation="resolve",
        concern_ref=str(concern.concern_id),
        conclusion="资料解释了向光生长的机制",
        basis_refs=("ctx:2",),
    )
    finished = apply_concern_changes(
        records,
        (close,),
        now=now + timedelta(hours=6),
        commit_id=uuid7(),
        basis_ordinals=(1, 2),
    )
    assert finished[0].state == "resolved"
    assert finished[0].review is None
    assert (
        apply_concern_changes(
            finished, (), now=now, commit_id=uuid7(), basis_ordinals=(1,)
        )
        == ()
    )


def test_capacity_and_reference_fail_as_one_change() -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    records = apply_concern_changes(
        (),
        tuple(creation(str(i)) for i in range(4)),
        now=now,
        commit_id=uuid7(),
        basis_ordinals=(1,),
    )
    with pytest.raises(ValueError, match="CAPACITY"):
        apply_concern_changes(
            records,
            (creation("第五个问题"),),
            now=now,
            commit_id=uuid7(),
            basis_ordinals=(1,),
        )
    invalid = CloseConcern(
        operation="release",
        concern_ref=str(uuid7()),
        conclusion="不再关注",
        basis_refs=("ctx:1",),
    )
    with pytest.raises(ValueError, match="REFERENCE"):
        apply_concern_changes(
            records, (invalid,), now=now, commit_id=uuid7(), basis_ordinals=(1,)
        )
    assert len(records) == 4


def test_wait_changes_the_condition_instead_of_sliding_it_on_reads() -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    records = apply_concern_changes(
        (), (creation(),), now=now, commit_id=uuid7(), basis_ordinals=(1,)
    )
    update = UpdateConcern(
        **{
            **creation().model_dump(),
            "operation": "update",
            "concern_ref": str(records[0].concern_id),
            "state": "waiting",
            "review": TimedReview(
                kind="review", after_seconds=3600, reason="目前没有新资料; 稍后重新判断"
            ),
        }
    )
    updated = apply_concern_changes(
        records,
        (update,),
        now=now + timedelta(minutes=5),
        commit_id=uuid7(),
        basis_ordinals=(1,),
    )
    assert updated[0].created_at == now
    assert updated[0].review_at == now + timedelta(minutes=65)


def test_attention_projection_reports_time_without_mutating_the_concern() -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    records = apply_concern_changes(
        (), (creation(),), now=now, commit_id=uuid7(), basis_ordinals=(1,)
    )
    assert (
        concern_attention_status(records, as_of=now, consumed=frozenset())[0][
            "condition_state"
        ]
        == "scheduled"
    )
    later = now + timedelta(hours=6)
    due = concern_attention_status(records, as_of=later, consumed=frozenset())
    assert due[0]["condition_state"] == "due"
    assert concern_attention_status(records, as_of=later, consumed=frozenset()) == due
    assert (
        concern_attention_status(
            records,
            as_of=later,
            consumed=frozenset(
                {("mind", str(records[0].concern_id), str(records[0].source_commit_id))}
            ),
        )[0]["condition_state"]
        == "consumed"
    )
    assert records[0].state == "open"


def test_owner_signals_keep_condition_identity_across_time_and_exclude_own_activity_round():
    from armi_subject_state._concerns import concern_signals

    now = datetime(2026, 9, 17, tzinfo=UTC)
    records = apply_concern_changes(
        (), (creation(),), now=now, commit_id=uuid7(), basis_ordinals=(1,)
    )
    assert concern_signals(()) == ()
    signals = concern_signals(records)
    assert signals == concern_signals(records)
    assert signals[0].condition_version == str(records[0].source_commit_id)
    closed = apply_concern_changes(
        records,
        (
            CloseConcern(
                operation="release",
                concern_ref=str(records[0].concern_id),
                conclusion="No further investment is worthwhile",
                basis_refs=("ctx:1",),
            ),
        ),
        now=now + timedelta(minutes=10),
        commit_id=uuid7(),
        basis_ordinals=(1,),
    )
    assert concern_signals(closed) == ()


def test_event_review_requires_new_creator_input_or_related_result_and_preserves_waiting():
    from armi_subject_state._concerns import concern_signals
    from armi_subject_state.api import ActivityReview, CreatorInputReview

    now = datetime(2026, 9, 17, tzinfo=UTC)
    records = apply_concern_changes(
        (),
        (
            creation().model_copy(
                update={
                    "review": CreatorInputReview(
                        kind="creator_input", reason="Ask when a new clue arrives"
                    )
                }
            ),
        ),
        now=now,
        commit_id=uuid7(),
        basis_ordinals=(1,),
    )
    event_ref = uuid7()
    assert (
        concern_signals(
            records,
            event_purpose="consider_creator_input",
            event_ref=event_ref,
            event_at=now,
        )
        == ()
    )
    event = concern_signals(
        records,
        event_purpose="consider_creator_input",
        event_ref=event_ref,
        event_at=now + timedelta(seconds=1),
    )
    assert event[0].reason == "creator_input"
    assert records[0].understanding == creation().understanding
    activity = uuid7()
    waiting = (
        records[0].model_copy(
            update={
                "review": ActivityReview(
                    kind="activity_result",
                    activity_ref=str(activity),
                    reason="Await evidence",
                ),
                "state": "waiting",
            }
        ),
    )
    assert (
        concern_signals(
            waiting,
            event_purpose="consider_autonomous_life",
            event_ref=event_ref,
            event_at=now + timedelta(seconds=1),
            activity_id=activity,
        )
        == ()
    )
    assert (
        concern_signals(
            waiting,
            event_purpose="consider_codex_result",
            event_ref=event_ref,
            event_at=now + timedelta(seconds=1),
            activity_id=uuid7(),
        )
        == ()
    )
    result = concern_signals(
        waiting,
        event_purpose="consider_codex_result",
        event_ref=event_ref,
        event_at=now + timedelta(seconds=1),
        activity_id=activity,
    )
    assert result[0].reason == "activity_result"
    assert waiting[0].state == "waiting"
    assert waiting[0].understanding == records[0].understanding


def test_scripted_curiosity_asks_waits_and_resolves_only_after_feedback():
    """Scripted owner candidates verify the mechanism, not model behavior."""
    from armi_subject_state._concerns import concern_signals
    from armi_subject_state.api import CreatorInputReview

    now = datetime(2026, 9, 17, tzinfo=UTC)
    records = apply_concern_changes(
        (), (creation(),), now=now, commit_id=uuid7(), basis_ordinals=(1,)
    )
    concern_id = records[0].concern_id
    # Asking and delivery do not supply knowledge. The next candidate keeps the
    # original understanding and waits for a new Creator input.
    wait = UpdateConcern(
        **{
            **creation().model_dump(),
            "operation": "update",
            "concern_ref": str(concern_id),
            "state": "waiting",
            "review": CreatorInputReview(
                kind="creator_input", reason="已询问叶片变化; 等待新的观察反馈"
            ),
        }
    )
    waiting = apply_concern_changes(
        records,
        (wait,),
        now=now + timedelta(minutes=5),
        commit_id=uuid7(),
        basis_ordinals=(1, 2),
    )
    assert waiting[0].understanding == records[0].understanding
    assert concern_signals(waiting) == ()
    feedback = concern_signals(
        waiting,
        event_purpose="consider_creator_input",
        event_ref=uuid7(),
        event_at=now + timedelta(hours=1),
    )
    assert feedback[0].object_ref == concern_id
    assert waiting[0].state == "waiting"
    resolved = apply_concern_changes(
        waiting,
        (
            CloseConcern(
                operation="resolve",
                concern_ref=str(concern_id),
                conclusion="反馈说明叶柄两侧生长不均使叶片朝光; 满足解释朝向变化的条件",
                basis_refs=("ctx:3",),
            ),
        ),
        now=now + timedelta(hours=1),
        commit_id=uuid7(),
        basis_ordinals=(1, 3),
    )
    assert resolved[0].concern_id == concern_id
    assert resolved[0].state == "resolved"
    assert concern_signals(resolved) == ()
