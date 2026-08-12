"""Remove the duplicated Runtime composition manifest contract."""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.runtime_bundle_activations
          DROP COLUMN bundle_digest,
          DROP COLUMN manifest_artifact_id;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
