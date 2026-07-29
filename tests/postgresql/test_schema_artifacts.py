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
        role_manifest = (
            root / "schema/manifests/database-role-manifest.json"
        ).read_bytes()
        manifest = canonical_manifest_bytes(
            build_manifest(root / "schema", role_manifest)
        )
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

    def test_manifest_has_exact_target_role_policy_and_no_self_digest(self) -> None:
        manifest = json.loads(
            Path("schema/manifests/schema-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["postgresql"]["version"], "18.4")
        self.assertEqual(manifest["target"], {"schema": "armi", "version": 2})
        self.assertEqual(
            [item["version"] for item in manifest["migrations"]],
            [1, 2],
        )
        self.assertEqual(
            manifest["database_role_manifest"]["path"],
            "schema/manifests/database-role-manifest.json",
        )
        self.assertEqual(
            [item["name"] for item in manifest["allowed_objects"]],
            ["armi.schema_migrations"],
        )
        self.assertNotIn("manifest_sha256", manifest)

    def test_permission_migration_has_no_future_object_or_privilege_surface(
        self,
    ) -> None:
        sql = Path("schema/migrations/0002_database_permissions.sql").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:CREATE\s+(?:TABLE|ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER|"
                r"artifact|audit_events|durable_work|outbox_items)\b"
            ),
        )
        self.assertIn("REVOKE ALL ON SCHEMA armi FROM PUBLIC", sql)
        self.assertIn("GRANT SELECT ON TABLE armi.schema_migrations", sql)

    def test_database_role_manifest_is_current_and_has_no_definer(self) -> None:
        role_manifest = json.loads(
            Path("schema/manifests/database-role-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(role_manifest["schema_version"], "armi.database-roles.v1")
        self.assertEqual(
            [item["name"] for item in role_manifest["capability_roles"]],
            ["armi_owner", "armi_migrator", "armi_runtime", "armi_admin"],
        )
        self.assertEqual(role_manifest["security_definer"]["entries"], [])
        self.assertEqual(role_manifest["default_privileges"], [])

    def test_runtime_module_has_no_upgrade_reference(self) -> None:
        source = Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("upgrade_operator_schema", source)
        self.assertNotIn(".upgrade(", source)


if __name__ == "__main__":
    unittest.main()
