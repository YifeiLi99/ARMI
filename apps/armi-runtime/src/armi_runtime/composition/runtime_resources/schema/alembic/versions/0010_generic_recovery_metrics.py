"""Allow owner-authored recovery metric identities."""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.runtime_recovery_metrics
          DROP CONSTRAINT runtime_recovery_metrics_kind_check,
          ADD CONSTRAINT runtime_recovery_metrics_kind_check
            CHECK (metric_kind ~ '^[a-z][a-z0-9._-]{0,127}$');
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
