ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result'
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
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep'
        ) AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose NOT IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep'
        ) AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition', 'creator_dialogue',
            'autonomous_activity', 'activity_attention',
            'activity_internal_work', 'sleep_decision'
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
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-attention-candidate.v2',
            'armi.activity-internal-work-candidate.v1',
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
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-attention-candidate.v2',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

CREATE TABLE armi.activity_internal_work_decisions (
    work_decision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(work_decision_id) = 7),
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
    outcome_kind text NOT NULL CHECK (
        outcome_kind IN (
            'progress', 'complete', 'need_information', 'abandon', 'no_result'
        )
    ),
    result_revision_id uuid NOT NULL,
    output_material_id uuid REFERENCES armi.life_materials(life_material_id),
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (expected_revision_id, activity_id)
        REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    FOREIGN KEY (result_revision_id, activity_id)
        REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    CHECK (
        output_material_id IS NULL
        OR outcome_kind IN ('progress', 'complete')
    )
);

REVOKE ALL ON TABLE armi.activity_internal_work_decisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.activity_internal_work_decisions
TO armi_runtime, armi_admin;

GRANT INSERT (
    work_decision_id, opportunity_id, cognitive_episode_id,
    candidate_validation_id, candidate_application_id, activity_id,
    expected_revision_id, expected_head_version, resource_snapshot_digest,
    outcome_kind, result_revision_id, output_material_id, schema_version
) ON armi.activity_internal_work_decisions TO armi_runtime;
