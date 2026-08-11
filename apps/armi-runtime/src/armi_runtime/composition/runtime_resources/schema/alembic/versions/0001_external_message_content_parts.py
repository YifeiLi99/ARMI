"""Add durable external-message content parts and recognition custody."""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.party_input_interactions
          ADD COLUMN cognition_content_digest text,
          ADD COLUMN recognition_status text NOT NULL DEFAULT 'not_required',
          ADD CONSTRAINT party_input_interactions_recognition_status_check
            CHECK (recognition_status = ANY (ARRAY[
              'not_required','pending','succeeded','failed','unknown','skipped'
            ])),
          ADD CONSTRAINT party_input_interactions_cognition_digest_check
            CHECK (cognition_content_digest IS NULL OR
                   cognition_content_digest ~ '^sha256:[0-9a-f]{64}$');

        CREATE TABLE armi.external_message_parts (
          external_message_part_id uuid PRIMARY KEY,
          interaction_id uuid NOT NULL REFERENCES armi.party_input_interactions(interaction_id),
          ordinal smallint NOT NULL,
          part_kind text NOT NULL,
          text_value text,
          target_key text,
          external_locator text,
          declared_file_name text,
          declared_media_type text,
          declared_byte_size bigint,
          processing_status text NOT NULL,
          raw_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          interpretation_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          interpretation_text text,
          failure_code text,
          created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
          settled_at timestamptz(6),
          UNIQUE (interaction_id, ordinal),
          CONSTRAINT external_message_parts_id_check
            CHECK (uuid_extract_version(external_message_part_id) = 7),
          CONSTRAINT external_message_parts_ordinal_check CHECK (ordinal BETWEEN 1 AND 64),
          CONSTRAINT external_message_parts_kind_check
            CHECK (part_kind = ANY (ARRAY[
              'text','mention','reply','face','image','audio','video','file','unknown'
            ])),
          CONSTRAINT external_message_parts_status_check
            CHECK (processing_status = ANY (ARRAY[
              'not_required','pending','succeeded','failed','unknown','skipped'
            ])),
          CONSTRAINT external_message_parts_size_check
            CHECK (declared_byte_size IS NULL OR declared_byte_size >= 0),
          CONSTRAINT external_message_parts_shape_check CHECK (
            (part_kind IN ('text','face','unknown') AND text_value IS NOT NULL
              AND target_key IS NULL AND external_locator IS NULL)
            OR
            (part_kind IN ('mention','reply') AND text_value IS NULL
              AND target_key IS NOT NULL AND external_locator IS NULL)
            OR
            (part_kind IN ('image','audio','video','file') AND text_value IS NULL
              AND target_key IS NULL AND external_locator IS NOT NULL)
          ),
          CONSTRAINT external_message_parts_settlement_check CHECK (
            (processing_status = 'pending' AND settled_at IS NULL
              AND interpretation_artifact_id IS NULL
              AND interpretation_text IS NULL AND failure_code IS NULL)
            OR
            (processing_status = 'not_required' AND settled_at IS NULL
              AND raw_artifact_id IS NULL AND interpretation_artifact_id IS NULL
              AND interpretation_text IS NULL AND failure_code IS NULL)
            OR
            (processing_status = 'skipped' AND settled_at IS NOT NULL
              AND raw_artifact_id IS NULL AND interpretation_artifact_id IS NULL
              AND interpretation_text IS NULL AND failure_code IS NULL)
            OR
            (processing_status = 'succeeded' AND settled_at IS NOT NULL
              AND interpretation_artifact_id IS NOT NULL
              AND interpretation_text IS NOT NULL AND failure_code IS NULL)
            OR
            (processing_status IN ('failed','unknown') AND settled_at IS NOT NULL
              AND interpretation_artifact_id IS NULL AND interpretation_text IS NULL
              AND failure_code IS NOT NULL)
          )
        );

        CREATE INDEX external_message_parts_interaction_idx
          ON armi.external_message_parts (interaction_id, ordinal);
        CREATE INDEX external_message_parts_pending_idx
          ON armi.external_message_parts (processing_status, interaction_id)
          WHERE processing_status = 'pending';

        CREATE TABLE armi.external_content_recognition_attempts (
          recognition_attempt_id uuid PRIMARY KEY,
          external_message_part_id uuid NOT NULL UNIQUE
            REFERENCES armi.external_message_parts(external_message_part_id),
          work_id uuid NOT NULL REFERENCES armi.durable_work(work_id),
          work_attempt_id uuid NOT NULL,
          provider text NOT NULL,
          model_id text NOT NULL,
          request_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
          dispatch_status text NOT NULL,
          provider_request_id text,
          provider_model_id text,
          response_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          input_tokens integer,
          output_tokens integer,
          estimated_cost_microyuan bigint,
          result_status text,
          error_code text,
          dispatched_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
          settled_at timestamptz(6),
          CONSTRAINT external_content_recognition_attempts_id_check
            CHECK (uuid_extract_version(recognition_attempt_id) = 7),
          CONSTRAINT external_content_recognition_attempts_dispatch_check
            CHECK (dispatch_status IN ('dispatched','settled')),
          CONSTRAINT external_content_recognition_attempts_result_check
            CHECK (result_status IS NULL OR result_status IN ('succeeded','failed','unknown')),
          CONSTRAINT external_content_recognition_attempts_usage_check
            CHECK ((input_tokens IS NULL OR input_tokens >= 0)
              AND (output_tokens IS NULL OR output_tokens >= 0)
              AND (estimated_cost_microyuan IS NULL OR estimated_cost_microyuan >= 0)),
          CONSTRAINT external_content_recognition_attempts_settlement_check CHECK (
            (dispatch_status = 'dispatched' AND result_status IS NULL
              AND settled_at IS NULL AND response_artifact_id IS NULL AND error_code IS NULL)
            OR
            (dispatch_status = 'settled' AND result_status IS NOT NULL
              AND settled_at IS NOT NULL
              AND ((result_status = 'succeeded' AND response_artifact_id IS NOT NULL
                    AND error_code IS NULL)
                   OR (result_status IN ('failed','unknown') AND error_code IS NOT NULL)))
          )
        );

        ALTER TABLE armi.external_message_parts OWNER TO armi_owner;
        ALTER TABLE armi.external_content_recognition_attempts OWNER TO armi_owner;
        REVOKE ALL ON TABLE armi.external_message_parts FROM PUBLIC;
        REVOKE ALL ON TABLE armi.external_content_recognition_attempts FROM PUBLIC;
        GRANT SELECT,INSERT,UPDATE ON TABLE armi.external_message_parts TO armi_runtime;
        GRANT SELECT,INSERT,UPDATE ON TABLE armi.external_content_recognition_attempts TO armi_runtime;
        GRANT SELECT,DELETE ON TABLE armi.external_message_parts TO armi_admin;
        GRANT SELECT,DELETE ON TABLE armi.external_content_recognition_attempts TO armi_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
