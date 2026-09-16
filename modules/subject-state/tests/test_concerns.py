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
        concern_attention_status(records, as_of=now, consumed_before=None)[0][
            "condition_state"
        ]
        == "scheduled"
    )
    later = now + timedelta(hours=6)
    due = concern_attention_status(records, as_of=later, consumed_before=None)
    assert due[0]["condition_state"] == "due"
    assert concern_attention_status(records, as_of=later, consumed_before=None) == due
    assert (
        concern_attention_status(records, as_of=later, consumed_before=later)[0][
            "condition_state"
        ]
        == "consumed"
    )
    assert records[0].state == "open"
