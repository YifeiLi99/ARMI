"""Attention-owned thresholds and atomic decisions in isolated PostgreSQL."""

import os
from typing import Any
from unittest.mock import patch

import pytest
from armi_attention._autonomy_postgresql import PostgreSQLAutonomyOwner
from armi_attention._owner import PostgreSQLOpportunityOwner
from armi_attention.api import AutonomyPolicy, OpportunityAdmissionStatus
from armi_kernel.application import AutonomyCategory

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.test_group("mind", "attention", "runtime"),
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


@pytest.mark.parametrize("result", ["rest", "reflect", "unknown"])
def test_selection_settlement_does_not_replay_an_exhausted_cycle(result):
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()

    async def probe(fixture, born, ids, fence, lease):
        factory = support.PostgreSQLUnitOfWorkFactory(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
            pool_min=1,
            pool_max=2,
            acquire_timeout_seconds=2,
            statement_timeout_seconds=5,
            authority_admission=lambda: fence,
        )
        owner, policy = PostgreSQLAutonomyOwner(), AutonomyPolicy()
        await factory.open()
        try:
            async with factory.unit_of_work() as unit:
                tx = unit.transaction
                await owner.ensure_plan(tx, subject_id=born.subject_id, policy=policy)
                initial = await owner.activation_state(
                    tx,
                    subject_id=born.subject_id,
                    policy=policy,
                    idling=True,
                    need=0,
                    runtime_ref=str(fence.runtime_instance_id.value),
                )
                await tx.execute(
                    "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp(), activation=jsonb_set(activation,'{accumulated}','100') WHERE subject_id=%s",
                    (born.subject_id,),
                )
                admission = await owner.admit_due(
                    tx, subject_id=born.subject_id, policy=policy
                )
                assert admission.opportunity_id is not None
                await tx.execute(
                    "UPDATE armi.opportunities SET current_disposition='selected', selected_at=statement_timestamp() WHERE opportunity_id=%s",
                    (admission.opportunity_id,),
                )
                if result == "unknown":
                    assert await PostgreSQLOpportunityOwner().resolve_cognition_failure(
                        tx,
                        opportunity_id=admission.opportunity_id,
                        failure_code="MODEL-JEV-CHECK-UNDETERMINED",
                    )
                else:
                    await owner.commit_check(
                        tx,
                        opportunity_id=admission.opportunity_id,
                        episode_id=ids["episode"],
                        category=AutonomyCategory(result),
                        policy=policy,
                    )
                row = await (
                    await tx.execute(
                        "SELECT activation,last_direction,last_selection_result,opportunity_id FROM armi.autonomy_plans WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                ).fetchone()
                assert row is not None
                if result == "reflect":
                    assert row[3] is not None and row[3] != admission.opportunity_id
                    count = await (
                        await tx.execute(
                            "SELECT count(*) FROM armi.opportunities WHERE predecessor_opportunity_id=%s",
                            (admission.opportunity_id,),
                        )
                    ).fetchone()
                    assert count == (1,)
                    await PostgreSQLOpportunityOwner().interrupt_autonomy(
                        tx, subject_id=born.subject_id
                    )
                    row = await (
                        await tx.execute(
                            "SELECT activation,last_direction,last_selection_result,opportunity_id FROM armi.autonomy_plans WHERE subject_id=%s",
                            (born.subject_id,),
                        )
                    ).fetchone()
                    assert row is not None
                assert row[3] is None
                assert row[0]["cycle"] == initial.cycle + 1
                assert row[0]["accumulated"] == 0
                if result == "unknown":
                    assert row[1] is None
                    assert row[2] == "MODEL-JEV-CHECK-UNDETERMINED"
                    assert row[0]["retry_after"] >= row[0]["anchor_seconds"] + 60
                else:
                    assert row[1] == result
        finally:
            await factory.close()

    try:
        case._exercise_creator_reply(mood_probe=probe)
    finally:
        case.tearDownClass()


def test_persisted_cycle_selects_direction_before_cognition_and_rollback():
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()

    async def probe(fixture, born, ids, fence, lease):
        factory = support.PostgreSQLUnitOfWorkFactory(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
            pool_min=1,
            pool_max=2,
            acquire_timeout_seconds=2,
            statement_timeout_seconds=5,
            authority_admission=lambda: fence,
        )
        owner = PostgreSQLAutonomyOwner()
        policy = AutonomyPolicy(outlet="creator_web")

        async def delivered(_root):
            return "delivered"

        await factory.open()
        try:
            async with factory.unit_of_work(read_only=True) as unit:
                scene = await (
                    await unit.transaction.execute(
                        "SELECT scene_id,context_party_id FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                        (ids["episode"],),
                    )
                ).fetchone()
                assert scene is not None
            args: dict[str, Any] = dict(
                subject_id=born.subject_id,
                input_ref=None,
                target_ref=str(scene[1]),
                active_seconds=0.0,
                delivery_status=delivered,
            )
            with patch(
                "armi_attention._autonomy_postgresql.random", return_value=0.5
            ) as draw:
                async with factory.unit_of_work() as unit:
                    plan = await owner.ensure_plan(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    first = await owner.social_cycle(unit.transaction, **args)
                    assert first.threshold == 0.5
                async with factory.unit_of_work() as unit:
                    # New owner instance models process restart; no new random draw.
                    assert (
                        await PostgreSQLAutonomyOwner().social_cycle(
                            unit.transaction, **args
                        )
                        == first
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp() WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                    admission = await owner.admit_due(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        scene_id=scene[0],
                        creator_party_id=scene[1],
                        social_ready=True,
                    )
                    assert admission.status is OpportunityAdmissionStatus.ADMITTED
                    assert admission.opportunity_id is not None
                    duplicate = await owner.admit_due(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        social_ready=True,
                    )
                    assert duplicate.opportunity_id == admission.opportunity_id
                    row = await (
                        await unit.transaction.execute(
                            "SELECT purpose,root_opportunity_id FROM armi.opportunities WHERE opportunity_id=%s",
                            (admission.opportunity_id,),
                        )
                    ).fetchone()
                    assert row == ("consider_autonomy_check", admission.opportunity_id)
                    await unit.transaction.execute(
                        "UPDATE armi.opportunities SET current_disposition='selected', selected_at=statement_timestamp() WHERE opportunity_id=%s",
                        (admission.opportunity_id,),
                    )
                    await owner.commit_check(
                        unit.transaction,
                        opportunity_id=admission.opportunity_id,
                        episode_id=ids["episode"],
                        category=AutonomyCategory.CONNECT,
                        policy=policy,
                    )
                    plan = await owner.ensure_plan(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    execution_id = plan.opportunity_id
                    assert (
                        execution_id is not None
                        and execution_id != admission.opportunity_id
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.opportunities SET current_disposition='selected', selected_at=statement_timestamp() WHERE opportunity_id=%s",
                        (execution_id,),
                    )
                assert draw.call_count == 1
            assert admission.opportunity_id is not None
            with pytest.raises(RuntimeError, match="rollback"):
                async with factory.unit_of_work() as unit:
                    await owner.commit_social_decision(
                        unit.transaction,
                        subject_id=born.subject_id,
                        opportunity_id=execution_id,
                        decision=("defer", "wait until later"),
                    )
                    raise RuntimeError("rollback")
            async with factory.unit_of_work() as unit:
                unchanged = await owner.social_cycle(unit.transaction, **args)
                assert unchanged.phase == "cognition"
                await owner.commit_social_decision(
                    unit.transaction,
                    subject_id=born.subject_id,
                    opportunity_id=execution_id,
                    decision=("express", "seek companionship"),
                )
                await owner.commit_plan(
                    unit.transaction,
                    subject_id=born.subject_id,
                    expected_version=plan.version,
                    episode_id=ids["episode"],
                    opportunity_id=execution_id,
                    acted=True,
                    policy=policy,
                )
            async with factory.unit_of_work() as unit:
                waiting = await owner.social_cycle(unit.transaction, **args)
                assert waiting.phase == "waiting" and waiting.review_at == 7200
                assert waiting.unanswered == 1
        finally:
            await factory.close()

    try:
        case._exercise_creator_reply(mood_probe=probe)
    finally:
        case.tearDownClass()
