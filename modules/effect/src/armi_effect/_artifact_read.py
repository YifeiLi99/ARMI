"""Bounded reuse of verified Creator deliverables, never of access decisions."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from armi_kernel.application import ArtifactRef, RuntimeFence
from armi_kernel.contracts import Digest

from .api import (
    EffectArtifactContent,
    EffectArtifactKind,
    EffectArtifactStorePort,
    EffectId,
    EffectViolation,
)

_MAX_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 32
_IDLE_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ArtifactReadIdentity:
    runtime: RuntimeFence
    creator: UUID
    effect: EffectId
    kind: EffectArtifactKind
    source: ArtifactRef


@dataclass(slots=True)
class _Entry:
    content: EffectArtifactContent
    expiry: asyncio.TimerHandle


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError(value)


def project_artifact(
    kind: EffectArtifactKind, source: ArtifactRef, content: bytes
) -> EffectArtifactContent:
    try:
        decoded = content.decode("utf-8", errors="strict")
        if kind is not EffectArtifactKind.FINAL_RESULT:
            return EffectArtifactContent(
                kind, source.media_type, content, source.content_digest
            )
        value: object = json.loads(
            decoded, object_pairs_hook=_object_pairs, parse_constant=_invalid_constant
        )
        if type(value) is not dict:
            raise ValueError
        document = cast(dict[str, object], value)
        if set(document) != {
            "summary",
            "changed_paths",
            "deliverable",
        }:
            raise ValueError
        deliverable = document["deliverable"]
        if type(deliverable) is not str or not deliverable.strip():
            raise ValueError
        projected = deliverable.encode("utf-8", errors="strict")
        if len(projected) > 1024 * 1024:
            raise ValueError
        return EffectArtifactContent(
            kind, "text/plain", projected, Digest.from_bytes(projected)
        )
    except UnicodeError, ValueError:
        raise EffectViolation("EFFECT-ARTIFACT-INTEGRITY") from None


class CreatorArtifactReader:
    def __init__(self, storage: EffectArtifactStorePort) -> None:
        self._storage = storage
        self._entries: OrderedDict[ArtifactReadIdentity, _Entry] = OrderedDict()
        self._bytes = 0
        self._loading = asyncio.Lock()
        self._runtime: RuntimeFence | None = None
        self._closed = False

    def clear(self) -> None:
        for entry in self._entries.values():
            entry.expiry.cancel()
        self._entries.clear()
        self._bytes = 0

    def close(self) -> None:
        self._closed = True
        self.clear()

    async def wait_closed(self) -> None:
        async with self._loading:
            pass

    def invalidate(
        self, creator: UUID, effect: EffectId, kind: EffectArtifactKind
    ) -> None:
        for key in tuple(self._entries):
            if (key.creator, key.effect, key.kind) == (creator, effect, kind):
                self._remove(key)

    def _remove(self, key: ArtifactReadIdentity) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            entry.expiry.cancel()
            self._bytes -= len(entry.content.content)

    def _lookup(self, key: ArtifactReadIdentity) -> EffectArtifactContent | None:
        if self._closed:
            raise EffectViolation("EFFECT-RUNTIME-STALE")
        if key.runtime != self._runtime:
            self.clear()
            self._runtime = key.runtime
        for previous in tuple(self._entries):
            if (previous.creator, previous.effect, previous.kind) == (
                key.creator,
                key.effect,
                key.kind,
            ) and previous != key:
                self._remove(previous)
        entry = self._entries.get(key)
        if entry is None:
            return None
        loop = asyncio.get_running_loop()
        if entry.expiry.when() <= loop.time():
            self._remove(key)
            return None
        entry.expiry.cancel()
        entry.expiry = loop.call_later(_IDLE_SECONDS, self._remove, key)
        self._entries.move_to_end(key)
        return entry.content

    async def read(
        self, snapshot: Callable[[], Awaitable[ArtifactReadIdentity]]
    ) -> EffectArtifactContent:
        key = await snapshot()
        cached = self._lookup(key)
        if cached is not None:
            return cached
        waited = self._loading.locked()
        async with self._loading:
            if waited:
                # The wait may cross another load, deletion or a Runtime change.
                key = await snapshot()
                cached = self._lookup(key)
                if cached is not None:
                    return cached
            task = asyncio.create_task(self._load(key))
            try:
                content = await asyncio.shield(task)
            except asyncio.CancelledError:
                # A filesystem thread cannot be cancelled. Finish and close its
                # handle before releasing the load lock/custody, without caching.
                while not task.done():
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await asyncio.shield(task)
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    task.result()
                raise
            current = await snapshot()
            if self._closed or current != key:
                self.invalidate(key.creator, key.effect, key.kind)
                if current.runtime != key.runtime:
                    self.clear()
                raise EffectViolation("EFFECT-ARTIFACT-CHANGED")
            while self._entries and (
                self._bytes + len(content.content) > _MAX_BYTES
                or len(self._entries) >= _MAX_ENTRIES
            ):
                self._remove(next(iter(self._entries)))
            self._entries[key] = _Entry(
                content,
                asyncio.get_running_loop().call_later(_IDLE_SECONDS, self._remove, key),
            )
            self._bytes += len(content.content)
            return content

    async def _load(self, key: ArtifactReadIdentity) -> EffectArtifactContent:
        stream = await self._storage.open_verified(key.source)
        try:
            content = await stream.read()
        finally:
            await stream.close()
        if len(content) != key.source.byte_size:
            raise EffectViolation("EFFECT-ARTIFACT-INTEGRITY")
        return await asyncio.to_thread(project_artifact, key.kind, key.source, content)
