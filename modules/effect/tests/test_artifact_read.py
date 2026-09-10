"""Real file verification behind the production Effect read/cache path."""

from __future__ import annotations

import asyncio
import hashlib
import io
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid7

import pytest
import pytest_asyncio
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_effect import _artifact_read
from armi_effect._application import EffectPipeline
from armi_effect._artifact_read import CreatorArtifactReader
from armi_effect.api import EffectArtifactKind, EffectId, EffectViolation
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactPublication,
    ArtifactRef,
    RuntimeFence,
    RuntimeInstanceId,
)
from armi_kernel.contracts import Digest, TraceId


class Harness:
    def __init__(self, root):
        self.creator = uuid7()
        self.effect = EffectId(uuid7())
        self.fence = RuntimeFence(
            RuntimeInstanceId(uuid7()), uuid7(), uuid7(), uuid7(), 1
        )
        self.ref: ArtifactRef | None = None
        self.store = ContentAddressedArtifactStore(
            root, max_object_bytes=20 * 1024 * 1024
        )
        self.reads = 0
        self.custody = 0
        self.pipeline = cast(Any, object.__new__(EffectPipeline))
        self.pipeline._factory = SimpleNamespace(
            unit_of_work=self.uow, environment_id=uuid7()
        )
        self.pipeline._repository = SimpleNamespace(get_effect=self.visible)
        self.pipeline._codex_artifacts = SimpleNamespace(
            artifact_reference=self.reference
        )
        self.pipeline._runtime_admission = lambda: self.fence
        self.pipeline._custody = SimpleNamespace(hold=self.hold)
        self.pipeline._stop = asyncio.Event()
        self.pipeline._artifact_reader = CreatorArtifactReader(self.store)

    @asynccontextmanager
    async def uow(self, **kwargs):
        assert kwargs == {"read_only": True}
        # Production read-only UoWs intentionally do not acquire a write fence.
        yield SimpleNamespace(runtime_fence=None)

    @asynccontextmanager
    async def hold(self, requests, *, deadline_at):
        assert len(requests) == 2 and deadline_at is None
        self.custody += 1
        try:
            yield
        finally:
            self.custody -= 1

    async def visible(self, uow, effect, creator):
        assert self.custody > 0
        if creator != self.creator:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        return SimpleNamespace(effect_kind="codex_delegation")

    async def reference(self, uow, **kwargs):
        if self.ref is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return self.ref

    async def publish(self, content, media_type="text/plain"):
        async def chunks():
            yield content

        staged = await self.store.stage(
            chunks(),
            ArtifactPolicy(
                media_type,
                "codex.result",
                "codex",
                TraceId("1" * 32),
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        await self.store.publish_reserved(
            staged,
            ArtifactPublication(
                staged.stage_id,
                uuid7(),
                1,
                staged.content_digest,
                staged.byte_size,
                staged.policy,
            ),
        )
        self.ref = ArtifactRef(
            ArtifactId(uuid7()),
            staged.content_digest,
            len(content),
            media_type,
            "codex.result",
            ArtifactPrivacyScope.PRIVATE,
            ArtifactIntegrityStatus.VERIFIED,
        )

    async def read(self, kind=EffectArtifactKind.PATCH):
        return await self.pipeline.read_artifact(
            self.effect, creator_party_id=self.creator, kind=kind
        )


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    h = Harness(tmp_path / "artifacts")
    original = ContentAddressedArtifactStore._open_verified_sync

    def counted(store, *args):
        h.reads += 1
        return original(store, *args)

    monkeypatch.setattr(ContentAddressedArtifactStore, "_open_verified_sync", counted)
    try:
        yield h
    finally:
        await h.pipeline.close()


@pytest.mark.asyncio
async def test_repeated_reads_verify_once_without_rehashing(harness, monkeypatch):
    h = harness
    content = b"a" * (4 * 1024 * 1024)
    await h.publish(content)
    h.reads = 0
    hashed_bytes = 0
    hash_calls = 0
    original_sha256 = hashlib.sha256

    class CountedHash:
        def __init__(self, initial=b""):
            nonlocal hash_calls, hashed_bytes
            hash_calls += 1
            hashed_bytes += len(initial)
            self.inner = original_sha256(initial)

        def update(self, value):
            nonlocal hashed_bytes
            hashed_bytes += len(value)
            self.inner.update(value)

        def hexdigest(self):
            return self.inner.hexdigest()

    monkeypatch.setattr(hashlib, "sha256", CountedHash)
    first = await h.read()
    assert first.content == content
    assert first.content_digest == h.ref.content_digest
    assert h.reads == 1
    # Any full-content hash on a hit is a regression, including accidental
    # reconstruction/validation of the immutable response object.
    monkeypatch.setattr(Digest, "from_bytes", lambda *_: pytest.fail("rehash on hit"))
    for _ in range(63):
        assert await h.read() is first
    assert h.reads == 1
    assert hash_calls == 1 and hashed_bytes == len(content)


@pytest.mark.asyncio
async def test_concurrent_cold_reads_share_one_load(harness):
    h = harness
    await h.publish(b"shared" * 10000)
    h.reads = 0
    results = await asyncio.gather(*(h.read() for _ in range(8)))
    assert all(result is results[0] for result in results)
    assert h.reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", [EffectArtifactKind.PATCH, EffectArtifactKind.VALIDATION_REPORT]
)
async def test_unprojected_content_preserves_registered_digest(harness, kind):
    h = harness
    await h.publish(b'{"verified":true}', "application/json")
    result = await h.read(kind)
    assert result.content_digest == h.ref.content_digest
    assert result.content == b'{"verified":true}'


@pytest.mark.asyncio
async def test_final_result_only_returns_deliverable_and_its_digest(harness):
    h = harness
    await h.publish(
        b'{"changed_paths":["result.md"],"deliverable":"done\\n","summary":"private wrapper"}',
        "application/json",
    )
    result = await h.read(EffectArtifactKind.FINAL_RESULT)
    assert result.content == b"done\n"
    assert result.media_type == "text/plain"
    assert result.content_digest == Digest.from_bytes(b"done\n")
    assert result.content_digest != h.ref.content_digest
    assert await h.read(EffectArtifactKind.FINAL_RESULT) is result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,kind",
    [
        (b"\xff", EffectArtifactKind.PATCH),
        (b"[]", EffectArtifactKind.FINAL_RESULT),
        (
            b'{"summary":"ok","changed_paths":[],"deliverable":""}',
            EffectArtifactKind.FINAL_RESULT,
        ),
        (
            b'{"summary":NaN,"changed_paths":[],"deliverable":"x"}',
            EffectArtifactKind.FINAL_RESULT,
        ),
        (
            b'{"summary":"ok","changed_paths":[],"deliverable":"x","deliverable":"y"}',
            EffectArtifactKind.FINAL_RESULT,
        ),
    ],
)
async def test_invalid_content_is_never_cached(harness, content, kind):
    h = harness
    await h.publish(content)
    with pytest.raises(EffectViolation, match="EFFECT-ARTIFACT-INTEGRITY"):
        await h.read(kind)
    assert not h.pipeline._artifact_reader._entries


@pytest.mark.asyncio
async def test_hit_cannot_bypass_creator_scope(harness):
    h = harness
    await h.publish(b"private")
    await h.read()
    with pytest.raises(EffectViolation, match="SCOPE-EFFECT-NOT-VISIBLE"):
        await h.pipeline.read_artifact(
            h.effect, creator_party_id=uuid7(), kind=EffectArtifactKind.PATCH
        )


@pytest.mark.asyncio
async def test_changed_reference_and_runtime_load_fresh_content(harness):
    h = harness
    await h.publish(b"before")
    await h.read()
    await h.publish(b"after")
    h.reads = 0
    assert (await h.read()).content == b"after"
    assert h.reads == 1
    assert len(h.pipeline._artifact_reader._entries) == 1
    h.fence = replace(h.fence, life_generation_id=uuid7())
    await h.read()
    assert h.reads == 2
    assert len(h.pipeline._artifact_reader._entries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", [True, False])
async def test_retired_or_corrupt_reference_invalidates_hit(harness, deleted):
    h = harness
    await h.publish(b"private")
    await h.read()
    h.ref = (
        None
        if deleted
        else replace(h.ref, integrity_status=ArtifactIntegrityStatus.CORRUPT)
    )
    with pytest.raises(EffectViolation, match="EFFECT-PAYLOAD-UNAVAILABLE"):
        await h.read()
    assert not h.pipeline._artifact_reader._entries


@pytest.mark.asyncio
async def test_corrupt_file_fails_on_cold_read_without_caching(harness):
    h = harness
    await h.publish(b"original")
    digest = h.ref.content_digest.value.removeprefix("sha256:")
    path = h.store._objects / "sha256" / digest[:2] / digest[2:4] / digest
    path.write_bytes(b"tampered")
    with pytest.raises(EffectViolation, match="EFFECT-PAYLOAD-UNAVAILABLE"):
        await h.read()
    assert not h.pipeline._artifact_reader._entries


@pytest.mark.asyncio
async def test_warm_snapshot_is_reused_but_missing_cold_file_is_not_hidden(harness):
    h = harness
    await h.publish(b"original")
    result = await h.read()
    digest = h.ref.content_digest.value.removeprefix("sha256:")
    path = h.store._objects / "sha256" / digest[:2] / digest[2:4] / digest
    path.unlink()  # The verified handle was closed; Windows permits deletion.
    assert await h.read() is result
    h.pipeline._artifact_reader.clear()
    with pytest.raises(EffectViolation, match="EFFECT-PAYLOAD-UNAVAILABLE"):
        await h.read()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reference", "runtime", "stop", "delete"])
async def test_reference_change_during_load_is_rejected(harness, monkeypatch, change):
    h = harness
    await h.publish(b"private")
    original = CreatorArtifactReader._load

    async def changed(reader, key):
        result = await original(reader, key)
        if change == "reference":
            h.ref = replace(h.ref, artifact_id=ArtifactId(uuid7()))
        elif change == "runtime":
            h.fence = replace(h.fence, fence_token=2)
        elif change == "stop":
            h.pipeline.stop()
        else:
            h.ref = None
        return result

    monkeypatch.setattr(CreatorArtifactReader, "_load", changed)
    with pytest.raises(EffectViolation):
        await h.read()
    assert not h.pipeline._artifact_reader._entries


@pytest.mark.asyncio
@pytest.mark.parametrize("byte_limit,entry_limit", [(12, 32), (64, 2)])
async def test_lru_evicts_least_recent_by_bytes_or_entries(
    harness, monkeypatch, byte_limit, entry_limit
):
    h = harness
    monkeypatch.setattr(_artifact_read, "_MAX_BYTES", byte_limit)
    monkeypatch.setattr(_artifact_read, "_MAX_ENTRIES", entry_limit)
    sources = []
    for payload in (b"111111", b"222222", b"333333"):
        await h.publish(payload)
        sources.append((EffectId(uuid7()), h.ref))
    h.reads = 0
    for index in (0, 1, 0, 2):
        h.effect, h.ref = sources[index]
        await h.read()
    cache = h.pipeline._artifact_reader
    assert cache._bytes == 12 and len(cache._entries) == 2
    assert h.reads == 3
    h.effect, h.ref = sources[0]
    await h.read()
    assert h.reads == 3
    h.effect, h.ref = sources[1]
    assert (await h.read()).content == b"222222"
    assert h.reads == 4


@pytest.mark.asyncio
async def test_idle_expiry_and_stop_release_memory_and_timers(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(_artifact_read, "_IDLE_SECONDS", 0.02)
    await h.publish(b"private")
    await h.read()
    cache = h.pipeline._artifact_reader
    await asyncio.sleep(0.06)
    assert cache._bytes == 0 and not cache._entries
    h.reads = 0
    await h.read()
    assert h.reads == 1
    handles = [entry.expiry for entry in cache._entries.values()]
    h.pipeline.stop()
    assert not cache._entries
    assert all(handle.cancelled() for handle in handles)
    with pytest.raises(EffectViolation, match="EFFECT-RUNTIME-STALE"):
        await h.read()


@pytest.mark.asyncio
@pytest.mark.parametrize("during_open", [False, True])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancel_or_close_waits_for_file_cleanup_without_caching(
    harness, during_open, shutdown
):
    h = harness
    await h.publish(b"private")
    started, release = asyncio.Event(), asyncio.Event()
    closed = False
    file = io.BytesIO(b"private")

    async def read():
        if not during_open:
            started.set()
            await release.wait()
        return file.read()

    async def close():
        nonlocal closed
        file.close()
        closed = True

    async def opened(ref):
        if during_open:
            started.set()
            await release.wait()
        return SimpleNamespace(read=read, close=close)

    h.pipeline._artifact_reader._storage = SimpleNamespace(open_verified=opened)
    task = asyncio.create_task(h.read())
    await started.wait()
    closing = None
    if shutdown:
        closing = asyncio.create_task(h.pipeline.close())
        await asyncio.sleep(0)
        assert not closing.done() and not file.closed
    else:
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and h.custody > 0
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not file.closed
    release.set()
    if shutdown:
        with pytest.raises(EffectViolation, match="EFFECT-RUNTIME-STALE"):
            await task
        assert closing is not None
        await closing
    else:
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed and h.custody == 0
    assert not h.pipeline._artifact_reader._entries
