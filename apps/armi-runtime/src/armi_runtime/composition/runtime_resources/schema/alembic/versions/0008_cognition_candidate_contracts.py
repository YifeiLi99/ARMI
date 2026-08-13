"""Accept the active modular cognition candidate contracts."""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_VERSIONS = """
  'armi.cognition-candidate.v1','armi.cognition-candidate.v2',
  'armi.cognition-candidate.v3','armi.cognition-candidate.v4',
  'armi.cognition-candidate.v5','armi.cognition-candidate.v6',
  'armi.cognition-candidate.v7',
  'armi.creator-dialogue-candidate.v5','armi.creator-dialogue-candidate.v6',
  'armi.creator-dialogue-candidate.v7','armi.creator-dialogue-candidate.v8',
  'armi.creator-dialogue-candidate.v9','armi.creator-dialogue-candidate.v10',
  'armi.creator-dialogue-candidate.v11','armi.creator-dialogue-candidate.v12',
  'armi.creator-dialogue-candidate.v13','armi.creator-dialogue-candidate.v14',
  'armi.creator-dialogue-candidate.v15','armi.creator-dialogue-candidate.v16',
  'armi.creator-dialogue-candidate.v17','armi.creator-dialogue-candidate.v18',
  'armi.creator-dialogue-candidate.v19','armi.creator-dialogue-candidate.v20',
  'armi.creator-dialogue-candidate.v21','armi.creator-dialogue-candidate.v22',
  'armi.autonomous-activity-candidate.v1',
  'armi.activity-attention-candidate.v1','armi.activity-attention-candidate.v2',
  'armi.activity-internal-work-candidate.v1','armi.sleep-decision-candidate.v1',
  'armi.maintenance-work-candidate.v1',
  'armi.other-human-dialogue-candidate.v1',
  'armi.other-human-dialogue-candidate.v2',
  'armi.other-human-dialogue-candidate.v3',
  'armi.other-human-dialogue-candidate.v4'
"""


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE armi.cognitive_attempts
          DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
          ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check
            CHECK (candidate_schema_version IN ({_VERSIONS}));

        ALTER TABLE armi.cognitive_candidate_validations
          DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
          ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check
            CHECK (candidate_contract_version IN ({_VERSIONS}));
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
