"""Real Windows-filesystem coverage for content-addressed bytes."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)


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

    async def test_stage_publish_verified_read_and_exact_reuse(self) -> None:
        content = b"immutable"
        first = await self.store.stage(_chunks(b"immu", b"table"), _policy())
        published = await self.store.publish(first)
        second = await self.store.stage(_chunks(content), _policy())
        reused = await self.store.publish(second)

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

    async def test_exact_verified_delete_is_idempotent_and_removes_only_target(
        self,
    ) -> None:
        content = b"erase-me"
        staged = await self.store.stage(_chunks(content), _policy())
        await self.store.publish(staged)

        self.assertTrue(await self.store.delete_verified(_reference(content)))
        self.assertFalse(await self.store.delete_verified(_reference(content)))
        with self.assertRaisesRegex(ArtifactViolation, "ART-MISSING"):
            await self.store.open_verified(_reference(content))

    async def test_corrupt_object_is_quarantined_before_bytes_are_released(
        self,
    ) -> None:
        content = b"original"
        staged = await self.store.stage(_chunks(content), _policy())
        published = await self.store.publish(staged)
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
            await self.store.publish(staged)

        valid = await self.store.stage(_chunks(content), _policy())
        published = await self.store.publish(valid)
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
        published = await self.store.publish(staged)
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
        published = await self.store.publish(staged)
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
