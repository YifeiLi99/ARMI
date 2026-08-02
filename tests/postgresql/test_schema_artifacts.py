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
        self.assertEqual(manifest["target"], {"schema": "armi", "version": 19})
        self.assertEqual(
            [item["version"] for item in manifest["migrations"]],
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
        )
        self.assertEqual(
            manifest["database_role_manifest"]["path"],
            "schema/manifests/database-role-manifest.json",
        )
        self.assertEqual(
            [item["name"] for item in manifest["allowed_objects"]],
            [
                "armi.schema_migrations",
                "armi.artifacts",
                "armi.audit_events",
                "armi.durable_work",
                "armi.outbox_items",
                "armi.subjects",
                "armi.life_generations",
                "armi.runtime_bundle_activations",
                "armi.parties",
                "armi.prompt_documents",
                "armi.prompt_revisions",
                "armi.subject_component_heads",
                "armi.subject_component_revisions",
                "armi.runtime_instances",
                "armi.runtime_recovery_runs",
                "armi.interaction_scenes",
                "armi.scene_timeline_items",
                "armi.creator_input_interactions",
                "armi.external_evidence",
                "armi.opportunities",
                "armi.cognitive_episodes",
                "armi.cognitive_context_items",
                "armi.cognitive_attempts",
                "armi.cognitive_candidate_validations",
                "armi.cognitive_candidate_validation_items",
                "armi.cognitive_candidate_basis_links",
                "armi.subject_commits",
                "armi.accepted_experiences",
                "armi.experience_evidence_links",
                "armi.cognitive_candidate_applications",
                "armi.capabilities",
                "armi.capability_requests",
                "armi.capability_request_basis_links",
                "armi.capability_request_decisions",
                "armi.permission_grants",
                "armi.action_intents",
                "armi.action_intent_revisions",
                "armi.formal_no_action_decisions",
                "armi.creator_response_operations",
                "armi.policy_decisions",
                "armi.effects",
                "armi.effect_outbox_items",
                "armi.creator_response_deliveries",
                "armi.effect_attempts",
                "armi.effect_observations",
                "armi.web_observation_requests",
                "armi.observation_attempts",
                "armi.observation_tool_calls",
            ],
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

    def test_artifact_migration_is_the_only_s012_object(self) -> None:
        sql = Path("schema/migrations/0003_content_addressed_artifacts.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("CREATE TABLE armi.artifacts", sql)
        self.assertIn("GRANT INSERT (", sql)
        self.assertIn(
            "GRANT UPDATE (integrity_status) ON armi.artifacts TO armi_runtime",
            sql,
        )
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:audit_events|durable_work|outbox_items|"
                r"CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )

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

    def test_runtime_authority_migration_is_the_only_s016_object(self) -> None:
        sql = Path("schema/migrations/0007_runtime_authority.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("CREATE TABLE armi.runtime_instances", sql)
        self.assertNotIn("SESSION", sql.upper())
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )
        source = Path(
            "apps/armi-runtime/src/armi_runtime/adapters/persistence/"
            "runtime_authority.py"
        ).read_text(encoding="utf-8")
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertNotIn("pg_advisory_lock(", source)

    def test_runtime_recovery_migration_is_the_only_s017_object(self) -> None:
        sql = Path("schema/migrations/0008_runtime_recovery.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("CREATE TABLE armi.runtime_recovery_runs", sql)
        self.assertNotIn("JSONB", sql.upper())
        self.assertIn("status IN ('running', 'safe', 'blocked', 'abandoned')", sql)
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:effect|episode|projection|cognition_attempt|"
                r"CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )

    def test_web_observation_migration_has_only_custody_objects(self) -> None:
        sql = Path("schema/migrations/0019_readonly_web_search_custody.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        self.assertIn("CREATE TABLE armi.web_observation_requests", sql)
        self.assertIn("CREATE TABLE armi.observation_attempts", sql)
        self.assertIn("CREATE TABLE armi.observation_tool_calls", sql)
        self.assertNotIn("external_evidence", sql)
        self.assertNotIn("scene_timeline_items", sql)
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )

    def test_scene_timeline_migration_has_only_the_s019_query_surface(self) -> None:
        sql = Path("schema/migrations/0009_scene_timeline_query.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertIn("CREATE TABLE armi.interaction_scenes", sql)
        self.assertIn("CREATE TABLE armi.scene_timeline_items", sql)
        self.assertNotIn("JSONB", sql.upper())
        self.assertNotIn("GRANT UPDATE", sql.upper())
        self.assertNotIn("GRANT DELETE", sql.upper())
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )

    def test_audit_migration_has_only_the_append_only_s013_surface(self) -> None:
        sql = Path("schema/migrations/0004_normal_audit_foundation.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 1)
        self.assertIn("CREATE TABLE armi.audit_events", sql)
        self.assertNotIn("JSONB", sql.upper())
        self.assertIn("GRANT INSERT (", sql)
        self.assertIn("GRANT SELECT ON TABLE armi.audit_events TO armi_runtime", sql)
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:UPDATE|DELETE|TRUNCATE)\s+ON\s+(?:TABLE\s+)?"
                r"armi\.audit_events\s+TO\s+armi_runtime\b"
            ),
        )
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:durable_work|outbox_items|"
                r"CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )

    def test_creator_input_migration_has_only_the_s021_authority_surface(
        self,
    ) -> None:
        sql = Path("schema/migrations/0010_creator_input_acceptance.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        for table in (
            "creator_input_interactions",
            "external_evidence",
            "opportunities",
        ):
            self.assertIn(f"CREATE TABLE armi.{table}", sql)
        self.assertIn("ADD COLUMN resumable_opportunity_count", sql)
        self.assertIn(
            "interaction_scenes_input_identity_unique",
            sql,
        )
        self.assertIn(
            "FOREIGN KEY (\n        scene_id,\n        subject_id,\n"
            "        creator_party_id\n    ) REFERENCES armi.interaction_scenes",
            sql,
        )
        self.assertNotIn("JSONB", sql.upper())
        scrubbed = sql.upper().replace(
            "GRANT UPDATE (RESUMABLE_OPPORTUNITY_COUNT)",
            "",
        )
        self.assertNotIn("GRANT UPDATE", scrubbed)
        self.assertNotIn("GRANT DELETE", sql.upper())

    def test_runtime_module_has_no_upgrade_reference(self) -> None:
        source = Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("upgrade_operator_schema", source)
        self.assertNotIn(".upgrade(", source)

    def test_context_migration_has_only_the_s023_authority_surface(self) -> None:
        sql = Path(
            "schema/migrations/0011_context_snapshot_and_compilation.sql"
        ).read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertIn("CREATE TABLE armi.cognitive_episodes", sql)
        self.assertIn("CREATE TABLE armi.cognitive_context_items", sql)
        self.assertIn("ADD COLUMN resumable_cognitive_episode_count", sql)
        self.assertIn(
            "mechanism_identity = 'armi.context-compiler.deterministic-v1'",
            sql,
        )
        self.assertNotIn("MODEL", sql.upper())
        self.assertNotIn("GRANT DELETE", sql.upper())
        self.assertNotIn("GRANT TRUNCATE", sql.upper())

    def test_candidate_validation_migration_has_only_the_s025_surface(self) -> None:
        sql = Path(
            "schema/migrations/0013_cognition_candidate_validation.sql"
        ).read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE TABLE"), 3)
        for table in (
            "cognitive_candidate_validations",
            "cognitive_candidate_validation_items",
            "cognitive_candidate_basis_links",
        ):
            self.assertIn(f"CREATE TABLE armi.{table}", sql)
        self.assertIn("armi.cognition-candidate.v2", sql)
        self.assertIn("ADD COLUMN resumable_candidate_validation_count", sql)
        self.assertNotIn("GRANT DELETE", sql.upper())
        self.assertNotIn("GRANT TRUNCATE", sql.upper())
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:subject_commits|memory_items|relationships|"
                r"activities|effects|action_intents)\b"
            ),
        )

    def test_subject_commit_migration_has_only_the_s026_surface(self) -> None:
        sql = Path("schema/migrations/0014_t03_subject_commit.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 4)
        for table in (
            "subject_commits",
            "accepted_experiences",
            "experience_evidence_links",
            "cognitive_candidate_applications",
        ):
            self.assertIn(f"CREATE TABLE armi.{table}", sql)
        self.assertIn("ADD COLUMN resumable_subject_commit_count", sql)
        self.assertNotIn("GRANT DELETE", sql.upper())
        self.assertNotIn("GRANT TRUNCATE", sql.upper())

    def test_response_migration_has_only_the_s028_surface(self) -> None:
        sql = Path(
            "schema/migrations/0016_response_and_formal_no_action.sql"
        ).read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE TABLE"), 4)
        for table in (
            "action_intents",
            "action_intent_revisions",
            "formal_no_action_decisions",
            "creator_response_operations",
        ):
            self.assertIn(f"CREATE TABLE armi.{table}", sql)
        self.assertIn("ADD COLUMN resumable_response_operation_count", sql)
        self.assertNotIn("CREATE TABLE armi.policy_decisions", sql)
        self.assertNotIn("CREATE TABLE armi.effects", sql)
        self.assertNotIn("GRANT DELETE", sql.upper())
        self.assertNotIn("GRANT TRUNCATE", sql.upper())

    def test_durable_work_migration_is_the_only_s014_surface(self) -> None:
        sql = Path("schema/migrations/0005_durable_work_and_outbox.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertIn("CREATE TABLE armi.durable_work", sql)
        self.assertIn("CREATE TABLE armi.outbox_items", sql)
        self.assertIn(
            "FOR UPDATE",
            Path(
                "apps/armi-runtime/src/armi_runtime/adapters/persistence/durable_work.py"
            ).read_text(encoding="utf-8"),
        )
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:effect_id|subject[s]?\\b|"
                r"CREATE\\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\\s+DEFAULT\\s+PRIVILEGES|SECURITY\\s+DEFINER)\b"
            ),
        )

    def test_unique_birth_migration_is_the_only_s015_surface(self) -> None:
        sql = Path("schema/migrations/0006_unique_birth.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(sql.count("CREATE TABLE"), 8)
        for table in (
            "subjects",
            "life_generations",
            "runtime_bundle_activations",
            "parties",
            "prompt_documents",
            "prompt_revisions",
            "subject_component_heads",
            "subject_component_revisions",
        ):
            self.assertIn(f"CREATE TABLE armi.{table}", sql)
        self.assertIn("ADD CONSTRAINT durable_work_subject_fk", sql)
        self.assertNotRegex(
            sql,
            re.compile(
                r"(?i)\b(?:runtime_instances|authority_lease|birth_records|"
                r"CREATE\s+(?:ROLE|FUNCTION|PROCEDURE|TRIGGER)|"
                r"ALTER\s+DEFAULT\s+PRIVILEGES|SECURITY\s+DEFINER)\b"
            ),
        )


if __name__ == "__main__":
    unittest.main()
