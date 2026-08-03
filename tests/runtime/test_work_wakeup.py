from __future__ import annotations

import asyncio

import pytest
from armi_runtime.composition.work_wakeup import (
    CANDIDATE_VALIDATE,
    CONTEXT_PREPARE,
    EFFECT_REGISTER,
    MODEL_INVOKE,
    OPPORTUNITY_AVAILABLE,
    RESPONSE_ADMIT,
    SUBJECT_COMMIT,
    WorkWakeupBus,
)


@pytest.mark.asyncio
async def test_notification_before_wait_is_not_lost() -> None:
    wakeups = WorkWakeupBus()
    stop = asyncio.Event()
    observed = wakeups.version(MODEL_INVOKE)

    wakeups.notify(MODEL_INVOKE)
    current = await wakeups.wait(
        MODEL_INVOKE,
        observed,
        stop=stop,
        timeout_seconds=10,
    )

    assert current == observed + 1


@pytest.mark.asyncio
async def test_notifications_are_channel_scoped_and_polling_remains_fallback() -> None:
    wakeups = WorkWakeupBus()
    stop = asyncio.Event()
    observed = wakeups.version(CANDIDATE_VALIDATE)
    wakeups.notify(MODEL_INVOKE)

    current = await wakeups.wait(
        CANDIDATE_VALIDATE,
        observed,
        stop=stop,
        timeout_seconds=0.01,
    )

    assert current == observed


@pytest.mark.asyncio
async def test_payload_free_pulses_wake_the_interactive_chain_immediately() -> None:
    wakeups = WorkWakeupBus()
    stop = asyncio.Event()
    channels = (
        OPPORTUNITY_AVAILABLE,
        CONTEXT_PREPARE,
        MODEL_INVOKE,
        CANDIDATE_VALIDATE,
        SUBJECT_COMMIT,
        RESPONSE_ADMIT,
        EFFECT_REGISTER,
    )
    completed: list[str] = []

    async def stage(channel: str, downstream: str | None) -> None:
        observed = wakeups.version(channel)
        await wakeups.wait(
            channel,
            observed,
            stop=stop,
            timeout_seconds=10,
        )
        completed.append(channel)
        if downstream is not None:
            wakeups.notify(downstream)

    tasks = tuple(
        asyncio.create_task(stage(channel, downstream))
        for channel, downstream in zip(channels, (*channels[1:], None), strict=True)
    )
    await asyncio.sleep(0)
    wakeups.notify(OPPORTUNITY_AVAILABLE)
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.5)

    assert completed == list(channels)


@pytest.mark.asyncio
async def test_stop_releases_waiters_without_a_business_notification() -> None:
    wakeups = WorkWakeupBus()
    stop = asyncio.Event()
    observed = wakeups.version(RESPONSE_ADMIT)
    waiter = asyncio.create_task(
        wakeups.wait(
            RESPONSE_ADMIT,
            observed,
            stop=stop,
            timeout_seconds=10,
        )
    )
    await asyncio.sleep(0)

    stop.set()

    assert await asyncio.wait_for(waiter, timeout=0.5) == observed


def test_wakeup_channel_must_be_safe_ascii() -> None:
    wakeups = WorkWakeupBus()

    with pytest.raises(ValueError, match="non-empty ASCII"):
        wakeups.notify("")
    with pytest.raises(ValueError, match="non-empty ASCII"):
        wakeups.notify("认知")
