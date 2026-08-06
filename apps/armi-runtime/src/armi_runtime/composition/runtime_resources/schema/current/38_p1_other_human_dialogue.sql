ALTER TABLE armi.opportunities
    ADD CONSTRAINT opportunities_other_human_episode_unique
        UNIQUE (opportunity_id, subject_id, scene_id, other_party_id);

ALTER TABLE armi.cognitive_episodes
    ADD COLUMN other_party_id uuid REFERENCES armi.parties(party_id),
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    DROP CONSTRAINT cognitive_episodes_scene_shape_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
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
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check'
        ) AND scene_id IS NULL
          AND creator_party_id IS NULL AND other_party_id IS NULL)
        OR (purpose = 'consider_other_human_input'
          AND scene_id IS NOT NULL
          AND creator_party_id IS NULL AND other_party_id IS NOT NULL)
        OR (purpose NOT IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check',
            'consider_other_human_input'
        ) AND scene_id IS NOT NULL
          AND creator_party_id IS NOT NULL AND other_party_id IS NULL)
    ),
    ADD CONSTRAINT cognitive_episodes_other_human_opportunity_fk
        FOREIGN KEY (opportunity_id, subject_id, scene_id, other_party_id)
        REFERENCES armi.opportunities(
            opportunity_id, subject_id, scene_id, other_party_id
        );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition', 'creator_dialogue', 'creator_outreach',
            'other_human_dialogue', 'autonomous_activity',
            'activity_attention', 'activity_internal_work', 'sleep_decision',
            'memory_maintenance', 'subject_self_check'
        )
    ),
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.creator-dialogue-candidate.v11',
            'armi.creator-dialogue-candidate.v12',
            'armi.creator-dialogue-candidate.v13',
            'armi.creator-dialogue-candidate.v14',
            'armi.creator-dialogue-candidate.v15',
            'armi.creator-dialogue-candidate.v16',
            'armi.creator-dialogue-candidate.v17',
            'armi.creator-dialogue-candidate.v18',
            'armi.other-human-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-attention-candidate.v2',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1',
            'armi.maintenance-work-candidate.v1'
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
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.creator-dialogue-candidate.v11',
            'armi.creator-dialogue-candidate.v12',
            'armi.creator-dialogue-candidate.v13',
            'armi.creator-dialogue-candidate.v14',
            'armi.creator-dialogue-candidate.v15',
            'armi.creator-dialogue-candidate.v16',
            'armi.creator-dialogue-candidate.v17',
            'armi.creator-dialogue-candidate.v18',
            'armi.other-human-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-attention-candidate.v2',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1',
            'armi.maintenance-work-candidate.v1'
        )
    );

CREATE TABLE armi.other_human_action_intents (
    other_human_action_intent_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_action_intent_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    root_opportunity_id uuid NOT NULL REFERENCES armi.opportunities(opportunity_id),
    purpose text NOT NULL CHECK (purpose = 'respond_to_other_human'),
    current_revision_id uuid UNIQUE,
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (scene_id, subject_id, other_party_id)
        REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id)
);

CREATE TABLE armi.other_human_action_intent_revisions (
    other_human_action_intent_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_action_intent_revision_id) = 7),
    other_human_action_intent_id uuid NOT NULL
        REFERENCES armi.other_human_action_intents(other_human_action_intent_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    response_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    response_digest text NOT NULL CHECK (response_digest ~ '^sha256:[0-9a-f]{64}$'),
    response_bytes integer NOT NULL CHECK (response_bytes BETWEEN 1 AND 65536),
    media_type text NOT NULL CHECK (media_type = 'text/plain'),
    capability_kind text NOT NULL CHECK (capability_kind = 'local.other-human-inbox.deliver'),
    operation_class text NOT NULL CHECK (operation_class = 'deliver_local'),
    audience_scope text NOT NULL CHECK (audience_scope = 'other_human'),
    data_scope text NOT NULL CHECK (data_scope = 'declared_party_response'),
    purpose text NOT NULL CHECK (purpose = 'respond_to_other_human'),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (other_human_action_intent_id, revision_no),
    UNIQUE (candidate_validation_id, proposal_ref)
);

ALTER TABLE armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_current_revision_fk
        FOREIGN KEY (current_revision_id)
        REFERENCES armi.other_human_action_intent_revisions(
            other_human_action_intent_revision_id
        );

CREATE TABLE armi.other_human_effects (
    other_human_effect_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_effect_id) = 7),
    action_intent_revision_id uuid NOT NULL UNIQUE
        REFERENCES armi.other_human_action_intent_revisions(
            other_human_action_intent_revision_id
        ),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    payload_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    payload_bytes integer NOT NULL CHECK (payload_bytes BETWEEN 1 AND 65536),
    status text NOT NULL CHECK (status IN ('registered', 'completed', 'failed', 'unknown')),
    registration_digest text NOT NULL CHECK (registration_digest ~ '^sha256:[0-9a-f]{64}$'),
    settlement_digest text CHECK (settlement_digest IS NULL OR settlement_digest ~ '^sha256:[0-9a-f]{64}$'),
    registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    settled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK ((status = 'registered' AND settlement_digest IS NULL AND settled_at IS NULL)
        OR (status <> 'registered' AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL)),
    FOREIGN KEY (scene_id, subject_id, other_party_id)
        REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id)
);

CREATE TABLE armi.other_human_local_inbox_deliveries (
    other_human_local_inbox_delivery_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_local_inbox_delivery_id) = 7),
    other_human_effect_id uuid NOT NULL UNIQUE
        REFERENCES armi.other_human_effects(other_human_effect_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    payload_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    receipt_digest text NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    delivered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);

CREATE TABLE armi.other_human_dialogue_decisions (
    other_human_dialogue_decision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(other_human_dialogue_decision_id) = 7),
    opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    cognitive_episode_id uuid NOT NULL UNIQUE REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    candidate_validation_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    candidate_application_id uuid UNIQUE
        REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    subject_commit_id uuid UNIQUE REFERENCES armi.subject_commits(subject_commit_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    decision_kind text NOT NULL CHECK (
        decision_kind IN ('reply', 'silence', 'defer', 'end_conversation')
    ),
    action_intent_id uuid UNIQUE
        REFERENCES armi.other_human_action_intents(other_human_action_intent_id),
    effect_id uuid UNIQUE REFERENCES armi.other_human_effects(other_human_effect_id),
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (decision_kind = 'reply' AND subject_commit_id IS NOT NULL
            AND candidate_application_id IS NULL
            AND action_intent_id IS NOT NULL AND effect_id IS NOT NULL)
        OR (decision_kind = 'end_conversation' AND subject_commit_id IS NOT NULL
            AND candidate_application_id IS NULL
            AND action_intent_id IS NULL AND effect_id IS NULL)
        OR (decision_kind IN ('silence', 'defer') AND subject_commit_id IS NULL
            AND candidate_application_id IS NOT NULL
            AND action_intent_id IS NULL AND effect_id IS NULL)
    )
);

REVOKE ALL ON TABLE armi.other_human_action_intents,
    armi.other_human_action_intent_revisions, armi.other_human_effects,
    armi.other_human_local_inbox_deliveries, armi.other_human_dialogue_decisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT, INSERT ON TABLE armi.other_human_action_intents,
    armi.other_human_action_intent_revisions, armi.other_human_effects,
    armi.other_human_local_inbox_deliveries, armi.other_human_dialogue_decisions
TO armi_runtime;
GRANT UPDATE (current_revision_id) ON armi.other_human_action_intents TO armi_runtime;
GRANT UPDATE (status, settlement_digest, settled_at)
ON armi.other_human_effects TO armi_runtime;
GRANT INSERT (other_party_id) ON armi.cognitive_episodes TO armi_runtime;
GRANT UPDATE (current_status, closed_at) ON armi.interaction_scenes TO armi_runtime;
