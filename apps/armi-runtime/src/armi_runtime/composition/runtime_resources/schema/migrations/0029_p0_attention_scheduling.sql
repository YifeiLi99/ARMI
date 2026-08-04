ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input',
            'consider_web_evidence',
            'consider_codex_task',
            'consider_codex_result',
            'consider_autonomous_life',
            'consider_activity_attention'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    DROP CONSTRAINT cognitive_episodes_scene_shape_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input',
            'consider_web_evidence',
            'consider_codex_task',
            'consider_codex_result',
            'consider_autonomous_life',
            'consider_activity_attention'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN ('consider_autonomous_life', 'consider_activity_attention')
            AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose NOT IN ('consider_autonomous_life', 'consider_activity_attention')
            AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition',
            'creator_dialogue',
            'autonomous_activity',
            'activity_attention'
        )
    ),
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1'
        )
    );

ALTER TABLE armi.activity_revisions
    ALTER COLUMN next_safe_step DROP NOT NULL,
    ADD COLUMN transition_kind text,
    ADD COLUMN waiting_condition_kind text,
    ADD COLUMN resume_not_before timestamptz(6);

UPDATE armi.activity_revisions
SET transition_kind = 'created'
WHERE revision_no = 1 AND status = 'ready';

ALTER TABLE armi.activity_revisions
    ALTER COLUMN transition_kind SET NOT NULL,
    ADD CONSTRAINT activity_revisions_transition_kind_check CHECK (
        transition_kind IN (
            'created', 'engage', 'progress', 'wait', 'pause', 'resume',
            'complete', 'abandon', 'system_fail'
        )
    ),
    ADD CONSTRAINT activity_revisions_waiting_kind_check CHECK (
        waiting_condition_kind IS NULL
        OR waiting_condition_kind IN (
            'time', 'creator_input', 'external_evidence', 'scheduled_review'
        )
    ),
    ADD CONSTRAINT activity_revisions_transition_state_check CHECK (
        (transition_kind = 'created' AND revision_no = 1 AND status = 'ready')
        OR (transition_kind = 'engage' AND status = 'in_progress')
        OR (transition_kind = 'progress' AND status = 'in_progress')
        OR (transition_kind = 'wait' AND status = 'waiting')
        OR (transition_kind = 'pause' AND status = 'paused')
        OR (transition_kind = 'resume' AND status = 'resuming')
        OR (transition_kind = 'complete' AND status = 'completed')
        OR (transition_kind = 'abandon' AND status = 'abandoned')
        OR (transition_kind = 'system_fail' AND status = 'failed')
    ),
    ADD CONSTRAINT activity_revisions_payload_shape_check CHECK (
        (status IN ('completed', 'abandoned', 'failed')
            AND terminal_reason IS NOT NULL
            AND next_safe_step IS NULL
            AND waiting_condition IS NULL
            AND waiting_condition_kind IS NULL
            AND resumption_cue IS NULL
            AND resume_not_before IS NULL)
        OR (status IN ('ready', 'in_progress', 'resuming')
            AND terminal_reason IS NULL
            AND next_safe_step IS NOT NULL
            AND waiting_condition IS NULL
            AND waiting_condition_kind IS NULL
            AND resumption_cue IS NULL
            AND resume_not_before IS NULL)
        OR (status = 'waiting'
            AND terminal_reason IS NULL
            AND next_safe_step IS NOT NULL
            AND waiting_condition IS NOT NULL
            AND waiting_condition_kind IN ('time', 'creator_input', 'external_evidence')
            AND resumption_cue IS NOT NULL
            AND ((waiting_condition_kind = 'time') = (resume_not_before IS NOT NULL)))
        OR (status = 'paused'
            AND terminal_reason IS NULL
            AND next_safe_step IS NOT NULL
            AND waiting_condition IS NOT NULL
            AND waiting_condition_kind = 'scheduled_review'
            AND resumption_cue IS NOT NULL
            AND resume_not_before IS NOT NULL)
    );

CREATE TABLE armi.activity_attention_decisions (
    attention_decision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(attention_decision_id) = 7),
    opportunity_id uuid NOT NULL UNIQUE
        REFERENCES armi.opportunities(opportunity_id),
    cognitive_episode_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    candidate_validation_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    candidate_application_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    activity_id uuid NOT NULL REFERENCES armi.activities(activity_id),
    expected_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL CHECK (expected_head_version > 0),
    resource_snapshot_digest text NOT NULL
        CHECK (resource_snapshot_digest ~ '^sha256:[0-9a-f]{64}$'),
    decision_kind text NOT NULL CHECK (
        decision_kind IN (
            'engage', 'progress', 'wait', 'pause', 'resume', 'complete',
            'abandon', 'no_action', 'defer', 'need_information'
        )
    ),
    result_revision_id uuid,
    review_not_before timestamptz(6),
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (expected_revision_id, activity_id)
        REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    FOREIGN KEY (result_revision_id, activity_id)
        REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    CHECK (
        (decision_kind IN (
            'engage', 'progress', 'wait', 'pause', 'resume', 'complete', 'abandon'
        ) AND result_revision_id IS NOT NULL)
        OR (decision_kind IN ('no_action', 'defer', 'need_information')
            AND result_revision_id IS NULL)
    ),
    CHECK ((decision_kind = 'defer') = (review_not_before IS NOT NULL))
);

REVOKE ALL ON TABLE armi.activity_attention_decisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.activity_attention_decisions TO armi_runtime, armi_admin;
GRANT INSERT (
    attention_decision_id, opportunity_id, cognitive_episode_id,
    candidate_validation_id, candidate_application_id, activity_id,
    expected_revision_id, expected_head_version, resource_snapshot_digest,
    decision_kind, result_revision_id, review_not_before, schema_version
) ON armi.activity_attention_decisions TO armi_runtime;

GRANT INSERT (
    transition_kind, waiting_condition_kind, resume_not_before
) ON armi.activity_revisions TO armi_runtime;
