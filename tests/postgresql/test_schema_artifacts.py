from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from armi_runtime.adapters.database_errors import DatabaseViolation
from armi_runtime.adapters.persistence.schema_gateway import (
    PostgreSQLSchemaGateway,
)

from tools.generate_schema_manifests import main as generate_schema_manifests

RESOURCE = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
BASELINE_DOCUMENTS = [
    "00_namespace.sql",
    "10_runtime_and_subject.sql",
    "20_artifacts_parties_interactions.sql",
    "30_cognition_and_provenance.sql",
    "40_life_memory_relationships.sql",
    "50_activities_and_maintenance.sql",
    "60_actions_work_and_effects.sql",
    "70_web_codex_audit_data_rights.sql",
    "80_cross_domain_constraints_and_indexes.sql",
    "90_static_catalog.sql",
    "99_privileges.sql",
]


def test_frozen_baseline_and_migration_plan_are_the_only_schema_sources() -> None:
    baseline = RESOURCE / "baseline"
    migrations = RESOURCE / "migrations"
    definitions = sorted(baseline.glob("*.sql"))
    assert [path.name for path in definitions] == BASELINE_DOCUMENTS
    assert not (baseline / "baseline.sql").exists()
    assert not (RESOURCE / "current").exists()
    assert (baseline / "manifest.json").is_file()
    assert (migrations / "manifest.json").is_file()
    assert not any((RESOURCE / "checks").glob("*.sql"))


def test_baseline_manifest_is_reproducible_and_declares_history() -> None:
    baseline_manifest = RESOURCE / "baseline/manifest.json"
    migration_manifest = RESOURCE / "migrations/manifest.json"
    before = (baseline_manifest.read_bytes(), migration_manifest.read_bytes())

    assert generate_schema_manifests() == 0

    after = (baseline_manifest.read_bytes(), migration_manifest.read_bytes())
    assert after == before
    baseline = json.loads(after[0])
    migrations = json.loads(after[1])
    assert baseline["schema_version"] == "armi.schema-baseline.v1"
    assert baseline["baseline_id"] == "baseline"
    assert [item["path"] for item in baseline["documents"]] == BASELINE_DOCUMENTS
    assert baseline["catalog_sha256"].startswith("sha256:")
    assert "schema_migrations" in baseline["tables"]
    assert migrations["baseline_id"] == "baseline"
    assert migrations["schema_version"] == "armi.schema-migrations.v1"
    assert [item["migration_id"] for item in migrations["migrations"]] == [
        "0001_harden_authoritative_schema"
    ]
    migration = migrations["migrations"][0]
    assert migration["creates_tables"] == ["runtime_recovery_metrics"]
    assert migration["drops_tables"] == []
    assert migration["sha256"].startswith("sha256:")
    assert migration["target_catalog_sha256"].startswith("sha256:")


def test_baseline_contains_authoritative_schema_and_migration_ledger() -> None:
    sql = "\n".join(
        (RESOURCE / "baseline" / name).read_text(encoding="utf-8")
        for name in BASELINE_DOCUMENTS
    )
    assert "CREATE SCHEMA armi" in sql
    assert "CREATE TABLE armi.schema_migrations" in sql
    assert "CREATE TABLE armi.subjects" in sql
    assert "CREATE TABLE armi.activities" in sql
    assert "CREATE TABLE armi.maintenance_sessions" in sql
    assert "CREATE TABLE armi.subjective_memories" in sql
    assert "CREATE TABLE armi.relationships" in sql
    assert "CREATE TABLE armi.life_materials" in sql
    assert "CREATE TABLE armi.dialogue_decisions" in sql
    assert "CREATE TABLE armi.creator_exports" in sql
    assert "CREATE TABLE armi.deletion_orders" in sql
    assert "INSERT INTO armi.capabilities VALUES" in sql
    assert "'creator.scene.reply'" in sql
    assert "'codex.delegated-work'" in sql
    assert "'local.other-human-inbox.deliver'" in sql
    for retired in (
        "creator_input_interactions",
        "other_human_input_interactions",
        "other_human_action_intents",
        "formal_no_action_decisions",
        "other_human_dialogue_decisions",
        "creator_response_operations",
        "other_human_effects",
        "creator_response_deliveries",
        "other_human_local_inbox_deliveries",
        "activity_attention_decisions",
        "activity_internal_work_decisions",
    ):
        assert retired not in sql


def test_gateway_exposes_baseline_install_and_explicit_migration() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert callable(PostgreSQLSchemaGateway.migrate)


def test_gateway_rejects_baseline_digest_drift(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    shutil.copytree(RESOURCE, schema)
    baseline = schema / "baseline/30_cognition_and_provenance.sql"
    baseline.write_text(
        baseline.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(DatabaseViolation) as raised:
        PostgreSQLSchemaGateway(resource_root=schema)

    assert raised.value.code == "DB-SCHEMA-RESOURCE"


def test_admin_package_has_no_second_schema_governance_manifest() -> None:
    resources = Path("apps/armi-admin/src/armi_admin/mcp/resources")
    assert sorted(path.name for path in resources.glob("*.json")) == [
        "admin-config.schema.json"
    ]
