"""Unit coverage for the technology-neutral artifact contract."""

from __future__ import annotations

import unittest
from uuid import uuid4, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_kernel.contracts import Digest, TraceId


def _policy(**overrides: object) -> ArtifactPolicy:
    values: dict[str, object] = {
        "media_type": "application/octet-stream",
        "logical_kind": "test.payload",
        "producer_kind": "test-suite",
        "producer_trace_id": TraceId("1" + ("0" * 31)),
        "privacy_scope": ArtifactPrivacyScope.PRIVATE,
    }
    values.update(overrides)
    return ArtifactPolicy(**values)  # type: ignore[arg-type]


class ArtifactContractTests(unittest.TestCase):
    def test_policy_and_reference_are_strict(self) -> None:
        policy = _policy()
        artifact_id = ArtifactId(uuid7())
        reference = ArtifactRef(
            artifact_id=artifact_id,
            content_digest=Digest("sha256:" + ("a" * 64)),
            byte_size=1,
            media_type=policy.media_type,
            logical_kind=policy.logical_kind,
            privacy_scope=policy.privacy_scope,
            integrity_status=ArtifactIntegrityStatus.VERIFIED,
        )

        self.assertEqual(reference.artifact_id, artifact_id)
        self.assertEqual(
            tuple(ArtifactPrivacyScope),
            (
                ArtifactPrivacyScope.CREATOR_VISIBLE,
                ArtifactPrivacyScope.PRIVATE,
                ArtifactPrivacyScope.SHARED,
                ArtifactPrivacyScope.RESTRICTED,
            ),
        )
        self.assertEqual(
            tuple(ArtifactIntegrityStatus),
            (
                ArtifactIntegrityStatus.VERIFIED,
                ArtifactIntegrityStatus.MISSING,
                ArtifactIntegrityStatus.CORRUPT,
            ),
        )

    def test_invalid_id_media_and_token_are_rejected(self) -> None:
        invalid_values = (
            lambda: ArtifactId(uuid4()),
            lambda: _policy(media_type="Text/Plain"),
            lambda: _policy(media_type="text/plain; charset=utf-8"),
            lambda: _policy(logical_kind="../escape"),
            lambda: _policy(producer_kind=""),
        )
        for invalid in invalid_values:
            with (
                self.subTest(invalid=invalid),
                self.assertRaises(ArtifactViolation),
            ):
                invalid()

    def test_reference_rejects_empty_size_and_dynamic_enum_values(self) -> None:
        with self.assertRaisesRegex(ArtifactViolation, "ART-SIZE-LIMIT"):
            ArtifactRef(
                artifact_id=ArtifactId(uuid7()),
                content_digest=Digest("sha256:" + ("a" * 64)),
                byte_size=0,
                media_type="application/octet-stream",
                logical_kind="test.payload",
                privacy_scope=ArtifactPrivacyScope.PRIVATE,
                integrity_status=ArtifactIntegrityStatus.VERIFIED,
            )
        with self.assertRaises(ValueError):
            ArtifactPrivacyScope("owner")


if __name__ == "__main__":
    unittest.main()
