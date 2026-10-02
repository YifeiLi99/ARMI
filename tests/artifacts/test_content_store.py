"""Real Windows-filesystem coverage for content-addressed bytes."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import threading
import unittest
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from unittest.mock import patch
from uuid import uuid7

import armi_artifact_store.content_store as content_store
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
    UnregisteredArtifactDisposition,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactPublication,
    ArtifactRef,
    ArtifactViolation,
    StagedArtifact,
)
from armi_kernel.contracts import Digest, TraceId


async def _chunks(*values: object) -> AsyncIterator[bytes]:
    for value in values:
        yield value  # type: ignore[misc]


def _policy() -> ArtifactPolicy:
    return ArtifactPolicy(
        media_type="application/octet-stream",
        logical_kind="test.payload",
        producer_kind="test-suite",
        producer_trace_id=TraceId("1" + ("0" * 31)),
        privacy_scope=ArtifactPrivacyScope.PRIVATE,
    )


def _reference(content: bytes) -> ArtifactRef:
    digest = hashlib.sha256(content).hexdigest()
    return ArtifactRef(
        artifact_id=ArtifactId(uuid7()),
        content_digest=Digest(f"sha256:{digest}"),
        byte_size=len(content),
        media_type="application/octet-stream",
        logical_kind="test.payload",
        privacy_scope=ArtifactPrivacyScope.PRIVATE,
        integrity_status=ArtifactIntegrityStatus.VERIFIED,
    )


class ContentStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "artifacts"
        self.store = ContentAddressedArtifactStore(
            self.root,
            max_object_bytes=16,
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def _publish(self, staged: StagedArtifact) -> ArtifactPublication:
        publication = ArtifactPublication(
            staged.stage_id,
            uuid7(),
            1,
            staged.content_digest,
            staged.byte_size,
            staged.policy,
        )
        return await self.store.publish_reserved(staged, publication)

    async def test_stage_publish_verified_read_and_exact_reuse(self) -> None:
        content = b"immutable"
        first = await self.store.stage(_chunks(b"immu", b"table"), _policy())
        self.assertFalse(
            await self.store.publication_object_exists(
                first.content_digest, first.byte_size
            )
        )
        published = await self._publish(first)
        self.assertTrue(
            await self.store.publication_object_exists(
                first.content_digest, first.byte_size
            )
        )
        second = await self.store.stage(_chunks(content), _policy())
        reused = await self._publish(second)

        self.assertEqual(published.content_digest, reused.content_digest)
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        self.assertEqual(object_path.read_bytes(), content)
        self.assertEqual(
            len(tuple(path for path in object_path.parent.iterdir() if path.is_file())),
            1,
        )

        stream = await self.store.open_verified(_reference(content))
        async with stream:
            self.assertEqual(await stream.read(4), b"immu")
            self.assertEqual(await stream.read(), b"table")
        with self.assertRaisesRegex(ArtifactViolation, "ART-STATE"):
            await stream.read()

    async def test_empty_oversize_and_non_byte_chunks_leave_no_stage(self) -> None:
        for source, code in (
            (_chunks(), "ART-SIZE-LIMIT"),
            (_chunks(b"x" * 17), "ART-SIZE-LIMIT"),
            (_chunks("not-bytes"), "ART-SOURCE"),
            (_chunks(b""), "ART-SOURCE"),
        ):
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(ArtifactViolation, code),
            ):
                await self.store.stage(source, _policy())
        staging = self.root / "staging"
        self.assertEqual(list(staging.iterdir()), [])

    async def test_cancelled_stage_closes_a_file_whose_open_is_still_pending(
        self,
    ) -> None:
        opened = threading.Event()
        release = threading.Event()
        returned = threading.Event()
        handles: list[BinaryIO] = []
        original_open = Path.open

        def delayed_open(path: Path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path.parent == self.root / "staging" and args == ("xb",):
                handles.append(handle)
                opened.set()
                release.wait(timeout=3)
                returned.set()
            return handle

        try:
            with patch.object(Path, "open", delayed_open):
                task = asyncio.create_task(
                    self.store.stage(_chunks(b"body"), _policy())
                )
                self.assertTrue(await asyncio.to_thread(opened.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(await asyncio.to_thread(returned.wait, 2))
            self.assertTrue(all(handle.closed for handle in handles))
            self.assertEqual(list((self.root / "staging").iterdir()), [])
        finally:
            release.set()
            for handle in handles:
                handle.close()

    async def test_failed_unlock_still_closes_the_lock_file(self) -> None:
        await self.store.prepare()
        lock = content_store._DigestFileLock(self.root / "locks" / "unlock-test.lock")
        lock.__enter__()
        handle = lock._file
        assert handle is not None
        try:
            with (
                patch.object(
                    content_store.msvcrt,
                    "locking",
                    side_effect=OSError("unlock failed"),
                ),
                self.assertRaisesRegex(ArtifactViolation, "ART-LOCK-IO"),
            ):
                lock.__exit__(None, None, None)
            self.assertTrue(handle.closed)
        finally:
            handle.close()

    async def test_cancelled_verified_open_closes_pending_file(self) -> None:
        content = b"cancel-read"
        staged = await self.store.stage(_chunks(content), _policy())
        await self._publish(staged)
        ref = _reference(content)
        original_open = ContentAddressedArtifactStore._open_verified_sync

        async def exercise(operation: str) -> None:
            opened = threading.Event()
            release = threading.Event()
            returned = threading.Event()
            handles: list[BinaryIO] = []
            paths: list[Path] = []

            def delayed_open(store, path, *args):
                handle = original_open(store, path, *args)
                handles.append(handle)
                paths.append(path)
                opened.set()
                release.wait(timeout=3)
                returned.set()
                return handle

            try:
                with patch.object(
                    ContentAddressedArtifactStore, "_open_verified_sync", delayed_open
                ):
                    task = asyncio.create_task(
                        self.store.open_verified(ref)
                        if operation == "read"
                        else self.store.publication_object_exists(
                            ref.content_digest, ref.byte_size
                        )
                    )
                    self.assertTrue(await asyncio.to_thread(opened.wait, 2))
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertTrue(await asyncio.to_thread(returned.wait, 2))
                self.assertTrue(all(handle.closed for handle in handles))
                moved = paths[0].with_suffix(".check")
                paths[0].rename(moved)
                moved.rename(paths[0])
            finally:
                release.set()
                for handle in handles:
                    handle.close()

        for operation in ("read", "exists"):
            with self.subTest(operation=operation):
                await exercise(operation)

    async def test_sync_read_and_unregistered_settlement_share_verifier(self) -> None:
        content = b"shared-owner"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(staged)

        self.assertEqual(self.store.read_verified_bytes(_reference(content)), content)
        self.assertEqual(
            self.store.settle_unregistered(published.content_digest),
            UnregisteredArtifactDisposition.DELETED,
        )
        self.assertEqual(
            self.store.settle_unregistered(published.content_digest),
            UnregisteredArtifactDisposition.ALREADY_ABSENT,
        )

    async def test_unregistered_corruption_is_quarantined(self) -> None:
        content = b"cleanup-corrupt"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(staged)
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        object_path.write_bytes(b"tampered")

        self.assertEqual(
            self.store.settle_unregistered(published.content_digest),
            UnregisteredArtifactDisposition.QUARANTINED,
        )
        self.assertFalse(object_path.exists())
        self.assertEqual(len(list((self.root / "quarantine").iterdir())), 1)

    async def test_corrupt_object_is_quarantined_before_bytes_are_released(
        self,
    ) -> None:
        content = b"original"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(staged)
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        object_path.write_bytes(b"tampered")

        with self.assertRaisesRegex(ArtifactViolation, "ART-CORRUPT"):
            await self.store.open_verified(_reference(content))

        self.assertFalse(object_path.exists())
        quarantined = list((self.root / "quarantine").iterdir())
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(quarantined[0].name.startswith(digest_hex))

    async def test_staged_tamper_and_hard_link_are_rejected(self) -> None:
        content = b"original"
        staged = await self.store.stage(_chunks(content), _policy())
        stage_path = self.root / "staging" / f"stage-{staged.stage_id.value.hex}.tmp"
        stage_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ArtifactViolation, "ART-CORRUPT"):
            await self._publish(staged)

        valid = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(valid)
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        hard_link = self.root / "second-link"
        os.link(object_path, hard_link)
        with self.assertRaisesRegex(ArtifactViolation, "ART-PATH-UNSAFE"):
            await self.store.open_verified(_reference(content))

    async def test_scan_is_deterministic_and_never_deletes_orphans(self) -> None:
        content = b"orphan"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(staged)
        digest = published.content_digest.value
        digest_hex = digest.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
        os.utime(object_path, (old, old))
        cutoff = datetime.now(UTC) - timedelta(days=1)

        first = await self.store.scan(cutoff=cutoff, registered={})
        second = await self.store.scan(cutoff=cutoff, registered={})

        self.assertEqual(first, second)
        self.assertEqual(first[0].category, "unregistered_object")
        self.assertEqual(first[0].content_digest, digest)
        self.assertTrue(object_path.exists())

    async def test_cleanup_removes_only_revalidated_unregistered_objects(self) -> None:
        content = b"cleanup-orphan"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self._publish(staged)
        digest = published.content_digest.value
        digest_hex = digest.removeprefix("sha256:")
        object_path = (
            self.root
            / "objects"
            / "sha256"
            / digest_hex[:2]
            / digest_hex[2:4]
            / digest_hex
        )
        old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
        os.utime(object_path, (old, old))
        cutoff = datetime.now(UTC) - timedelta(days=1)

        retained = await self.store.cleanup(
            cutoff=cutoff,
            registered={digest: _reference(content)},
        )
        self.assertEqual(retained.removed_counts, ())
        self.assertTrue(object_path.exists())

        removed = await self.store.cleanup(cutoff=cutoff, registered={})
        self.assertEqual(removed.removed_counts, (("unregistered_object", 1),))
        self.assertEqual(removed.removed_bytes, len(content))
        self.assertFalse(object_path.exists())

    async def test_cleanup_removes_only_staging_older_than_cutoff(self) -> None:
        old_stage = await self.store.stage(_chunks(b"old-stage"), _policy())
        current_stage = await self.store.stage(_chunks(b"current"), _policy())
        staging = self.root / "staging"
        old_path = staging / f"stage-{old_stage.stage_id.value.hex}.tmp"
        current_path = staging / f"stage-{current_stage.stage_id.value.hex}.tmp"
        old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
        os.utime(old_path, (old, old))

        result = await self.store.cleanup(
            cutoff=datetime.now(UTC) - timedelta(days=1),
            registered={},
        )

        self.assertEqual(result.removed_counts, (("stale_staging", 1),))
        self.assertEqual(result.removed_bytes, len(b"old-stage"))
        self.assertFalse(old_path.exists())
        self.assertTrue(current_path.exists())


if __name__ == "__main__":
    unittest.main()
