"""Reduce trigram KNN false positives with a wider GiST signature."""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX armi.context_embedding_projections_retrieval_gist_idx;

        CREATE INDEX context_embedding_projections_retrieval_gist_idx
          ON armi.context_embedding_projections
          USING gist (
            retrieval_text armi_extensions.gist_trgm_ops(siglen=256)
          );
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
