"""Tests for supported platform and toolchain metadata checks."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.check_locked_environment import check_repository

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATHS = (
    ".python-version",
    ".node-version",
    "apps/armi-creator-web/package.json",
    "tools/toolchain-node/package.json",
    "tools/toolchain-manifest.json",
)


class LockedEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in FIXTURE_PATHS:
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def codes(self) -> set[str]:
        return {
            violation.code
            for violation in check_repository(
                self.root,
                system_name="Windows",
                machine="AMD64",
            )
        }

    def test_current_repository_satisfies_toolchain_checks(self) -> None:
        self.assertEqual(
            check_repository(ROOT, system_name="Windows", machine="AMD64"),
            [],
        )

    def test_manifest_only_keeps_consumed_tool_integrity_values(self) -> None:
        manifest = json.loads(
            (ROOT / "tools/toolchain-manifest.json").read_text(encoding="utf-8")
        )
        tools = {item["id"]: item for item in manifest["tools"]}
        self.assertEqual(
            {tool_id for tool_id, item in tools.items() if "archive_sha256" in item},
            {
                "uv",
                "node",
                "postgresql",
                "pgvector-windows",
                "msvc-build-tools",
            },
        )
        self.assertEqual(
            {tool_id for tool_id, item in tools.items() if "install_digest" in item},
            {"postgresql"},
        )

    def test_unsupported_platform_is_rejected(self) -> None:
        violations = check_repository(
            self.root,
            system_name="Linux",
            machine="x86_64",
        )
        self.assertIn("S003-PLATFORM", {item.code for item in violations})

    def test_wrong_tool_version_is_rejected(self) -> None:
        (self.root / ".node-version").write_text("24.18.1\n", encoding="utf-8")
        self.assertIn("S003-VERSION", self.codes())


if __name__ == "__main__":
    unittest.main()
