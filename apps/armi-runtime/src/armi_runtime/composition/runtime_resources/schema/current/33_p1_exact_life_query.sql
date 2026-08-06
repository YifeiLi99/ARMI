CREATE TABLE armi.exact_life_query_intents (
    exact_life_query_intent_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(exact_life_query_intent_id) = 7),
    subject_commit_id uuid NOT NULL UNIQUE
        REFERENCES armi.subject_commits(subject_commit_id),
    source_opportunity_id uuid NOT NULL UNIQUE
        REFERENCES armi.opportunities(opportunity_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    proposal_ref text NOT NULL CHECK (
        proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'
    ),
    record_kind text NOT NULL CHECK (
        record_kind IN (
            'activity', 'conversation', 'material', 'memory',
            'relationship', 'self_change'
        )
    ),
    query_text text CHECK (
        query_text IS NULL OR (
            octet_length(query_text) BETWEEN 1 AND 1024
            AND btrim(query_text) <> ''
        )
    ),
    result_limit smallint NOT NULL CHECK (result_limit BETWEEN 1 AND 20),
    query_digest text NOT NULL CHECK (query_digest ~ '^sha256:[0-9a-f]{64}$'),
    execution_work_id uuid NOT NULL UNIQUE REFERENCES armi.durable_work(work_id),
    status text NOT NULL CHECK (
        status IN ('pending', 'succeeded', 'empty', 'failed', 'denied')
    ),
    result_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    result_digest text CHECK (
        result_digest IS NULL OR result_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    result_count smallint CHECK (result_count IS NULL OR result_count BETWEEN 0 AND 20),
    failure_code text CHECK (
        failure_code IS NULL OR failure_code ~ '^LIFE-QUERY-[A-Z0-9-]+$'
    ),
    result_opportunity_id uuid UNIQUE REFERENCES armi.opportunities(opportunity_id),
    trace_id text NOT NULL CHECK (
        trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)
    ),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, source_opportunity_id, proposal_ref),
    CHECK (
        (status = 'pending'
            AND result_artifact_id IS NULL AND result_digest IS NULL
            AND result_count IS NULL AND failure_code IS NULL
            AND result_opportunity_id IS NULL AND completed_at IS NULL)
        OR (status IN ('succeeded', 'empty')
            AND result_artifact_id IS NOT NULL AND result_digest IS NOT NULL
            AND result_count IS NOT NULL AND failure_code IS NULL
            AND result_opportunity_id IS NOT NULL AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'denied')
            AND result_artifact_id IS NOT NULL AND result_digest IS NOT NULL
            AND result_count = 0 AND failure_code IS NOT NULL
            AND result_opportunity_id IS NOT NULL AND completed_at IS NOT NULL)
    ),
    CHECK ((status = 'empty') = (result_count = 0 AND failure_code IS NULL)),
    CHECK ((status = 'succeeded') = (result_count > 0))
);

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_source_kind_check,
    DROP CONSTRAINT opportunities_source_shape_check,
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_source_kind_check CHECK (
        source_kind IN (
            'external_evidence', 'life_generation_available',
            'subject_component_revision', 'activity_revision',
            'maintenance_window', 'life_material_revision',
            'life_query_result'
        )
    ),
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind IN (
                'life_generation_available', 'subject_component_revision',
                'maintenance_window', 'life_material_revision'
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
            'consider_sleep', 'consider_life_query_result'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_sleep', 'consider_life_query_result'
        )
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
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
            'armi.sleep-decision-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK (
        owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action',
            'web_research', 'codex_delegation', 'sleep', 'material',
            'prompt', 'exact_life_query'
        )
    );

REVOKE ALL ON TABLE armi.exact_life_query_intents
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT, INSERT ON TABLE armi.exact_life_query_intents TO armi_runtime;
GRANT UPDATE (
    status, result_artifact_id, result_digest, result_count,
    failure_code, result_opportunity_id, completed_at
) ON armi.exact_life_query_intents TO armi_runtime;
