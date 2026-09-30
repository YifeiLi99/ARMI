"""Admit the dedicated Jev profile used by finite cognition decisions."""

from armi_postgresql_contract.alembic_support import (
    execute_schema_sql,
    finalize_schema_identity,
)

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_schema_sql("migrations", "0002_allow_bounded_decision_profile.sql")
    finalize_schema_identity()


def downgrade() -> None:
    raise RuntimeError("DB-SCHEMA-FORWARD-ONLY")
