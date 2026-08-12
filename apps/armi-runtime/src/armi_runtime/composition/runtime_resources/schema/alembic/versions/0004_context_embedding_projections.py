"""Add rebuildable semantic-recall projections and their attempt ledger."""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.cognitive_attempts
          DROP CONSTRAINT cognitive_attempts_profile_check,
          ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
            profile IN (
              'creator_input_cognition','creator_dialogue','creator_outreach',
              'other_human_dialogue','autonomous_activity',
              'activity_attention','activity_internal_work','sleep_decision',
              'memory_maintenance','subject_self_check',
              'web_evidence_cognition','codex_task','codex_result'
            )
          );

        ALTER TABLE armi.cognitive_episodes
          DROP CONSTRAINT cognitive_episodes_mechanism_identity_check,
          ADD CONSTRAINT cognitive_episodes_mechanism_identity_check
            CHECK (mechanism_identity IN (
              'armi.context-compiler.deterministic-v1',
              'armi.context-compiler.layered-v2'
            ));

        CREATE TABLE armi.context_embedding_attempts (
          context_embedding_attempt_id uuid PRIMARY KEY,
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          life_generation_id uuid NOT NULL
            REFERENCES armi.life_generations(life_generation_id),
          source_kind text NOT NULL,
          source_ref uuid NOT NULL,
          source_version bigint NOT NULL,
          chunk_ordinal integer NOT NULL,
          model_binding text NOT NULL,
          provider_model text NOT NULL,
          input_digest text NOT NULL,
          status text NOT NULL,
          provider_request_id text,
          input_tokens bigint,
          error_code text,
          prepared_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          dispatched_at timestamptz(6),
          settled_at timestamptz(6),
          CONSTRAINT context_embedding_attempts_id_check
            CHECK (uuid_extract_version(context_embedding_attempt_id) = 7),
          CONSTRAINT context_embedding_attempts_source_kind_check
            CHECK (source_kind IN ('subjective_memory','life_material')),
          CONSTRAINT context_embedding_attempts_source_version_check
            CHECK (source_version > 0),
          CONSTRAINT context_embedding_attempts_source_ref_check
            CHECK (uuid_extract_version(source_ref) = 7),
          CONSTRAINT context_embedding_attempts_chunk_ordinal_check
            CHECK (chunk_ordinal >= 0),
          CONSTRAINT context_embedding_attempts_status_check
            CHECK (status IN ('prepared','dispatched','succeeded','failed')),
          CONSTRAINT context_embedding_attempts_input_tokens_check
            CHECK (input_tokens IS NULL OR input_tokens >= 0),
          CONSTRAINT context_embedding_attempts_input_digest_check
            CHECK (input_digest ~ '^sha256:[0-9a-f]{64}$'),
          CONSTRAINT context_embedding_attempts_binding_check
            CHECK (model_binding =
              'armi.embedding.volcengine-ark-doubao-vision-250615-v1'),
          CONSTRAINT context_embedding_attempts_model_check
            CHECK (provider_model = 'doubao-embedding-vision-250615'),
          CONSTRAINT context_embedding_attempts_error_check
            CHECK ((status = 'failed') = (error_code IS NOT NULL)),
          CONSTRAINT context_embedding_attempts_settlement_check
            CHECK ((status IN ('succeeded','failed')) = (settled_at IS NOT NULL)),
          UNIQUE (
            source_kind, source_ref, source_version, chunk_ordinal,
            model_binding, context_embedding_attempt_id
          )
        );

        CREATE TABLE armi.context_embedding_projections (
          context_embedding_projection_id uuid PRIMARY KEY,
          context_embedding_attempt_id uuid NOT NULL UNIQUE
            REFERENCES armi.context_embedding_attempts(context_embedding_attempt_id),
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          life_generation_id uuid NOT NULL
            REFERENCES armi.life_generations(life_generation_id),
          source_kind text NOT NULL,
          source_ref uuid NOT NULL,
          source_version bigint NOT NULL,
          chunk_ordinal integer NOT NULL,
          chunk_text text NOT NULL,
          model_binding text NOT NULL,
          embedding armi_extensions.vector(1024) NOT NULL,
          created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          CONSTRAINT context_embedding_projections_id_check
            CHECK (uuid_extract_version(context_embedding_projection_id) = 7),
          CONSTRAINT context_embedding_projections_source_kind_check
            CHECK (source_kind IN ('subjective_memory','life_material')),
          CONSTRAINT context_embedding_projections_source_version_check
            CHECK (source_version > 0),
          CONSTRAINT context_embedding_projections_source_ref_check
            CHECK (uuid_extract_version(source_ref) = 7),
          CONSTRAINT context_embedding_projections_chunk_ordinal_check
            CHECK (chunk_ordinal >= 0),
          CONSTRAINT context_embedding_projections_chunk_text_check
            CHECK (length(chunk_text) BETWEEN 1 AND 1500),
          CONSTRAINT context_embedding_projections_binding_check
            CHECK (model_binding =
              'armi.embedding.volcengine-ark-doubao-vision-250615-v1'),
          UNIQUE (
            source_kind, source_ref, source_version, chunk_ordinal, model_binding
          )
        );

        CREATE INDEX context_embedding_projections_current_source_idx
          ON armi.context_embedding_projections (
            subject_id, life_generation_id, source_kind, source_ref,
            source_version, model_binding
          );

        CREATE VIEW armi.context_model_cache_hit_ratios AS
          SELECT episode.purpose,
                 count(*) FILTER (
                   WHERE attempt.result_status = 'succeeded'
                 ) AS succeeded_attempts,
                 count(*) FILTER (
                   WHERE attempt.result_status = 'succeeded'
                     AND attempt.cached_input_tokens > 0
                 ) AS cache_hit_attempts,
                 COALESCE(sum(attempt.cached_input_tokens) FILTER (
                   WHERE attempt.result_status = 'succeeded'
                 ), 0) AS cached_input_tokens,
                 COALESCE(sum(attempt.input_tokens) FILTER (
                   WHERE attempt.result_status = 'succeeded'
                 ), 0) AS input_tokens,
                 CASE
                   WHEN COALESCE(sum(attempt.input_tokens) FILTER (
                     WHERE attempt.result_status = 'succeeded'
                   ), 0) = 0 THEN 0::numeric
                   ELSE
                     COALESCE(sum(attempt.cached_input_tokens) FILTER (
                       WHERE attempt.result_status = 'succeeded'
                     ), 0)::numeric
                     / sum(attempt.input_tokens) FILTER (
                       WHERE attempt.result_status = 'succeeded'
                     )
                 END AS cached_input_ratio
          FROM armi.cognitive_episodes AS episode
          JOIN armi.cognitive_attempts AS attempt
            ON attempt.cognitive_episode_id = episode.cognitive_episode_id
          GROUP BY episode.purpose;

        GRANT SELECT ON armi.context_embedding_attempts TO armi_admin;
        GRANT SELECT,INSERT,UPDATE ON armi.context_embedding_attempts TO armi_runtime;
        GRANT SELECT ON armi.context_embedding_projections TO armi_admin;
        GRANT SELECT,INSERT,DELETE ON armi.context_embedding_projections TO armi_runtime;
        GRANT SELECT ON armi.context_model_cache_hit_ratios TO armi_admin;
        GRANT SELECT ON armi.context_model_cache_hit_ratios TO armi_runtime;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
