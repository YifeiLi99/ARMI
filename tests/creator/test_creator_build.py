"""WEB-GEN and WEB-ASSET checks for deterministic Creator artifacts."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.build_creator_web import (
    CreatorBuildError,
    files_under,
    generate,
    validate_openapi,
)

ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = Path(os.environ.get("ARMI_TOOL_ROOT", ROOT / ".armi-tools"))
RESOURCE_ROOT = (
    ROOT / "apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources"
)


def temporary_root() -> Path:
    path = ROOT / ".tmp"
    path.mkdir(exist_ok=True)
    return path


class CreatorBuildTests(unittest.TestCase):
    def test_source_resource_package_contains_no_built_assets(self) -> None:
        self.assertFalse((RESOURCE_ROOT / "manifest.json").exists())
        static = RESOURCE_ROOT / "static"
        self.assertFalse(
            static.is_dir() and any(path.is_file() for path in static.rglob("*"))
        )

    def test_two_isolated_generations_are_byte_identical(self) -> None:
        with (
            tempfile.TemporaryDirectory(dir=temporary_root()) as first,
            tempfile.TemporaryDirectory(dir=temporary_root()) as second,
        ):
            first_openapi, first_types, first_resources = generate(
                ROOT,
                TOOL_ROOT,
                Path(first),
            )
            second_openapi, second_types, second_resources = generate(
                ROOT,
                TOOL_ROOT,
                Path(second),
            )
            self.assertEqual(first_openapi.read_bytes(), second_openapi.read_bytes())
            self.assertEqual(first_types.read_bytes(), second_types.read_bytes())
            self.assertEqual(
                files_under(first_resources),
                files_under(second_resources),
            )
            manifest = json.loads(
                (first_resources / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], "armi.creator-static.v1")
            self.assertEqual(manifest["base_path"], "/ui/")
            self.assertEqual(manifest["entrypoint"], "static/index.html")
            self.assertFalse(manifest["runtime_discovery"])
            self.assertNotIn("timestamp", manifest)
            self.assertTrue(
                all(not Path(item["path"]).is_absolute() for item in manifest["assets"])
            )

    def test_extra_openapi_path_is_rejected_with_stable_code(self) -> None:
        schema = {
            "openapi": "3.1.0",
            "paths": {
                "/health/live": {},
                "/health/ready": {},
                "/v1/runtime/status": {},
                "/v1/future": {},
            },
        }
        with self.assertRaises(CreatorBuildError) as raised:
            validate_openapi(schema)
        self.assertEqual(raised.exception.code, "CON-OPENAPI-PATHS")

    def test_missing_tool_is_a_stable_failure(self) -> None:
        with (
            tempfile.TemporaryDirectory(dir=temporary_root()) as temporary,
            self.assertRaises(CreatorBuildError) as raised,
        ):
            generate(ROOT, Path(temporary), Path(temporary) / "stage")
        self.assertEqual(raised.exception.code, "WEB-GEN-TOOL")


if __name__ == "__main__":
    unittest.main()
