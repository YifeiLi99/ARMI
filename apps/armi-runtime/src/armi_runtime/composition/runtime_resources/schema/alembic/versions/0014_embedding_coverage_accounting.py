"""Track pending Context projection work without crossing owner boundaries."""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.context_embedding_coverage
          ADD COLUMN pending_work_count bigint NOT NULL DEFAULT 0,
          ADD CONSTRAINT context_embedding_coverage_pending_check
            CHECK (pending_work_count >= 0);
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
