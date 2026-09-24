from random import Random

import pytest
from armi_attention._social_cycle import SocialCycle


def test_one_draw_survives_reads_and_restart_and_focus_only_changes_readiness():
    rng = Random(7)
    cycle = SocialCycle.begin(rng.random)
    state = rng.getstate()
    for _ in range(100):
        assert not cycle.ready(drive=cycle.threshold, active_seconds=0.0, focused=True)
        assert cycle.ready(drive=cycle.threshold, active_seconds=0.0, focused=False)
    assert rng.getstate() == state
    assert SocialCycle.model_validate_json(cycle.model_dump_json()) == cycle


def test_delivery_and_progressive_wait_never_mean_satisfaction():
    cycle = SocialCycle.begin(Random(7).random)
    now = 0.0
    for hours in (2, 4, 8, 16, 24, 24):
        cycle = cycle.model_copy(update={"phase": "cognition"})
        cycle = cycle.decided(
            outcome="express",
            reason="seek contact",
            episode_ref="source",
            active_seconds=now,
        )
        assert not cycle.ready(drive=1.0, active_seconds=now + 999999, focused=False)
        cycle = cycle.delivered(active_seconds=now)
        assert cycle.review_at == now + hours * 3600
        assert not cycle.ready(
            drive=1.0, active_seconds=cycle.review_at - 1, focused=False
        )
        now = cycle.review_at
    reset = SocialCycle.begin(Random(8).random, input_ref="new response")
    assert reset.unanswered == 0


@pytest.mark.parametrize(("outcome", "delay"), [("defer", 3600), ("release", 14400)])
def test_cognition_can_explain_a_postponement(outcome, delay):
    cycle = SocialCycle.begin(lambda: 0.5).model_copy(update={"phase": "cognition"})
    decided = cycle.decided(
        outcome=outcome,
        reason="current circumstances",
        episode_ref="source",
        active_seconds=20.0,
    )
    assert decided.review_at == 20 + delay
    assert not decided.ready(drive=1.0, active_seconds=20.0, focused=False)
    failed = cycle.interrupted(active_seconds=20.0, reason="unknown")
    assert failed.unanswered == 0
    assert failed.reason == "unknown"
