"""Switch semantic recall to local Qwen embeddings and lexical fusion."""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM armi.context_embedding_projections;

        ALTER TABLE armi.context_embedding_attempts
          DROP CONSTRAINT context_embedding_attempts_binding_check,
          DROP CONSTRAINT context_embedding_attempts_model_check,
          ADD CONSTRAINT context_embedding_attempts_binding_model_check CHECK (
            (model_binding =
               'armi.embedding.volcengine-ark-doubao-vision-250615-v1'
             AND provider_model = 'doubao-embedding-vision-250615')
            OR
            (model_binding =
               'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1'
             AND provider_model = 'Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0')
          );

        ALTER TABLE armi.context_embedding_projections
          ADD COLUMN retrieval_text text,
          DROP CONSTRAINT context_embedding_projections_binding_check,
          ADD CONSTRAINT context_embedding_projections_binding_check
            CHECK (model_binding =
              'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1');

        ALTER TABLE armi.context_embedding_projections
          ALTER COLUMN retrieval_text SET NOT NULL,
          ADD CONSTRAINT context_embedding_projections_retrieval_text_check
            CHECK (length(retrieval_text) BETWEEN 1 AND 2000);

        CREATE INDEX context_embedding_projections_retrieval_trgm_idx
          ON armi.context_embedding_projections
          USING gin (retrieval_text armi_extensions.gin_trgm_ops);
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
