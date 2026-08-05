ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_source_kind_check,
    DROP CONSTRAINT opportunities_source_shape_check,
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_source_kind_check CHECK (
        source_kind IN (
            'external_evidence', 'life_generation_available',
            'subject_component_revision', 'activity_revision',
            'maintenance_window'
        )
    ),
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind IN (
                'life_generation_available', 'subject_component_revision',
                'maintenance_window'
            )
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NULL)
        OR (source_kind = 'activity_revision'
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_sleep'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    DROP CONSTRAINT cognitive_episodes_scene_shape_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_sleep'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN (
                'consider_autonomous_life', 'consider_activity_attention',
                'consider_sleep'
            ) AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose NOT IN (
                'consider_autonomous_life', 'consider_activity_attention',
                'consider_sleep'
            ) AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition', 'creator_dialogue',
            'autonomous_activity', 'activity_attention', 'sleep_decision'
        )
    ),
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK (
        owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action',
            'web_research', 'codex_delegation', 'sleep'
        )
    );

CREATE TABLE armi.sleep_decisions (
    sleep_decision_id uuid PRIMARY KEY CHECK (uuid_extract_version(sleep_decision_id) = 7),
    opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    cognitive_episode_id uuid NOT NULL UNIQUE REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    candidate_validation_id uuid NOT NULL UNIQUE REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    candidate_application_id uuid NOT NULL UNIQUE REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL REFERENCES armi.life_generations(life_generation_id),
    cycle_anchor_ref uuid NOT NULL CHECK (uuid_extract_version(cycle_anchor_ref) = 7),
    source_digest text NOT NULL CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    decision_kind text NOT NULL CHECK (
        decision_kind IN ('sleep', 'stay_awake', 'defer', 'need_information')
    ),
    review_not_before timestamptz(6),
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK ((decision_kind = 'defer') = (review_not_before IS NOT NULL))
);

CREATE TABLE armi.maintenance_sessions (
    maintenance_session_id uuid PRIMARY KEY CHECK (uuid_extract_version(maintenance_session_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL REFERENCES armi.life_generations(life_generation_id),
    origin_opportunity_id uuid REFERENCES armi.opportunities(opportunity_id),
    cycle_anchor_kind text NOT NULL CHECK (cycle_anchor_kind IN ('life_generation', 'maintenance_session')),
    cycle_anchor_ref uuid NOT NULL CHECK (uuid_extract_version(cycle_anchor_ref) = 7),
    consideration_at timestamptz(6) NOT NULL,
    deadline_at timestamptz(6) NOT NULL,
    schedule_digest text NOT NULL CHECK (schedule_digest ~ '^sha256:[0-9a-f]{64}$'),
    trigger_kind text NOT NULL CHECK (trigger_kind IN ('subject_choice', 'system_deadline')),
    sleep_decision_id uuid UNIQUE REFERENCES armi.sleep_decisions(sleep_decision_id),
    started_subject_version bigint NOT NULL CHECK (started_subject_version >= 0),
    started_state_epoch bigint NOT NULL CHECK (started_state_epoch >= 0),
    current_revision_id uuid,
    head_version bigint NOT NULL DEFAULT 1 CHECK (head_version > 0),
    started_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    finished_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, life_generation_id, cycle_anchor_ref),
    CHECK (consideration_at < deadline_at),
    CHECK ((trigger_kind = 'subject_choice') = (sleep_decision_id IS NOT NULL))
);

CREATE UNIQUE INDEX maintenance_sessions_one_unfinished
ON armi.maintenance_sessions (subject_id)
WHERE finished_at IS NULL;

CREATE TABLE armi.maintenance_session_revisions (
    maintenance_revision_id uuid PRIMARY KEY CHECK (uuid_extract_version(maintenance_revision_id) = 7),
    maintenance_session_id uuid NOT NULL REFERENCES armi.maintenance_sessions(maintenance_session_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_revision_id uuid,
    phase text NOT NULL CHECK (phase IN (
        'preparing', 'memory_maintenance', 'self_check', 'life_quiet',
        'resume_check', 'completed'
    )),
    result_status text NOT NULL CHECK (result_status IN ('running', 'completed', 'interrupted', 'failed')),
    transition_kind text NOT NULL CHECK (transition_kind IN ('started', 'advanced', 'completed', 'interrupted', 'system_failed')),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (maintenance_session_id, revision_no),
    UNIQUE (maintenance_revision_id, maintenance_session_id),
    FOREIGN KEY (previous_revision_id, maintenance_session_id)
        REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id),
    CHECK (
        (revision_no = 1 AND previous_revision_id IS NULL AND phase = 'preparing'
            AND result_status = 'running' AND transition_kind = 'started')
        OR (revision_no > 1 AND previous_revision_id IS NOT NULL)
    ),
    CHECK ((phase = 'completed') = (result_status = 'completed'))
);

ALTER TABLE armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_current_revision_fk
    FOREIGN KEY (current_revision_id, maintenance_session_id)
    REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT maintenance_sessions_current_revision_required CHECK (current_revision_id IS NOT NULL);

REVOKE ALL ON TABLE armi.sleep_decisions, armi.maintenance_sessions,
    armi.maintenance_session_revisions FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.sleep_decisions, armi.maintenance_sessions,
    armi.maintenance_session_revisions TO armi_runtime, armi_admin;
GRANT INSERT ON TABLE armi.sleep_decisions, armi.maintenance_session_revisions TO armi_runtime;
GRANT INSERT ON TABLE armi.maintenance_sessions TO armi_runtime;
GRANT INSERT (available_after, expires_at)
    ON armi.opportunities TO armi_runtime;
GRANT UPDATE (current_revision_id, head_version, finished_at)
    ON armi.maintenance_sessions TO armi_runtime;
