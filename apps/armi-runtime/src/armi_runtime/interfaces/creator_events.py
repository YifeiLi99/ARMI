"""Bounded process-local broker for authenticated Creator SSE invalidations."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass

from armi_kernel.application import (
    CreatorEventViolation,
    CreatorProjectionInvalidation,
)

from .browser_sessions import BrowserSessionStore, BrowserSessionViolation

REPLAY_CAPACITY = 256
SUBSCRIBER_CAPACITY = 64
MAX_EVENT_BYTES = 4096
KEEPALIVE_SECONDS = 15
RETRY_MILLISECONDS = 1000
EVENT_KINDS = {
    "activity": "activity.invalidated",
    "memory": "memory.invalidated",
    "maintenance": "maintenance.invalidated",
    "material": "material.invalidated",
    "relationship": "relationship.invalidated",
    "scene_timeline": "scene.timeline.invalidated",
    "capability_request": "capability.request.invalidated",
    "operation": "operation.invalidated",
    "other_human_record": "other_human.record.invalidated",
    "effect": "effect.invalidated",
    "subject_summary": "subject.summary.invalidated",
    "data_rights": "data.rights.invalidated",
}
_EVENT_ID = re.compile(
    r"^sse-v1\.([A-Za-z0-9_-]{22})\.([1-9][0-9]*)$",
    re.ASCII,
)
_CLOSED = object()

DiagnosticEvent = Callable[[str], None]


class CreatorEventBrokerViolation(RuntimeError):
    """Transport-local failure with a stable safe code and HTTP status."""

    __slots__ = ("code", "status_code")

    def __init__(self, code: str, *, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__("creator event stream failed")

    def __str__(self) -> str:
        return f"{self.code}: creator event stream failed"


@dataclass(frozen=True, slots=True)
class PublishedCreatorEvent:
    event_id: str
    event_kind: str
    data: bytes
    frame: bytes
    sequence: int


class CreatorEventSubscription:
    __slots__ = ("_broker", "_closed", "_queue", "replay")

    def __init__(
        self,
        broker: CreatorEventBroker,
        replay: tuple[PublishedCreatorEvent, ...],
        queue: asyncio.Queue[PublishedCreatorEvent | object],
    ) -> None:
        self._broker = broker
        self._closed = False
        self._queue = queue
        self.replay = replay

    async def receive(self) -> PublishedCreatorEvent | None:
        item = await self._queue.get()
        return None if item is _CLOSED else item  # type: ignore[return-value]

    def enqueue(self, event: PublishedCreatorEvent) -> bool:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.terminate()
            return False
        return True

    def terminate(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(_CLOSED)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._broker.unsubscribe(self)


class CreatorEventBroker:
    """Assign event IDs and retain a bounded replay window for one session."""

    __slots__ = (
        "_diagnostic",
        "_epoch",
        "_lock",
        "_maximum_event_bytes",
        "_replay",
        "_sequence",
        "_subscriber",
        "_subscriber_capacity",
    )

    def __init__(
        self,
        *,
        diagnostic: DiagnosticEvent | None = None,
        epoch: bytes | None = None,
        replay_capacity: int = REPLAY_CAPACITY,
        subscriber_capacity: int = SUBSCRIBER_CAPACITY,
        maximum_event_bytes: int = MAX_EVENT_BYTES,
    ) -> None:
        raw_epoch = secrets.token_bytes(16) if epoch is None else epoch
        if type(raw_epoch) is not bytes or len(raw_epoch) != 16:
            raise ValueError("creator event epoch must contain 16 bytes")
        if (
            type(replay_capacity) is not int
            or replay_capacity < 1
            or type(subscriber_capacity) is not int
            or subscriber_capacity < 1
            or type(maximum_event_bytes) is not int
            or maximum_event_bytes < 1
        ):
            raise ValueError("creator event broker bounds must be positive")
        self._epoch = base64.urlsafe_b64encode(raw_epoch).rstrip(b"=").decode("ascii")
        self._replay: deque[PublishedCreatorEvent] = deque(maxlen=replay_capacity)
        self._subscriber_capacity = subscriber_capacity
        self._maximum_event_bytes = maximum_event_bytes
        self._sequence = 0
        self._subscriber: CreatorEventSubscription | None = None
        self._lock = asyncio.Lock()

        def ignore_diagnostic(_event: str) -> None:
            return None

        self._diagnostic: DiagnosticEvent = (
            diagnostic if diagnostic is not None else ignore_diagnostic
        )

    @property
    def epoch(self) -> str:
        return self._epoch

    async def notify(self, invalidation: CreatorProjectionInvalidation) -> None:
        if type(invalidation) is not CreatorProjectionInvalidation:
            raise CreatorEventViolation("CON-SSE-EVENT")
        async with self._lock:
            sequence = self._sequence + 1
            event_id = f"sse-v1.{self._epoch}.{sequence}"
            event_kind = EVENT_KINDS[invalidation.resource_kind.value]
            wire = {
                "contract_version": "1.0",
                "event_id": event_id,
                "event_kind": event_kind,
                "resource_kind": invalidation.resource_kind.value,
                "resource_ref": invalidation.resource_ref,
                "projection_version": invalidation.projection_version,
                "occurred_at": invalidation.occurred_at.to_wire(),
            }
            data = json.dumps(
                wire,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            frame = (
                f"id: {event_id}\nevent: {event_kind}\ndata: ".encode("ascii")
                + data
                + b"\n\n"
            )
            if len(frame) > self._maximum_event_bytes:
                raise CreatorEventBrokerViolation(
                    "SSE-EVENT-TOO-LARGE",
                    status_code=503,
                )
            event = PublishedCreatorEvent(
                event_id=event_id,
                event_kind=event_kind,
                data=data,
                frame=frame,
                sequence=sequence,
            )
            self._sequence = sequence
            self._replay.append(event)
            subscriber = self._subscriber
            if subscriber is not None and not subscriber.enqueue(event):
                self._subscriber = None
                self._diagnostic("creator.event_stream.slow_consumer")

    async def subscribe(
        self,
        last_event_id: str | None,
    ) -> CreatorEventSubscription:
        async with self._lock:
            replay = self._resolve_replay(last_event_id)
            if self._subscriber is not None:
                self._subscriber.terminate()
                self._diagnostic("creator.event_stream.replaced")
            queue: asyncio.Queue[PublishedCreatorEvent | object] = asyncio.Queue(
                maxsize=self._subscriber_capacity
            )
            subscription = CreatorEventSubscription(self, replay, queue)
            self._subscriber = subscription
            self._diagnostic("creator.event_stream.connected")
            return subscription

    async def unsubscribe(self, subscription: CreatorEventSubscription) -> None:
        async with self._lock:
            if self._subscriber is subscription:
                self._subscriber = None
                subscription.terminate()
                self._diagnostic("creator.event_stream.disconnected")

    async def close_active(self) -> None:
        async with self._lock:
            if self._subscriber is not None:
                self._subscriber.terminate()
                self._subscriber = None
                self._diagnostic("creator.event_stream.closed")

    def _resolve_replay(
        self,
        last_event_id: str | None,
    ) -> tuple[PublishedCreatorEvent, ...]:
        if last_event_id is None:
            return ()
        match = _EVENT_ID.fullmatch(last_event_id)
        if match is None:
            self._diagnostic("creator.event_stream.parser_failure")
            raise CreatorEventBrokerViolation(
                "INPUT_EVENT_ID_INVALID",
                status_code=400,
            )
        epoch, sequence_text = match.groups()
        sequence = int(sequence_text)
        if epoch != self._epoch or sequence > self._sequence:
            self._diagnostic("creator.event_stream.gap")
            raise CreatorEventBrokerViolation(
                "CONFLICT_EVENT_GAP",
                status_code=409,
            )
        earliest = self._replay[0].sequence if self._replay else self._sequence + 1
        if sequence < earliest - 1:
            self._diagnostic("creator.event_stream.gap")
            raise CreatorEventBrokerViolation(
                "CONFLICT_EVENT_GAP",
                status_code=409,
            )
        return tuple(event for event in self._replay if event.sequence > sequence)


def parse_last_event_id(
    raw_headers: Iterable[tuple[bytes, bytes]],
) -> str | None:
    values = [value for name, value in raw_headers if name.lower() == b"last-event-id"]
    if len(values) > 1:
        raise CreatorEventBrokerViolation(
            "INPUT_EVENT_ID_INVALID",
            status_code=400,
        )
    try:
        return values[0].decode("ascii") if values else None
    except UnicodeDecodeError:
        raise CreatorEventBrokerViolation(
            "INPUT_EVENT_ID_INVALID",
            status_code=400,
        ) from None


async def stream_creator_events(
    subscription: CreatorEventSubscription,
    *,
    sessions: BrowserSessionStore,
    token: str,
    diagnostic: DiagnosticEvent,
) -> AsyncIterator[bytes]:
    try:
        yield f"retry: {RETRY_MILLISECONDS}\n\n".encode("ascii")
        for replayed in subscription.replay:
            yield replayed.frame
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.receive(),
                    timeout=KEEPALIVE_SECONDS,
                )
            except TimeoutError:
                try:
                    sessions.verify(token)
                except BrowserSessionViolation:
                    diagnostic("creator.event_stream.session_expired")
                    return
                yield b": keepalive\n\n"
                continue
            if event is None:
                return
            yield event.frame
    finally:
        await subscription.close()


__all__ = (
    "EVENT_KINDS",
    "KEEPALIVE_SECONDS",
    "MAX_EVENT_BYTES",
    "REPLAY_CAPACITY",
    "RETRY_MILLISECONDS",
    "SUBSCRIBER_CAPACITY",
    "CreatorEventBroker",
    "CreatorEventBrokerViolation",
    "CreatorEventSubscription",
    "PublishedCreatorEvent",
    "parse_last_event_id",
    "stream_creator_events",
)
