from datetime import UTC, datetime, timedelta

import pytest
from armi_live_vision.api import (
    CameraFrame,
    LatestFrameBuffer,
    LiveVisionViolation,
    ObservationBudget,
    ObservationTrigger,
    StableSceneChangeDetector,
    TriggerCoalescer,
)


def test_latest_frame_buffer_keeps_only_latest() -> None:
    buffer = LatestFrameBuffer()
    first = CameraFrame(datetime.now(UTC), b"one", 1, 1)
    second = CameraFrame(datetime.now(UTC), b"two", 1, 1)
    buffer.put(first)
    buffer.put(second)
    assert buffer.latest() is second
    buffer.clear()
    assert buffer.latest() is None


def test_scene_change_requires_three_consecutive_samples() -> None:
    detector = StableSceneChangeDetector(threshold=0.2)
    assert detector.sample(0.3) is False
    assert detector.sample(0.1) is False
    assert detector.sample(0.3) is False
    assert detector.sample(0.4) is False
    assert detector.sample(0.5) is True
    assert detector.sample(0.5) is False


def test_manual_bypasses_cooldown_but_not_hourly_limit() -> None:
    budget = ObservationBudget(hourly_limit=2, automatic_cooldown=timedelta(seconds=30))
    now = datetime.now(UTC)
    budget.record(ObservationTrigger.INITIAL, now)
    assert (
        budget.allow(ObservationTrigger.SCENE_CHANGE, now + timedelta(seconds=10))
        is False
    )
    assert budget.allow(ObservationTrigger.MANUAL, now + timedelta(seconds=10)) is True
    budget.record(ObservationTrigger.MANUAL, now + timedelta(seconds=10))
    assert budget.allow(ObservationTrigger.MANUAL, now + timedelta(seconds=20)) is False
    with pytest.raises(LiveVisionViolation, match="rate limited"):
        budget.record(ObservationTrigger.MANUAL, now + timedelta(seconds=20))
    assert budget.allow(
        ObservationTrigger.PERIODIC_REFRESH, now + timedelta(hours=1, seconds=1)
    )


def test_in_flight_triggers_coalesce_to_latest() -> None:
    coalescer = TriggerCoalescer()
    assert coalescer.request(ObservationTrigger.INITIAL)
    assert not coalescer.request(ObservationTrigger.SCENE_CHANGE, 0.3)
    assert not coalescer.request(ObservationTrigger.MANUAL)
    assert coalescer.settle() == (ObservationTrigger.MANUAL, None)
    assert coalescer.settle() is None
