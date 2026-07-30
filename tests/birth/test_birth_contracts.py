from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

import rfc8785
from armi_kernel.application import (
    BirthResult,
    BirthViolation,
    PersonalityAnchor,
)
from armi_kernel.contracts import Digest
from armi_runtime.composition.birth_manifest import (
    load_birth_manifest,
    packaged_birth_digests,
)

ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
BIRTH_REQUEST_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234568")
CREATOR_PARTY_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234569")


def manifest_value() -> dict[str, object]:
    anchor = {
        "schema_version": "armi.personality-anchor.v1",
        "voice_style": "约 16 岁少女口吻",
        "traits": ["好奇", "坦率"],
    }
    package = {name: digest.value for name, digest in packaged_birth_digests().items()}
    return {
        "schema_version": "armi.birth-manifest.v1",
        "environment_id": str(ENVIRONMENT_ID),
        "birth_request_id": str(BIRTH_REQUEST_ID),
        "creator_party_id": str(CREATOR_PARTY_ID),
        "idempotency_key": "birth-request-001",
        "personality_anchor": anchor,
        "personality_anchor_digest": Digest.from_bytes(rfc8785.dumps(anchor)).value,
        "expected_package": package,
    }


def write_manifest(root: Path, value: dict[str, object]) -> None:
    bootstrap = root / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "birth-manifest.json").write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


class BirthContractTests(unittest.TestCase):
    def test_private_manifest_loads_and_binds_all_package_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_manifest(root, manifest_value())
            manifest = load_birth_manifest(
                root,
                expected_environment_id=ENVIRONMENT_ID,
            )

        self.assertEqual(manifest.environment_id, ENVIRONMENT_ID)
        self.assertEqual(manifest.personality_anchor.traits, ("好奇", "坦率"))
        self.assertTrue(manifest.request_digest.value.startswith("sha256:"))

    def test_forbidden_acquired_content_is_rejected_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = manifest_value()
            value["name"] = "forbidden"
            write_manifest(root, value)
            with self.assertRaises(BirthViolation) as raised:
                load_birth_manifest(root, expected_environment_id=ENVIRONMENT_ID)

        self.assertEqual(raised.exception.code, "BIRTH-FORBIDDEN-CONTENT")
        self.assertNotIn("forbidden", str(raised.exception))

    def test_anchor_and_result_are_strict_and_redacted(self) -> None:
        with self.assertRaises(BirthViolation):
            PersonalityAnchor(
                "armi.personality-anchor.v1",
                "other",
                ("好奇",),
            )
        result = BirthResult(
            BIRTH_REQUEST_ID,
            CREATOR_PARTY_ID,
            ENVIRONMENT_ID,
            Digest.from_bytes(b"request"),
            True,
        )
        self.assertEqual(result.safe_view()["status"], "applied")


if __name__ == "__main__":
    unittest.main()
