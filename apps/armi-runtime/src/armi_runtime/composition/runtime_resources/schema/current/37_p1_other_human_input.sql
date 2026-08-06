ALTER TABLE armi.parties
    DROP CONSTRAINT parties_party_kind_check,
    DROP CONSTRAINT parties_check,
    DROP CONSTRAINT parties_display_label_check,
    ADD COLUMN declared_identity_key text,
    ADD CONSTRAINT parties_party_kind_check CHECK (
        party_kind IN ('subject', 'creator', 'other_human')
    ),
    ADD CONSTRAINT parties_role_shape_check CHECK (
        (party_kind = 'subject'
            AND represented_subject_id IS NOT NULL
            AND creator_role IS NULL AND declared_identity_key IS NULL)
        OR (party_kind = 'creator'
            AND represented_subject_id IS NULL
            AND creator_role = 'unique_primary_creator'
            AND declared_identity_key IS NULL)
        OR (party_kind = 'other_human'
            AND represented_subject_id IS NULL
            AND creator_role IS NULL
            AND declared_identity_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    ),
    ADD CONSTRAINT parties_display_label_check CHECK (
        (party_kind IN ('subject', 'creator') AND display_label IS NULL)
        OR (party_kind = 'other_human'
            AND length(btrim(display_label)) BETWEEN 1 AND 256)
    ),
    ADD CONSTRAINT parties_id_kind_unique UNIQUE (party_id, party_kind);

CREATE UNIQUE INDEX parties_other_human_declared_identity_idx
    ON armi.parties (declared_identity_key)
    WHERE party_kind = 'other_human';

ALTER TABLE armi.interaction_scenes
    DROP CONSTRAINT interaction_scenes_subject_id_scene_key_key,
    DROP CONSTRAINT interaction_scenes_scene_kind_check,
    DROP CONSTRAINT interaction_scenes_audience_scope_check,
    ADD COLUMN primary_party_kind text NOT NULL DEFAULT 'creator',
    ADD CONSTRAINT interaction_scenes_scene_kind_check CHECK (
        scene_kind IN ('creator_dialogue', 'other_human_dialogue')
    ),
    ADD CONSTRAINT interaction_scenes_audience_scope_check CHECK (
        audience_scope IN ('creator', 'other_human')
    ),
    ADD CONSTRAINT interaction_scenes_role_shape_check CHECK (
        (scene_kind = 'creator_dialogue' AND audience_scope = 'creator'
            AND primary_party_kind = 'creator')
        OR (scene_kind = 'other_human_dialogue' AND audience_scope = 'other_human'
            AND primary_party_kind = 'other_human')
    ),
    ADD CONSTRAINT interaction_scenes_primary_party_kind_fk
        FOREIGN KEY (primary_party_id, primary_party_kind)
        REFERENCES armi.parties(party_id, party_kind),
    ADD CONSTRAINT interaction_scenes_party_key_unique
        UNIQUE (subject_id, primary_party_id, scene_key);

CREATE TABLE armi.other_human_input_interactions (
    other_human_interaction_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_interaction_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    purpose text NOT NULL CHECK (purpose = 'other_human_message'),
    idempotency_key text NOT NULL
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    content_digest text NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    received_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (other_party_id, scene_id, purpose, idempotency_key),
    UNIQUE (other_human_interaction_id, subject_id, scene_id, other_party_id),
    FOREIGN KEY (scene_id, subject_id, other_party_id)
        REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id)
);

ALTER TABLE armi.external_evidence
    ALTER COLUMN creator_party_id DROP NOT NULL,
    ADD COLUMN other_human_interaction_id uuid UNIQUE,
    ADD COLUMN other_party_id uuid REFERENCES armi.parties(party_id),
    DROP CONSTRAINT external_evidence_source_kind_check,
    DROP CONSTRAINT external_evidence_source_identity_check,
    ADD CONSTRAINT external_evidence_source_kind_check CHECK (
        source_kind IN (
            'creator_input', 'web_search', 'codex_task_source', 'codex_result',
            'other_human_input'
        )
    ),
    ADD CONSTRAINT external_evidence_source_identity_check CHECK (
        (source_kind = 'creator_input'
            AND creator_interaction_id IS NOT NULL
            AND other_human_interaction_id IS NULL AND other_party_id IS NULL
            AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NULL
            AND creator_party_id IS NOT NULL AND privacy_scope = 'creator_visible')
        OR (source_kind = 'other_human_input'
            AND creator_interaction_id IS NULL
            AND other_human_interaction_id IS NOT NULL AND other_party_id IS NOT NULL
            AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NULL
            AND creator_party_id IS NULL AND privacy_scope = 'private')
        OR (source_kind = 'web_search'
            AND creator_interaction_id IS NULL AND other_human_interaction_id IS NULL
            AND other_party_id IS NULL AND web_observation_request_id IS NOT NULL
            AND observation_attempt_id IS NOT NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NULL
            AND creator_party_id IS NOT NULL AND privacy_scope = 'private')
        OR (source_kind = 'codex_task_source'
            AND other_human_interaction_id IS NULL AND other_party_id IS NULL
            AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NOT NULL AND codex_verification_id IS NULL
            AND creator_party_id IS NOT NULL AND privacy_scope = 'private')
        OR (source_kind = 'codex_result'
            AND creator_interaction_id IS NULL AND other_human_interaction_id IS NULL
            AND other_party_id IS NULL AND web_observation_request_id IS NULL
            AND observation_attempt_id IS NULL AND codex_task_source_id IS NULL
            AND codex_verification_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND privacy_scope = 'private')
    ),
    ADD CONSTRAINT external_evidence_other_human_fk
        FOREIGN KEY (other_human_interaction_id, subject_id, scene_id, other_party_id)
        REFERENCES armi.other_human_input_interactions(
            other_human_interaction_id, subject_id, scene_id, other_party_id
        ),
    ADD CONSTRAINT external_evidence_other_human_identity_unique
        UNIQUE (evidence_id, subject_id, scene_id, other_party_id);

ALTER TABLE armi.opportunities
    ADD COLUMN other_party_id uuid REFERENCES armi.parties(party_id),
    DROP CONSTRAINT opportunities_source_shape_check,
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref AND scene_id IS NOT NULL
            AND activity_id IS NULL
            AND ((creator_party_id IS NOT NULL AND other_party_id IS NULL)
                OR (creator_party_id IS NULL AND other_party_id IS NOT NULL)))
        OR (source_kind IN (
                'life_generation_available', 'subject_component_revision',
                'maintenance_window', 'maintenance_phase_revision',
                'life_material_revision'
            ) AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND other_party_id IS NULL
            AND activity_id IS NULL)
        OR (source_kind = 'activity_revision'
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND other_party_id IS NULL
            AND activity_id IS NOT NULL)
        OR (source_kind = 'life_query_result'
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND other_party_id IS NULL
            AND activity_id IS NULL)
        OR (source_kind IN ('creator_outreach_absence', 'creator_outreach_relationship')
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND other_party_id IS NULL
            AND activity_id IS NULL)
        OR (source_kind = 'creator_outreach_activity'
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND other_party_id IS NULL
            AND activity_id IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result', 'maintain_subjective_memory',
            'perform_subject_self_check', 'consider_creator_outreach',
            'consider_other_human_input'
        )
    ),
    ADD CONSTRAINT opportunities_other_human_evidence_fk
        FOREIGN KEY (evidence_id, subject_id, scene_id, other_party_id)
        REFERENCES armi.external_evidence(
            evidence_id, subject_id, scene_id, other_party_id
        );

REVOKE ALL ON TABLE armi.other_human_input_interactions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT, INSERT ON TABLE armi.other_human_input_interactions TO armi_runtime;
GRANT INSERT (party_id, party_kind, display_label, declared_identity_key)
ON armi.parties TO armi_runtime;
GRANT INSERT (primary_party_kind) ON armi.interaction_scenes TO armi_runtime;
GRANT INSERT (other_human_interaction_id, other_party_id)
ON armi.external_evidence TO armi_runtime;
GRANT INSERT (other_party_id) ON armi.opportunities TO armi_runtime;
