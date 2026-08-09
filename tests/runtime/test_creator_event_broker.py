"""CON-SSE replay, gap, replacement, and queue-boundary checks."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from armi_kernel.application import (
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
)
from armi_kernel.contracts import Instant
from armi_runtime.interfaces.creator_events import (
    CreatorEventBroker,
    CreatorEventBrokerViolation,
)


def invalidation(scene_key: str = "default") -> CreatorProjectionInvalidation:
    return CreatorProjectionInvalidation(
        resource_kind=CreatorEventResourceKind.SCENE_TIMELINE,
        resource_ref=scene_key,
        occurred_at=Instant(datetime(2026, 7, 30, 12, 0, tzinfo=UTC)),
        projection_version="scene-timeline.v5",
    )


class CreatorEventBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ids_are_monotonic_and_replay_is_exact(self) -> None:
        broker = CreatorEventBroker(epoch=b"\x01" * 16)
        await broker.notify(invalidation())
        await broker.notify(invalidation())
        first_id = f"sse-v1.{broker.epoch}.1"
        subscription = await broker.subscribe(first_id)

        self.assertEqual(
            tuple(event.sequence for event in subscription.replay),
            (2,),
        )
        self.assertEqual(subscription.replay[0].event_id, f"sse-v1.{broker.epoch}.2")
        self.assertIn(b'"resource_ref":"default"', subscription.replay[0].data)
        self.assertIn(
            f"id: sse-v1.{broker.epoch}.2\n".encode(),
            subscription.replay[0].frame,
        )
        await subscription.close()

    async def test_invalid_ahead_epoch_and_ring_gap_are_distinct(self) -> None:
        broker = CreatorEventBroker(epoch=b"\x02" * 16, replay_capacity=2)
        for _index in range(4):
            await broker.notify(invalidation())

        with self.assertRaisesRegex(
            CreatorEventBrokerViolation,
            "INPUT_EVENT_ID_INVALID",
        ):
            await broker.subscribe("invalid")
        with self.assertRaisesRegex(
            CreatorEventBrokerViolation,
            "INPUT_EVENT_ID_INVALID",
        ):
            await broker.subscribe(f"sse-v1.{broker.epoch}.0")
        for event_id in (
            f"sse-v1.{broker.epoch}.5",
            f"sse-v1.{'A' * 22}.4",
            f"sse-v1.{broker.epoch}.1",
        ):
            with self.subTest(event_id=event_id):
                with self.assertRaises(CreatorEventBrokerViolation) as context:
                    await broker.subscribe(event_id)
                self.assertEqual(context.exception.status_code, 409)
                self.assertEqual(context.exception.code, "CONFLICT_EVENT_GAP")

    async def test_new_subscription_closes_the_old_one(self) -> None:
        broker = CreatorEventBroker(epoch=b"\x03" * 16)
        first = await broker.subscribe(None)
        second = await broker.subscribe(None)
        self.assertIsNone(await asyncio.wait_for(first.receive(), timeout=0.1))
        await broker.notify(invalidation())
        current = await asyncio.wait_for(second.receive(), timeout=0.1)
        assert current is not None
        self.assertEqual(current.sequence, 1)
        await second.close()

    async def test_slow_subscriber_is_closed_without_blocking_publisher(self) -> None:
        broker = CreatorEventBroker(
            epoch=b"\x04" * 16,
            subscriber_capacity=1,
        )
        subscription = await broker.subscribe(None)
        await broker.notify(invalidation())
        await broker.notify(invalidation())
        self.assertIsNone(await asyncio.wait_for(subscription.receive(), timeout=0.1))

    async def test_event_size_is_enforced_before_publish(self) -> None:
        broker = CreatorEventBroker(
            epoch=b"\x05" * 16,
            maximum_event_bytes=32,
        )
        with self.assertRaisesRegex(
            CreatorEventBrokerViolation,
            "SSE-EVENT-TOO-LARGE",
        ):
            await broker.notify(invalidation())
        subscription = await broker.subscribe(None)
        self.assertEqual(subscription.replay, ())
        await subscription.close()


if __name__ == "__main__":
    unittest.main()
