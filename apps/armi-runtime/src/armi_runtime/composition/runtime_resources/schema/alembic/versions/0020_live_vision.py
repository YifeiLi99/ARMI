"""Add durable private observations for a persistent USB camera."""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE armi.live_vision_sessions (
          session_id uuid PRIMARY KEY CHECK (uuid_extract_version(session_id)=7),
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          state text NOT NULL CHECK (state IN (
            'starting','observing','degraded','unavailable','stopping','stopped','failed')),
          device_name text NOT NULL CHECK (length(btrim(device_name)) BETWEEN 1 AND 512),
          device_path text NOT NULL CHECK (length(btrim(device_path)) BETWEEN 1 AND 1024),
          usb_location_id text NOT NULL CHECK (length(btrim(usb_location_id)) BETWEEN 1 AND 512),
          backend text NOT NULL CHECK (backend='DSHOW'),
          width integer NOT NULL CHECK (width=1280),
          height integer NOT NULL CHECK (height=720),
          fps integer NOT NULL CHECK (fps=5),
          started_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          ended_at timestamptz(6),
          error_code text CHECK (error_code IS NULL OR error_code ~ '^VISION-[A-Z0-9-]{1,120}$'),
          CHECK ((state IN ('stopped','failed'))=(ended_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX live_vision_one_open_session
          ON armi.live_vision_sessions(subject_id) WHERE ended_at IS NULL;

        CREATE TABLE armi.live_vision_observations (
          observation_id uuid PRIMARY KEY CHECK (uuid_extract_version(observation_id)=7),
          session_id uuid NOT NULL REFERENCES armi.live_vision_sessions(session_id),
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          observation_no bigint NOT NULL CHECK (observation_no>0),
          trigger_kind text NOT NULL CHECK (trigger_kind IN (
            'initial','scene_change','periodic_refresh','manual')),
          status text NOT NULL CHECK (status IN (
            'registered','recognizing','completed','failed','unknown')),
          change_score double precision CHECK (change_score BETWEEN 0 AND 1),
          change_class text CHECK (change_class IN ('none','minor','notable','uncertain')),
          scene_summary text CHECK (scene_summary IS NULL OR length(scene_summary) BETWEEN 1 AND 2048),
          visible_change text CHECK (visible_change IS NULL OR length(visible_change) BETWEEN 1 AND 2048),
          uncertainty text CHECK (uncertainty IS NULL OR length(uncertainty) BETWEEN 1 AND 1024),
          provider text,
          model_id text,
          input_tokens integer CHECK (input_tokens IS NULL OR input_tokens>=0),
          output_tokens integer CHECK (output_tokens IS NULL OR output_tokens>=0),
          evidence_id uuid,
          registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          settled_at timestamptz(6),
          error_code text CHECK (error_code IS NULL OR error_code ~ '^VISION-[A-Z0-9-]{1,120}$'),
          UNIQUE(session_id,observation_no),
          CHECK (
            (status IN ('registered','recognizing') AND settled_at IS NULL)
            OR (status='completed' AND settled_at IS NOT NULL AND scene_summary IS NOT NULL
                AND visible_change IS NOT NULL AND change_class IS NOT NULL AND error_code IS NULL)
            OR (status IN ('failed','unknown') AND settled_at IS NOT NULL AND error_code IS NOT NULL)
          )
        );

        CREATE TABLE armi.live_vision_observation_frames (
          observation_id uuid NOT NULL REFERENCES armi.live_vision_observations(observation_id),
          ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 4),
          artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          content_digest text NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
          byte_size bigint NOT NULL CHECK (byte_size>0),
          width integer NOT NULL CHECK (width>0),
          height integer NOT NULL CHECK (height>0),
          captured_at timestamptz(6) NOT NULL,
          purge_after timestamptz(6) NOT NULL,
          purged_at timestamptz(6),
          PRIMARY KEY(observation_id,ordinal),
          CHECK (purge_after>captured_at),
          CHECK ((artifact_id IS NULL)=(purged_at IS NOT NULL))
        );

        CREATE TABLE armi.visual_recognition_attempts (
          visual_attempt_id uuid PRIMARY KEY CHECK (uuid_extract_version(visual_attempt_id)=7),
          observation_id uuid NOT NULL REFERENCES armi.live_vision_observations(observation_id),
          attempt_no smallint NOT NULL DEFAULT 1 CHECK (attempt_no=1),
          provider text NOT NULL,
          model_id text NOT NULL,
          request_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
          response_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          provider_request_id text,
          status text NOT NULL CHECK (status IN ('prepared','dispatched','succeeded','failed','unknown')),
          input_tokens integer CHECK (input_tokens IS NULL OR input_tokens>=0),
          output_tokens integer CHECK (output_tokens IS NULL OR output_tokens>=0),
          error_code text CHECK (error_code IS NULL OR error_code ~ '^VISION-[A-Z0-9-]{1,120}$'),
          prepared_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          dispatched_at timestamptz(6),
          settled_at timestamptz(6),
          UNIQUE(observation_id,attempt_no),
          CHECK (
            (status='prepared' AND dispatched_at IS NULL AND settled_at IS NULL)
            OR (status='dispatched' AND dispatched_at IS NOT NULL AND settled_at IS NULL)
            OR (status='succeeded' AND dispatched_at IS NOT NULL AND settled_at IS NOT NULL
                AND response_artifact_id IS NOT NULL AND error_code IS NULL)
            OR (status IN ('failed','unknown') AND settled_at IS NOT NULL AND error_code IS NOT NULL)
          )
        );

        ALTER TABLE armi.external_evidence
          ALTER COLUMN scene_id DROP NOT NULL,
          ADD COLUMN visual_observation_id uuid REFERENCES armi.live_vision_observations(observation_id),
          DROP CONSTRAINT external_evidence_source_identity_check,
          DROP CONSTRAINT external_evidence_source_kind_check,
          ADD CONSTRAINT external_evidence_source_kind_check CHECK (source_kind IN (
            'creator_input','web_search','codex_task_source','codex_result','other_human_input','visual_observation')),
          ADD CONSTRAINT external_evidence_source_identity_check CHECK (
            (source_kind IN ('creator_input','other_human_input') AND interaction_id IS NOT NULL
              AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL
              AND codex_task_source_id IS NULL AND codex_verification_id IS NULL AND visual_observation_id IS NULL)
            OR (source_kind='web_search' AND interaction_id IS NULL AND web_observation_request_id IS NOT NULL
              AND observation_attempt_id IS NOT NULL AND codex_task_source_id IS NULL
              AND codex_verification_id IS NULL AND visual_observation_id IS NULL)
            OR (source_kind='codex_task_source' AND interaction_id IS NULL AND web_observation_request_id IS NULL
              AND observation_attempt_id IS NULL AND codex_task_source_id IS NOT NULL
              AND codex_verification_id IS NULL AND visual_observation_id IS NULL)
            OR (source_kind='codex_result' AND interaction_id IS NULL AND web_observation_request_id IS NULL
              AND observation_attempt_id IS NULL AND codex_task_source_id IS NULL
              AND codex_verification_id IS NOT NULL AND visual_observation_id IS NULL)
            OR (source_kind='visual_observation' AND interaction_id IS NULL AND scene_id IS NULL
              AND context_party_id IS NULL AND web_observation_request_id IS NULL
              AND observation_attempt_id IS NULL AND codex_task_source_id IS NULL
              AND codex_verification_id IS NULL AND visual_observation_id IS NOT NULL
              AND privacy_scope='private')
          );
        ALTER TABLE armi.live_vision_observations
          ADD CONSTRAINT live_vision_observation_evidence_fkey
          FOREIGN KEY(evidence_id) REFERENCES armi.external_evidence(evidence_id);

        ALTER TABLE armi.opportunities
          DROP CONSTRAINT opportunities_purpose_check,
          ADD CONSTRAINT opportunities_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task','consider_codex_result',
            'consider_autonomous_life','consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','consider_creator_outreach','consider_other_human_input',
            'consider_visual_observation')),
          DROP CONSTRAINT opportunities_source_shape_check,
          ADD CONSTRAINT opportunities_source_shape_check CHECK (
            (source_kind='external_evidence' AND evidence_id=source_ref AND activity_id IS NULL
              AND ((purpose='consider_visual_observation' AND scene_id IS NULL AND context_party_id IS NULL)
                OR (purpose<>'consider_visual_observation' AND scene_id IS NOT NULL AND context_party_id IS NOT NULL)))
            OR (source_kind IN ('life_generation_available','subject_component_revision','maintenance_window',
                'maintenance_phase_revision','life_material_revision') AND evidence_id IS NULL
                AND scene_id IS NULL AND context_party_id IS NULL AND activity_id IS NULL)
            OR (source_kind='activity_revision' AND evidence_id IS NULL AND scene_id IS NULL
                AND context_party_id IS NULL AND activity_id IS NOT NULL)
            OR (source_kind IN ('life_query_result','creator_outreach_absence','creator_outreach_relationship')
                AND evidence_id IS NULL AND scene_id IS NOT NULL AND context_party_id IS NOT NULL AND activity_id IS NULL)
            OR (source_kind='creator_outreach_activity' AND evidence_id IS NULL AND scene_id IS NOT NULL
                AND context_party_id IS NOT NULL AND activity_id IS NOT NULL)
          );

        ALTER TABLE armi.accepted_experiences
          ALTER COLUMN scene_id DROP NOT NULL,
          DROP CONSTRAINT accepted_experiences_experience_kind_check,
          ADD CONSTRAINT accepted_experiences_experience_kind_check CHECK (experience_kind IN (
            'creator_input','web_observation','codex_observation','other_human_input','visual_observation')),
          DROP CONSTRAINT accepted_experiences_source_perspective_check,
          ADD CONSTRAINT accepted_experiences_source_perspective_check CHECK (source_perspective IN (
            'creator_claim','web_claim','codex_observation','other_human_claim','visual_model_observation')),
          DROP CONSTRAINT accepted_experiences_source_pair_check,
          ADD CONSTRAINT accepted_experiences_source_pair_check CHECK (
            (experience_kind='creator_input' AND source_perspective='creator_claim' AND scene_id IS NOT NULL)
            OR (experience_kind='web_observation' AND source_perspective='web_claim' AND scene_id IS NOT NULL)
            OR (experience_kind='codex_observation' AND source_perspective='codex_observation' AND scene_id IS NOT NULL)
            OR (experience_kind='other_human_input' AND source_perspective='other_human_claim' AND scene_id IS NOT NULL)
            OR (experience_kind='visual_observation' AND source_perspective='visual_model_observation'
                AND scene_id IS NULL AND fact_class IN ('external_claim','inference','unknown'))
          );

        ALTER TABLE armi.cognitive_episodes
          DROP CONSTRAINT cognitive_episodes_purpose_check,
          ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task','consider_codex_result',
            'consider_autonomous_life','consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','consider_creator_outreach','consider_other_human_input',
            'consider_visual_observation')),
          DROP CONSTRAINT cognitive_episodes_scene_shape_check,
          ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
            (purpose IN ('consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep','maintain_subjective_memory',
              'perform_subject_self_check','consider_visual_observation')
              AND scene_id IS NULL AND context_party_id IS NULL)
            OR (purpose NOT IN ('consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep','maintain_subjective_memory',
              'perform_subject_self_check','consider_visual_observation')
              AND scene_id IS NOT NULL AND context_party_id IS NOT NULL)
          );

        DO $constraints$
        DECLARE definition text;
        BEGIN
          SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
          WHERE conrelid='armi.cognitive_attempts'::regclass
            AND conname='cognitive_attempts_candidate_schema_version_check';
          EXECUTE 'ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check';
          definition := regexp_replace(definition, '\]\)\)\)$',
            ', ''armi.visual-observation-candidate.v1''::text])))');
          EXECUTE 'ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check ' || definition;

          SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
          WHERE conrelid='armi.cognitive_attempts'::regclass
            AND conname='cognitive_attempts_profile_check';
          EXECUTE 'ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_profile_check';
          definition := regexp_replace(definition, '\]\)\)\)$',
            ', ''visual_observation''::text])))');
          EXECUTE 'ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_profile_check ' || definition;

          SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
          WHERE conrelid='armi.cognitive_candidate_validations'::regclass
            AND conname='cognitive_candidate_validation_candidate_contract_version_check';
          EXECUTE 'ALTER TABLE armi.cognitive_candidate_validations DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check';
          definition := regexp_replace(definition, '\]\)\)\)$',
            ', ''armi.visual-observation-candidate.v1''::text])))');
          EXECUTE 'ALTER TABLE armi.cognitive_candidate_validations ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check ' || definition;
        END
        $constraints$;

        GRANT SELECT,INSERT,UPDATE ON armi.live_vision_sessions,
          armi.live_vision_observations, armi.live_vision_observation_frames,
          armi.visual_recognition_attempts TO armi_runtime;
        GRANT SELECT ON armi.live_vision_sessions, armi.live_vision_observations,
          armi.live_vision_observation_frames, armi.visual_recognition_attempts TO armi_admin;
        GRANT SELECT,INSERT,UPDATE(visual_observation_id) ON armi.external_evidence TO armi_runtime;
        GRANT SELECT(visual_observation_id) ON armi.external_evidence TO armi_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
