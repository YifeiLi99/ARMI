ALTER TABLE armi.creator_input_interactions
    DROP CONSTRAINT creator_input_interactions_purpose_check,
    ADD CONSTRAINT creator_input_interactions_purpose_check CHECK (
        purpose IN ('creator_message', 'codex_task_request')
    );

ALTER TABLE armi.external_evidence
    DROP CONSTRAINT external_evidence_source_identity_check,
    ADD CONSTRAINT external_evidence_source_identity_check CHECK (
        (source_kind = 'creator_input'
            AND creator_interaction_id IS NOT NULL
            AND web_observation_request_id IS NULL
            AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NULL
            AND privacy_scope = 'creator_visible')
        OR (source_kind = 'web_search'
            AND creator_interaction_id IS NULL
            AND web_observation_request_id IS NOT NULL
            AND observation_attempt_id IS NOT NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NULL
            AND privacy_scope = 'private')
        OR (source_kind = 'codex_task_source'
            AND web_observation_request_id IS NULL
            AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NOT NULL AND codex_verification_id IS NULL
            AND privacy_scope = 'private')
        OR (source_kind = 'codex_result'
            AND creator_interaction_id IS NULL
            AND web_observation_request_id IS NULL
            AND observation_attempt_id IS NULL
            AND codex_task_source_id IS NULL AND codex_verification_id IS NOT NULL
            AND privacy_scope = 'private')
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_failure_code_check,
    ADD CONSTRAINT cognitive_episodes_failure_code_check CHECK (
        failure_code IS NULL
        OR failure_code ~ '^[A-Z][A-Z0-9-]{2,127}$'
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6'
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
            'armi.cognition-candidate.v6'
        )
    );

ALTER TABLE armi.creator_response_operations
    DROP CONSTRAINT creator_response_operations_reason_code_check,
    ADD CONSTRAINT creator_response_operations_reason_code_check CHECK (
        reason_code IS NULL
        OR reason_code ~ '^(?:RESPONSE|POLICY|ACTION|CODEX)-[A-Z0-9-]+$'
    );
