"""Add bounded ANN, lexical Top-K, and projection coverage state."""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX armi.context_embedding_projections_retrieval_trgm_idx;

        CREATE INDEX context_embedding_projections_retrieval_gist_idx
          ON armi.context_embedding_projections
          USING gist (
            retrieval_text armi_extensions.gist_trgm_ops(siglen=64)
          );

        CREATE INDEX context_embedding_projections_embedding_hnsw_idx
          ON armi.context_embedding_projections
          USING hnsw (
            (embedding::armi_extensions.halfvec(1024))
              armi_extensions.halfvec_cosine_ops
          ) WITH (m=16,ef_construction=128);

        CREATE TABLE armi.context_embedding_coverage (
          model_binding text PRIMARY KEY,
          coverage_state text NOT NULL,
          epoch bigint NOT NULL DEFAULT 1,
          scanning_epoch bigint,
          scan_found_missing boolean NOT NULL DEFAULT false,
          source_kind text,
          after_source_ref uuid,
          updated_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          CONSTRAINT context_embedding_coverage_binding_check CHECK (
            model_binding =
              'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1'
          ),
          CONSTRAINT context_embedding_coverage_state_check CHECK (
            coverage_state IN ('dirty','reconciling','complete')
          ),
          CONSTRAINT context_embedding_coverage_epoch_check CHECK (
            epoch > 0 AND (scanning_epoch IS NULL OR scanning_epoch > 0)
          ),
          CONSTRAINT context_embedding_coverage_cursor_check CHECK (
            (coverage_state='dirty'
              AND scanning_epoch IS NULL
              AND source_kind IS NULL
              AND after_source_ref IS NULL)
            OR
            (coverage_state='reconciling'
              AND scanning_epoch IS NOT NULL
              AND source_kind IN ('life_material','subjective_memory'))
            OR
            (coverage_state='complete'
              AND scanning_epoch IS NULL
              AND source_kind IS NULL
              AND after_source_ref IS NULL)
          )
        );

        INSERT INTO armi.context_embedding_coverage (
          model_binding,coverage_state,epoch
        ) VALUES (
          'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1','dirty',1
        );

        GRANT SELECT ON armi.context_embedding_coverage TO armi_admin;
        GRANT SELECT,INSERT,UPDATE ON armi.context_embedding_coverage TO armi_runtime;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
