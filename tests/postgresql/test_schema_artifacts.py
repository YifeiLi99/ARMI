from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tools.generate_schema_artifacts import (
    build_manifest,
    canonical_manifest_bytes,
    generated_files,
)


class SchemaArtifactTests(unittest.TestCase):
    def test_manifest_and_wheel_mirror_are_deterministic(self) -> None:
        root = Path.cwd()
        generated = generated_files(root)
        manifest = canonical_manifest_bytes(build_manifest(root / "schema"))
        self.assertEqual(
            (root / "schema/manifests/schema-manifest.json").read_bytes(),
            manifest,
        )
        for relative, value in generated.items():
            self.assertEqual(
                (
                    root / "apps/armi-runtime/src/armi_runtime/composition/"
                    "runtime_resources/schema" / relative
                ).read_bytes(),
                value,
            )

    def test_baseline_contains_only_schema_and_migration_ledger(self) -> None:
        sql = Path("schema/migrations/0001_m0_baseline.sql").read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE SCHEMA"), 1)
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("armi.schema_migrations", sql)
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:artifact|audit_events|durable_work|outbox_items|"
                r"subject|lifeline)\b"
            ),
        )
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?im)^\s*(?:BEGIN|COMMIT|ROLLBACK|GRANT|REVOKE|CREATE ROLE|"
                r"ALTER OWNER|\\)"
            ),
        )

    def test_manifest_has_exact_target_and_no_self_digest(self) -> None:
        manifest = json.loads(
            Path("schema/manifests/schema-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["postgresql"]["version"], "18.4")
        self.assertEqual(manifest["target"], {"schema": "armi", "version": 1})
        self.assertEqual(
            [item["name"] for item in manifest["allowed_objects"]],
            ["armi.schema_migrations"],
        )
        self.assertNotIn("manifest_sha256", manifest)

    def test_runtime_module_has_no_upgrade_reference(self) -> None:
        source = Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("upgrade_operator_schema", source)
        self.assertNotIn(".upgrade(", source)


if __name__ == "__main__":
    unittest.main()
