ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_source_kind_check,
    DROP CONSTRAINT opportunities_source_shape_check,
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_source_kind_check CHECK (
        source_kind IN (
            'external_evidence', 'life_generation_available',
            'subject_component_revision', 'activity_revision',
            'maintenance_window', 'maintenance_phase_revision',
            'life_material_revision', 'life_query_result'
        )
    ),
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind IN (
                'life_generation_available', 'subject_component_revision',
                'maintenance_window', 'maintenance_phase_revision',
                'life_material_revision'
            )
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NULL)
        OR (source_kind = 'activity_revision'
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NOT NULL)
        OR (source_kind = 'life_query_result'
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
    ),
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result', 'maintain_subjective_memory',
            'perform_subject_self_check'
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
            'consider_life_query_result', 'maintain_subjective_memory',
            'perform_subject_self_check'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check'
        ) AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose NOT IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check'
        ) AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition', 'creator_dialogue',
            'autonomous_activity', 'activity_attention',
            'activity_internal_work', 'sleep_decision',
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
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-attention-candidate.v2',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1',
            'armi.maintenance-work-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK (
        owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action',
            'web_research', 'codex_delegation', 'sleep', 'material',
            'prompt', 'exact_life_query', 'maintenance'
        )
    );

CREATE TABLE armi.maintenance_phase_results (
    maintenance_phase_result_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(maintenance_phase_result_id) = 7),
    opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    cognitive_episode_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    candidate_validation_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    candidate_application_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    subject_commit_id uuid NOT NULL UNIQUE
        REFERENCES armi.subject_commits(subject_commit_id),
    maintenance_session_id uuid NOT NULL
        REFERENCES armi.maintenance_sessions(maintenance_session_id),
    maintenance_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL CHECK (expected_head_version > 0),
    phase text NOT NULL CHECK (phase IN ('memory_maintenance', 'self_check')),
    outcome text NOT NULL CHECK (
        outcome IN ('memory_changed', 'memory_unchanged', 'issue_found', 'no_issue')
    ),
    result_summary text NOT NULL CHECK (length(result_summary) BETWEEN 1 AND 512),
    creator_visible_problem text CHECK (
        creator_visible_problem IS NULL
        OR length(creator_visible_problem) BETWEEN 1 AND 512
    ),
    memory_id uuid REFERENCES armi.subjective_memories(memory_id),
    completed_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (maintenance_revision_id, maintenance_session_id)
        REFERENCES armi.maintenance_session_revisions(
            maintenance_revision_id, maintenance_session_id
        ),
    UNIQUE (maintenance_revision_id),
    CHECK (
        (phase = 'memory_maintenance'
            AND outcome IN ('memory_changed', 'memory_unchanged'))
        OR (phase = 'self_check' AND outcome IN ('issue_found', 'no_issue'))
    ),
    CHECK ((outcome = 'memory_changed') = (memory_id IS NOT NULL)),
    CHECK (
        (outcome = 'issue_found') = (creator_visible_problem IS NOT NULL)
    )
);

REVOKE ALL ON TABLE armi.maintenance_phase_results
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_runtime, armi_admin;
GRANT INSERT (
    maintenance_phase_result_id, opportunity_id, cognitive_episode_id,
    candidate_validation_id, candidate_application_id, subject_commit_id,
    maintenance_session_id, maintenance_revision_id, expected_head_version,
    phase, outcome, result_summary, creator_visible_problem, memory_id,
    schema_version
) ON armi.maintenance_phase_results TO armi_runtime;
