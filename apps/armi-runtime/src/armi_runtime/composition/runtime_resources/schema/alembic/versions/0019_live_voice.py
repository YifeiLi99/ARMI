"""Add durable ownership records for local real-time voice sessions."""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.party_input_interactions
          ADD COLUMN modality text NOT NULL DEFAULT 'text',
          ADD CONSTRAINT party_input_interactions_modality_check
            CHECK (modality IN ('text','media_file','live_voice'));

        GRANT SELECT(modality),INSERT(modality)
          ON armi.party_input_interactions TO armi_runtime;
        GRANT SELECT(modality)
          ON armi.party_input_interactions TO armi_admin;

        CREATE TABLE armi.live_voice_sessions (
          session_id uuid PRIMARY KEY,
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
          scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
          state text NOT NULL,
          context_version text,
          input_host_api text NOT NULL,
          input_device_name text NOT NULL,
          output_host_api text NOT NULL,
          output_device_name text NOT NULL,
          started_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          ended_at timestamptz(6),
          error_code text,
          CONSTRAINT live_voice_sessions_id_check
            CHECK (uuid_extract_version(session_id)=7),
          CONSTRAINT live_voice_sessions_state_check CHECK (
            state IN (
              'starting','listening','recognizing','thinking','speaking',
              'waiting_slow','stopped','failed','unavailable'
            )
          ),
          CONSTRAINT live_voice_sessions_context_check CHECK (
            context_version IS NULL OR length(context_version) BETWEEN 1 AND 128
          ),
          CONSTRAINT live_voice_sessions_device_check CHECK (
            length(btrim(input_host_api)) BETWEEN 1 AND 128
            AND length(btrim(input_device_name)) BETWEEN 1 AND 512
            AND length(btrim(output_host_api)) BETWEEN 1 AND 128
            AND length(btrim(output_device_name)) BETWEEN 1 AND 512
          ),
          CONSTRAINT live_voice_sessions_error_check CHECK (
            error_code IS NULL OR error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'
          ),
          CONSTRAINT live_voice_sessions_lifecycle_check CHECK (
            (state IN ('stopped','failed','unavailable')) = (ended_at IS NOT NULL)
          )
        );

        CREATE UNIQUE INDEX live_voice_one_open_session
          ON armi.live_voice_sessions(subject_id)
          WHERE ended_at IS NULL;

        CREATE TABLE armi.live_voice_turns (
          turn_id uuid PRIMARY KEY,
          session_id uuid NOT NULL
            REFERENCES armi.live_voice_sessions(session_id),
          turn_no bigint NOT NULL,
          interaction_id uuid
            REFERENCES armi.party_input_interactions(interaction_id),
          final_transcript text,
          decision_kind text,
          spoken_text text NOT NULL DEFAULT '',
          model_identity text,
          context_version text,
          result_status text NOT NULL DEFAULT 'recognizing',
          error_code text,
          speech_ended_at timestamptz(6),
          first_audio_at timestamptz(6),
          completed_at timestamptz(6),
          created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          CONSTRAINT live_voice_turns_id_check
            CHECK (uuid_extract_version(turn_id)=7),
          CONSTRAINT live_voice_turns_number_check CHECK (turn_no > 0),
          CONSTRAINT live_voice_turns_transcript_check CHECK (
            final_transcript IS NULL
            OR length(btrim(final_transcript)) BETWEEN 1 AND 4096
          ),
          CONSTRAINT live_voice_turns_decision_check CHECK (
            decision_kind IS NULL OR decision_kind IN ('speak','wait','silent')
          ),
          CONSTRAINT live_voice_turns_spoken_check
            CHECK (length(spoken_text) <= 4096),
          CONSTRAINT live_voice_turns_status_check CHECK (
            result_status IN (
              'recognizing','thinking','speaking','waiting_slow',
              'completed','failed','partial','unknown','silent'
            )
          ),
          CONSTRAINT live_voice_turns_error_check CHECK (
            error_code IS NULL OR error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'
          ),
          CONSTRAINT live_voice_turns_first_audio_check CHECK (
            first_audio_at IS NULL OR speech_ended_at IS NULL
            OR first_audio_at >= speech_ended_at
          ),
          UNIQUE (session_id,turn_no)
        );

        CREATE TABLE armi.live_voice_text_fragments (
          fragment_id uuid PRIMARY KEY,
          turn_id uuid NOT NULL REFERENCES armi.live_voice_turns(turn_id),
          fragment_no smallint NOT NULL,
          body text NOT NULL,
          registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          CONSTRAINT live_voice_fragments_id_check
            CHECK (uuid_extract_version(fragment_id)=7),
          CONSTRAINT live_voice_fragments_number_check
            CHECK (fragment_no BETWEEN 1 AND 64),
          CONSTRAINT live_voice_fragments_body_check
            CHECK (length(btrim(body)) BETWEEN 1 AND 160),
          UNIQUE (turn_id,fragment_no)
        );

        CREATE TABLE armi.live_voice_provider_attempts (
          provider_attempt_id uuid PRIMARY KEY,
          turn_id uuid NOT NULL REFERENCES armi.live_voice_turns(turn_id),
          service_kind text NOT NULL,
          provider text NOT NULL,
          resource_id text NOT NULL,
          model_identity text,
          attempt_no smallint NOT NULL DEFAULT 1,
          result_status text NOT NULL,
          error_code text,
          started_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          first_result_at timestamptz(6),
          settled_at timestamptz(6),
          CONSTRAINT live_voice_attempts_id_check
            CHECK (uuid_extract_version(provider_attempt_id)=7),
          CONSTRAINT live_voice_attempts_service_check
            CHECK (service_kind IN ('asr','llm','tts')),
          CONSTRAINT live_voice_attempts_binding_check CHECK (
            length(btrim(provider)) BETWEEN 1 AND 64
            AND length(btrim(resource_id)) BETWEEN 1 AND 128
          ),
          CONSTRAINT live_voice_attempts_number_check CHECK (attempt_no=1),
          CONSTRAINT live_voice_attempts_status_check CHECK (
            result_status IN ('started','completed','failed','partial','unknown')
          ),
          CONSTRAINT live_voice_attempts_error_check CHECK (
            error_code IS NULL OR error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'
          ),
          CONSTRAINT live_voice_attempts_result_check CHECK (
            (result_status='started' AND settled_at IS NULL AND error_code IS NULL)
            OR (result_status='completed' AND settled_at IS NOT NULL
                AND error_code IS NULL)
            OR (result_status IN ('failed','partial','unknown')
                AND settled_at IS NOT NULL AND error_code IS NOT NULL)
          ),
          UNIQUE (turn_id,service_kind,attempt_no)
        );

        CREATE TABLE armi.live_voice_playback_attempts (
          playback_attempt_id uuid PRIMARY KEY,
          turn_id uuid NOT NULL REFERENCES armi.live_voice_turns(turn_id),
          destination_kind text NOT NULL DEFAULT 'local_audio',
          attempt_no smallint NOT NULL DEFAULT 1,
          result_status text NOT NULL,
          frames_written bigint NOT NULL DEFAULT 0,
          error_code text,
          registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
          first_frame_at timestamptz(6),
          settled_at timestamptz(6),
          CONSTRAINT live_voice_playback_id_check
            CHECK (uuid_extract_version(playback_attempt_id)=7),
          CONSTRAINT live_voice_playback_destination_check
            CHECK (destination_kind='local_audio'),
          CONSTRAINT live_voice_playback_attempt_check CHECK (attempt_no=1),
          CONSTRAINT live_voice_playback_status_check CHECK (
            result_status IN ('registered','completed','failed','partial','unknown')
          ),
          CONSTRAINT live_voice_playback_frames_check CHECK (frames_written >= 0),
          CONSTRAINT live_voice_playback_error_check CHECK (
            error_code IS NULL OR error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'
          ),
          CONSTRAINT live_voice_playback_result_check CHECK (
            (result_status='registered' AND settled_at IS NULL
                AND error_code IS NULL)
            OR (result_status='completed' AND settled_at IS NOT NULL
                AND frames_written > 0 AND error_code IS NULL)
            OR (result_status IN ('failed','partial','unknown')
                AND settled_at IS NOT NULL AND error_code IS NOT NULL)
          ),
          UNIQUE (turn_id,attempt_no)
        );

        GRANT SELECT,INSERT,UPDATE ON
          armi.live_voice_sessions,
          armi.live_voice_turns,
          armi.live_voice_text_fragments,
          armi.live_voice_provider_attempts,
          armi.live_voice_playback_attempts
          TO armi_runtime;
        GRANT SELECT ON
          armi.live_voice_sessions,
          armi.live_voice_turns,
          armi.live_voice_text_fragments,
          armi.live_voice_provider_attempts,
          armi.live_voice_playback_attempts
          TO armi_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
