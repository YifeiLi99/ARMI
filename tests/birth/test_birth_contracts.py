from __future__ import annotations

import asyncio
import json
import selectors
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

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
from armi_runtime.composition.bootstrap import execute_birth

ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
BIRTH_REQUEST_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234568")
CREATOR_PARTY_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234569")


def manifest_value() -> dict[str, object]:
    anchor = {
        "schema_version": "armi.personality-anchor.v1",
        "voice_style": "约 16 岁少女口吻",
        "traits": ["好奇", "坦率"],
    }
    return {
        "schema_version": "armi.birth-manifest.v1",
        "environment_id": str(ENVIRONMENT_ID),
        "birth_request_id": str(BIRTH_REQUEST_ID),
        "creator_party_id": str(CREATOR_PARTY_ID),
        "idempotency_key": "birth-request-001",
        "personality_anchor": anchor,
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
    def test_birth_uses_psycopg_compatible_selector_loop(self) -> None:
        result = BirthResult(
            BIRTH_REQUEST_ID,
            CREATOR_PARTY_ID,
            ENVIRONMENT_ID,
            Digest.from_bytes(b"request"),
            True,
        )

        class Handle:
            def __enter__(self) -> Handle:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def consume(
                self, operation: Callable[[memoryview], BirthResult]
            ) -> BirthResult:
                return operation(memoryview(b"postgresql://redacted"))

        prepared = SimpleNamespace(
            root=Path("C:/acceptance"),
            effective=SimpleNamespace(
                config=SimpleNamespace(
                    environment=SimpleNamespace(environment_id=ENVIRONMENT_ID),
                    secret_locators={"database.runtime": object()},
                )
            ),
            credential_port=SimpleNamespace(resolve=lambda *_args: Handle()),
        )
        invocation = AsyncMock()
        with (
            patch(
                "armi_runtime.composition.bootstrap.load_birth_manifest",
                return_value=object(),
            ),
            patch(
                "armi_runtime.composition.bootstrap.execute_birth_with_conninfo",
                invocation,
            ),
            patch(
                "armi_runtime.composition.bootstrap.asyncio.run", return_value=result
            ) as run,
        ):
            self.assertIs(execute_birth(prepared), result)  # type: ignore[arg-type]

        coroutine = run.call_args.args[0]
        coroutine.close()
        loop = run.call_args.kwargs["loop_factory"]()
        try:
            self.assertIsInstance(loop, asyncio.SelectorEventLoop)
            self.assertIsInstance(loop._selector, selectors.SelectSelector)
        finally:
            loop.close()

    def test_private_manifest_loads_and_runtime_binds_package_identity(self) -> None:
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
        self.assertEqual(
            manifest.composition_digest,
            packaged_birth_digests()["composition_digest"],
        )

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
