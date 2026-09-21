from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from armi_kernel.application import WorkType
from armi_runtime.adapters.database_errors import DatabaseViolation
from armi_runtime.adapters.persistence.schema_gateway import (
    PostgreSQLSchemaGateway,
)

RESOURCE = Path(
    "packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema"
)
BASELINE_DOCUMENTS = [
    "10_runtime_and_subject.sql",
    "20_artifacts_parties_interactions.sql",
    "30_cognition_and_provenance.sql",
    "40_life_memory_relationships.sql",
    "50_activities_and_maintenance.sql",
    "60_actions_work_and_effects.sql",
    "70_codex_audit_data_rights.sql",
    "75_admin_management.sql",
    "80_cross_domain_constraints_and_indexes.sql",
    "85_provider_usage.sql",
    "86_autonomy.sql",
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
    assert script.get_heads() == ["0000"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [revision.revision for revision in reversed(revisions)] == ["0000"]
    assert sorted(
        path.name for path in (RESOURCE / "alembic" / "versions").glob("*.py")
    ) == ["0000_baseline.py"]


def test_baseline_contains_authoritative_schema() -> None:
    sql = "\n".join(
        (RESOURCE / "baseline" / name).read_text(encoding="utf-8")
        for name in BASELINE_DOCUMENTS
    )
    assert "CREATE TABLE armi.subjects" in sql
    for removed in (
        "capability_requests",
        "capability_request_basis_links",
        "capability_request_decisions",
        "permission_grants",
        "policy_decisions",
        "effect_registrations",
        "action_intent_revisions",
        "action_intent_revision_id",
        "capability_request_id",
        "permission_grant_id",
        "policy_decision_id",
        "grant_ref",
        "policy_ref",
    ):
        assert re.search(rf"\b{removed}\b", sql) is None
    work_constraint = next(
        line
        for line in sql.splitlines()
        if "CONSTRAINT durable_work_work_kind_check" in line
    )
    assert set(re.findall(r"'([^']+)'::text", work_constraint)) == {
        kind.value for kind in WorkType
    }
    assert "CREATE TABLE armi.activity_revisions" in sql
    assert "CREATE TABLE armi.maintenance_sessions" in sql
    assert "CREATE TABLE armi.subjective_memory_revisions" in sql
    assert "CREATE TABLE armi.relationship_revisions" in sql
    assert "CREATE TABLE armi.life_material_revisions" in sql
    assert "CREATE TABLE armi.dialogue_decisions" not in sql
    assert "CREATE TABLE armi.creator_exports" in sql
    assert "CREATE TABLE armi.data_rights_orders" in sql
    assert "CREATE TABLE armi.schema_migrations" not in sql
    assert "external_private_delivery" in sql


def test_active_cognition_contracts_are_in_the_current_baseline() -> None:
    baseline = "\n".join(
        (RESOURCE / "baseline" / name).read_text(encoding="utf-8")
        for name in BASELINE_DOCUMENTS
    )
    for contract in (
        "armi.creator-dialogue-candidate.v26",
        "armi.other-human-dialogue-candidate.v9",
    ):
        assert contract in baseline
    assert "cognitive_attempts_candidate_schema_version_check" in baseline
    assert "armi.creator-cognitive-act-candidate.v8" in baseline
    assert "armi.creator-voice-act-candidate.v8" in baseline
    assert "maintenance_source_episode_id" in baseline
    assert "processed_through_ordinal" in baseline
    assert "acceptance_ordinal bigint GENERATED ALWAYS AS IDENTITY" in baseline
    assert "late_response_artifact_id" not in baseline
    assert "reflect_mood" in baseline
    for contract in (
        "armi.other-human-dialogue-candidate.v9",
        "armi.autonomous-activity-candidate.v12",
        "armi.activity-attention-candidate.v5",
        "armi.activity-internal-work-candidate.v5",
    ):
        assert contract in baseline
    assert "CREATE TABLE armi.mood_revisions" in baseline
    assert "semantic-anchors.v1" in baseline
    assert "derived_appraisal_payload" in baseline


def test_gateway_exposes_install_and_status_only() -> None:
    assert callable(PostgreSQLSchemaGateway.install)
    assert callable(PostgreSQLSchemaGateway.status)
    assert not hasattr(PostgreSQLSchemaGateway, "migrate")
    assert "armi.schema-baseline.v70" in (
        RESOURCE / "baseline" / "10_runtime_and_subject.sql"
    ).read_text(encoding="utf-8")


def test_gateway_rejects_multiple_alembic_heads(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    shutil.copytree(RESOURCE, schema)
    (schema / "alembic/versions/unsupported_parallel_probe.py").write_text(
        "revision = 'parallel'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade(): pass\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(DatabaseViolation) as raised:
        PostgreSQLSchemaGateway(resource_root=schema)
    assert raised.value.code == "DB-SCHEMA-RESOURCE"


def test_admin_package_has_no_second_schema_governance_manifest() -> None:
    resources = Path("apps/armi-admin/src/armi_admin/application/resources")
    assert sorted(path.name for path in resources.glob("*.json")) == [
        "admin-config.schema.json"
    ]
