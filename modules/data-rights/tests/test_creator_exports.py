from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid7

from armi_data_rights._creator_export import CreatorExportService, _ArtifactSnapshot
from armi_data_rights.api import (
    CreatorExportCommand,
    CreatorExportResult,
    CreatorExportStatus,
    CreatorExportViolation,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId


class _Stream:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def read(self, size: int = -1) -> bytes:
        del size
        return self.content

    async def close(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Storage:
    def __init__(self, values: dict[str, bytes | None]) -> None:
        self.values = values

    async def open_verified(self, ref: ArtifactRef) -> _Stream:
        value = self.values.get(ref.content_digest.value)
        if value is None:
            raise ArtifactViolation("ART-MISSING")
        if Digest.from_bytes(value) != ref.content_digest:
            raise ArtifactViolation("ART-DIGEST-MISMATCH")
        return _Stream(value)


def _artifact(content: bytes) -> _ArtifactSnapshot:
    digest = Digest.from_bytes(content)
    return _ArtifactSnapshot(
        ArtifactRef(
            artifact_id=ArtifactId(uuid7()),
            content_digest=digest,
            byte_size=len(content),
            media_type="text/plain",
            logical_kind="creator.export.test",
            privacy_scope=ArtifactPrivacyScope.PRIVATE,
            integrity_status=ArtifactIntegrityStatus.VERIFIED,
        ),
        "creator.export.test",
    )


class CreatorExportContractTests(unittest.TestCase):
    def test_completed_directory_with_unsupported_format_is_rejected(self) -> None:
        now = Instant(datetime.now(UTC))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            published = root / "exports" / "unsupported"
            published.mkdir(parents=True)
            published.joinpath("manifest.json").write_text(
                '{"format":"armi.creator-export.unsupported"}\n', encoding="utf-8"
            )
            service = CreatorExportService(
                creator_party_id=uuid7(),
                data_root=root,
                storage=_Storage({}),  # type: ignore[arg-type]
                unit_of_work_factory=object(),  # type: ignore[arg-type]
                participants=(),
            )
            result = CreatorExportResult(
                uuid7(),
                CreatorExportStatus.COMPLETED,
                "unsupported",
                str(published),
                1,
                1,
                0,
                (),
                None,
                now,
                now,
                False,
            )
            with self.assertRaises(CreatorExportViolation) as raised:
                service._verify_published_format(  # pyright: ignore[reportPrivateUsage]
                    result
                )
            self.assertEqual(raised.exception.code, "CREATOR-EXPORT-FORMAT-UNSUPPORTED")

    def test_failed_export_settlement_failure_is_not_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = CreatorExportService(
                creator_party_id=uuid7(),
                data_root=Path(directory).resolve(),
                storage=_Storage({}),  # type: ignore[arg-type]
                unit_of_work_factory=object(),  # type: ignore[arg-type]
                participants=(),
            )
            with (
                patch.object(
                    CreatorExportService,
                    "_settle",
                    side_effect=CreatorExportViolation("CREATOR-EXPORT-UNAVAILABLE"),
                ),
                self.assertRaises(CreatorExportViolation) as raised,
            ):
                asyncio.run(
                    service._settle_failed(  # pyright: ignore[reportPrivateUsage]
                        uuid7(), TraceId("1" * 32)
                    )
                )
            self.assertEqual(raised.exception.code, "CREATOR-EXPORT-UNAVAILABLE")

    def test_command_restricts_export_to_one_directory_name(self) -> None:
        with self.assertRaises(CreatorExportViolation):
            CreatorExportCommand(
                "../escape",
                IdempotencyKey("export-1"),
                TraceId("1" * 32),
            )

    def test_partial_result_cannot_claim_running_state(self) -> None:
        now = Instant(datetime.now(UTC))
        result = CreatorExportResult(
            uuid7(),
            CreatorExportStatus.PARTIAL,
            "export-1",
            "data/exports/export-1",
            3,
            4,
            1,
            (Digest.from_bytes(b"missing").value,),
            None,
            now,
            now,
            True,
        )
        self.assertEqual(result.status, CreatorExportStatus.PARTIAL)


class CreatorExportArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_copies_every_verified_artifact(self) -> None:
        first = _artifact(b"first")
        second = _artifact(b"second")
        storage = _Storage(
            {
                first.ref.content_digest.value: b"first",
                second.ref.content_digest.value: b"second",
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service = CreatorExportService(
                creator_party_id=uuid7(),
                data_root=root,
                storage=storage,  # type: ignore[arg-type]
                unit_of_work_factory=object(),  # type: ignore[arg-type]
                participants=(),
            )
            staging = root / "staging"
            staging.mkdir()
            copied, missing = await service._copy_artifacts(  # pyright: ignore[reportPrivateUsage]
                staging, (first, second)
            )
            self.assertEqual((copied, missing), (2, ()))
            self.assertEqual(len(tuple((staging / "artifacts").iterdir())), 2)

    async def test_missing_and_checksum_failure_are_explicit_partial_inputs(
        self,
    ) -> None:
        missing = _artifact(b"missing")
        corrupt = _artifact(b"expected")
        storage = _Storage(
            {
                missing.ref.content_digest.value: None,
                corrupt.ref.content_digest.value: b"different",
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service = CreatorExportService(
                creator_party_id=uuid7(),
                data_root=root,
                storage=storage,  # type: ignore[arg-type]
                unit_of_work_factory=object(),  # type: ignore[arg-type]
                participants=(),
            )
            staging = root / "staging"
            staging.mkdir()
            copied, absent = await service._copy_artifacts(  # pyright: ignore[reportPrivateUsage]
                staging, (missing, corrupt)
            )
            self.assertEqual(copied, 0)
            self.assertEqual(
                absent,
                tuple(
                    sorted(
                        {
                            missing.ref.content_digest.value,
                            corrupt.ref.content_digest.value,
                        }
                    )
                ),
            )

    async def test_export_destination_permission_failure_is_not_partial(self) -> None:
        artifact = _artifact(b"content")
        storage = _Storage({artifact.ref.content_digest.value: b"content"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service = CreatorExportService(
                creator_party_id=uuid7(),
                data_root=root,
                storage=storage,  # type: ignore[arg-type]
                unit_of_work_factory=object(),  # type: ignore[arg-type]
                participants=(),
            )
            staging = root / "staging"
            staging.mkdir()
            with (
                patch.object(Path, "write_bytes", side_effect=PermissionError),
                self.assertRaises(PermissionError),
            ):
                await service._copy_artifacts(  # pyright: ignore[reportPrivateUsage]
                    staging, (artifact,)
                )


if __name__ == "__main__":
    unittest.main()
