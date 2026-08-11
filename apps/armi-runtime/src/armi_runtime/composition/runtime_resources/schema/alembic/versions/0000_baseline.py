"""Install the squashed ARMI baseline."""

from __future__ import annotations

from armi_runtime.composition.alembic_support import execute_schema_sql

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None

_DOCUMENTS = (
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
)


def upgrade() -> None:
    for name in _DOCUMENTS:
        execute_schema_sql("baseline", name)


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
