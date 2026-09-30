"""Bridge the verified mutable baseline to immutable forward migrations."""

from __future__ import annotations

from armi_postgresql_contract.alembic_support import (
    execute_schema_sql,
    finalize_schema_identity,
)

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_schema_sql("migrations", "0001_restore_forward_migrations.sql")
    finalize_schema_identity()


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
