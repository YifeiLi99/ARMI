from __future__ import annotations

from pathlib import Path

from armi_runtime.adapters.persistence.schema_gateway import (
    PostgreSQLSchemaGateway,
)

RESOURCE = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)


def test_current_schema_is_the_only_database_definition() -> None:
    current = RESOURCE / "current"
    definitions = sorted(current.glob("*.sql"))
    assert definitions
    assert not Path("schema").exists()
    assert not (RESOURCE / "migrations").exists()
    assert not (RESOURCE / "manifests").exists()
    assert not any((RESOURCE / "checks").glob("*.sql"))
    assert not any(RESOURCE.rglob("*.json"))


def test_current_schema_has_no_migration_ledger() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((RESOURCE / "current").glob("*.sql"))
    )
    assert "schema_migrations" not in sql
    assert "CREATE SCHEMA armi" in sql
    assert "CREATE TABLE armi.subjects" in sql
    assert "CREATE TABLE armi.activities" in sql
    assert "CREATE TABLE armi.maintenance_sessions" in sql
    assert "CREATE TABLE armi.subjective_memories" in sql
    assert "CREATE TABLE armi.subjective_memory_revisions" in sql
    assert "CREATE TABLE armi.memory_relations" in sql
    assert "accessibility IN ('available', 'faded', 'forgotten')" in sql
    assert "wake_request_id" in sql
    assert "schema_migrations" not in sql


def test_gateway_exposes_empty_database_install_not_upgrade() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert not hasattr(PostgreSQLSchemaGateway, "upgrade")


def test_admin_package_has_no_schema_governance_manifest() -> None:
    resources = Path("apps/armi-admin/src/armi_admin/mcp/resources")
    assert sorted(path.name for path in resources.glob("*.json")) == [
        "admin-config.schema.json"
    ]
