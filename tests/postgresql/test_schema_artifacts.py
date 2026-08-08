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


def test_frozen_baseline_and_migration_plan_are_the_only_schema_sources() -> None:
    baseline = RESOURCE / "baseline"
    migrations = RESOURCE / "migrations"
    definitions = sorted(baseline.glob("*.sql"))
    assert definitions
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
    assert baseline["baseline_id"] == "0001_baseline"
    assert "schema_migrations" in baseline["tables"]
    assert migrations == {
        "baseline_id": "0001_baseline",
        "migrations": [],
        "schema_version": "armi.schema-migrations.v1",
    }


def test_baseline_contains_authoritative_schema_and_migration_ledger() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((RESOURCE / "baseline").glob("*.sql"))
    )
    assert "CREATE SCHEMA armi" in sql
    assert "CREATE TABLE armi.schema_migrations" in sql
    assert "CREATE TABLE armi.subjects" in sql
    assert "CREATE TABLE armi.activities" in sql
    assert "CREATE TABLE armi.maintenance_sessions" in sql
    assert "CREATE TABLE armi.subjective_memories" in sql
    assert "CREATE TABLE armi.relationships" in sql
    assert "CREATE TABLE armi.life_materials" in sql
    assert "CREATE TABLE armi.other_human_dialogue_decisions" in sql
    assert "CREATE TABLE armi.creator_exports" in sql
    assert "CREATE TABLE armi.deletion_orders" in sql


def test_gateway_exposes_baseline_install_and_explicit_migration() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert callable(PostgreSQLSchemaGateway.migrate)


def test_gateway_rejects_baseline_digest_drift(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    shutil.copytree(RESOURCE, schema)
    foundation = schema / "baseline/00_foundation.sql"
    foundation.write_text(
        foundation.read_text(encoding="utf-8") + "\n",
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
