from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from armi_runtime.adapters.database_errors import DatabaseViolation
from armi_runtime.adapters.persistence.schema_gateway import (
    PostgreSQLSchemaGateway,
)

RESOURCE = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
BASELINE_DOCUMENTS = [
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


def _script(root: Path = RESOURCE) -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config)


def test_schema_resources_use_one_linear_alembic_history() -> None:
    assert sorted(path.name for path in (RESOURCE / "baseline").glob("*.sql")) == (
        BASELINE_DOCUMENTS
    )
    assert not (RESOURCE / "migrations").exists()
    assert not list(RESOURCE.glob("**/manifest.json"))
    script = _script()
    assert script.get_heads() == ["0015"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [revision.revision for revision in reversed(revisions)] == [
        "0000",
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        "0006",
        "0007",
        "0008",
        "0009",
        "0010",
        "0011",
        "0012",
        "0013",
        "0014",
        "0015",
    ]


def test_baseline_contains_authoritative_schema() -> None:
    sql = "\n".join(
        (RESOURCE / "baseline" / name).read_text(encoding="utf-8")
        for name in BASELINE_DOCUMENTS
    )
    assert "CREATE TABLE armi.subjects" in sql
    assert "CREATE TABLE armi.activities" in sql
    assert "CREATE TABLE armi.maintenance_sessions" in sql
    assert "CREATE TABLE armi.subjective_memories" in sql
    assert "CREATE TABLE armi.relationships" in sql
    assert "CREATE TABLE armi.life_materials" in sql
    assert "CREATE TABLE armi.dialogue_decisions" in sql
    assert "CREATE TABLE armi.creator_exports" in sql
    assert "CREATE TABLE armi.deletion_orders" in sql
    assert "CREATE TABLE armi.schema_migrations" not in sql
    assert "external.private.message.send" in sql


def test_active_cognition_contracts_have_a_forward_schema_revision() -> None:
    migration = (
        RESOURCE / "alembic/versions/0008_cognition_candidate_contracts.py"
    ).read_text(encoding="utf-8")
    for contract in (
        "armi.creator-dialogue-candidate.v21",
        "armi.creator-dialogue-candidate.v22",
        "armi.other-human-dialogue-candidate.v4",
    ):
        assert contract in migration
    assert "cognitive_attempts_candidate_schema_version_check" in migration
    assert (
        "cognitive_candidate_validation_candidate_contract_version_check" in migration
    )
    branches = (
        RESOURCE / "alembic/versions/0011_creator_cognition_branches.py"
    ).read_text(encoding="utf-8")
    assert "armi.creator-response-candidate.v1" in branches
    assert "armi.creator-appraisal-candidate.v1" in branches
    assert "armi.creator-dialogue-aggregate.v1" in branches
    assert "cognition_maintenance_batches" in branches
    assert "processed_through_experience_id" in branches
    assert "late_response_artifact_id" in branches
    assert "reflect_self','reflect_mind','reflect_prompt" in branches


def test_gateway_exposes_install_status_and_explicit_migration() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert callable(PostgreSQLSchemaGateway.status)
    assert callable(PostgreSQLSchemaGateway.migrate)


def test_gateway_rejects_multiple_alembic_heads(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    shutil.copytree(RESOURCE, schema)
    (schema / "alembic/versions/0001_parallel_probe.py").write_text(
        "revision = 'parallel'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade(): pass\n"
        "def downgrade(): pass\n",
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
