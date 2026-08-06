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
    assert "CREATE TABLE armi.relationships" in sql
    assert "CREATE TABLE armi.relationship_revisions" in sql
    assert "CREATE TABLE armi.relationship_experience_links" in sql
    assert "CREATE TABLE armi.life_materials" in sql
    assert "CREATE TABLE armi.life_material_revisions" in sql
    assert "material_kind IN ('diary', 'work', 'collection', 'draft')" in sql
    assert "FOREIGN KEY (owner_party_id, subject_id)" in sql
    assert "UNIQUE (subject_commit_id, proposal_ref)" in sql
    assert "life_materials_current_revision_fk" in sql
    assert "'maintenance_window', 'life_material_revision'" in sql
    assert "'codex_result_rejected'" in sql
    assert "ACTION|CANDIDATE" in sql
    assert "'privacy_changed', 'deleted'" in sql
    assert "'creator_visible', 'private', 'shared', 'restricted'" in sql
    assert "revision_kind = 'updated'" in sql
    assert "privacy_status IN ('creator_visible', 'private')" in sql
    assert (
        "GRANT UPDATE (current_revision_id, head_version, deleted_at, updated_at)"
        in sql
    )
    assert "commitments jsonb NOT NULL" in sql
    assert "open_issues jsonb NOT NULL" in sql
    assert "supports_commitment_event" in sql
    assert "accessibility IN ('available', 'faded', 'forgotten')" in sql
    assert "wake_request_id" in sql
    assert "'birth', 'created', 'revised', 'deactivated'," in sql
    assert "'subject_created', 'subject_revised'" in sql
    assert "prompt_revisions_subject_commit_fk" in sql
    assert "GRANT UPDATE (current_revision_id, status)" in sql
    assert "CHECK (status = 'active' OR current_revision_id IS NOT NULL)" in sql
    assert "CHECK (subject_commit_id IS NULL)" in sql
    assert "schema_migrations" not in sql


def test_gateway_exposes_empty_database_install_not_upgrade() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert not hasattr(PostgreSQLSchemaGateway, "upgrade")


def test_admin_package_has_no_schema_governance_manifest() -> None:
    resources = Path("apps/armi-admin/src/armi_admin/mcp/resources")
    assert sorted(path.name for path in resources.glob("*.json")) == [
        "admin-config.schema.json"
    ]
