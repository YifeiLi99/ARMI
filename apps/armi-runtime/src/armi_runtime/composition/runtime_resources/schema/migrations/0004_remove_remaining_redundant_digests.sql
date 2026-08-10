-- Remove remaining digests without an independent verifier or decision consumer.

ALTER TABLE armi.observation_attempts
    DROP CONSTRAINT observation_attempts_check,
    DROP CONSTRAINT observation_attempts_check1;

ALTER TABLE armi.observation_tool_calls
    DROP CONSTRAINT observation_tool_calls_observation_attempt_id_provider_iden_key;

ALTER TABLE armi.deployment_environments
    DROP COLUMN bundle_digest,
    DROP COLUMN config_digest,
    DROP COLUMN template_digest,
    DROP COLUMN data_root_identity_digest,
    DROP COLUMN database_identity_digest;

ALTER TABLE armi.life_material_revisions
    DROP COLUMN body_digest;

ALTER TABLE armi.observation_attempts
    DROP COLUMN provider_request_digest;

ALTER TABLE armi.observation_tool_calls
    DROP COLUMN provider_identity_digest;

ALTER TABLE armi.observation_attempts
    ADD CONSTRAINT observation_attempts_check CHECK (
        (dispatch_state = 'prepared' AND result_status IS NULL
            AND provider_model_id IS NULL AND result_artifact_id IS NULL
            AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NULL AND settled_at IS NULL)
        OR (dispatch_state = 'dispatched' AND result_status IS NULL
            AND provider_model_id IS NULL AND result_artifact_id IS NULL
            AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NOT NULL AND settled_at IS NULL)
        OR (dispatch_state = 'settled' AND result_status = 'cancelled'
            AND settled_at IS NOT NULL)
        OR (dispatch_state = 'settled'
            AND result_status IN ('succeeded', 'failed', 'outcome_unknown')
            AND dispatched_at IS NOT NULL AND settled_at IS NOT NULL)
    ),
    ADD CONSTRAINT observation_attempts_check1 CHECK (
        (result_status = 'succeeded' AND provider_model_id IS NOT NULL
            AND result_artifact_id IS NOT NULL AND input_tokens IS NOT NULL
            AND output_tokens IS NOT NULL AND web_search_calls IS NOT NULL
            AND citation_count IS NOT NULL
            AND estimated_cost_microyuan IS NOT NULL AND error_code IS NULL)
        OR (result_status IN ('failed', 'outcome_unknown')
            AND error_code IS NOT NULL AND result_artifact_id IS NULL)
        OR result_status IS NULL
        OR (result_status = 'cancelled' AND result_artifact_id IS NULL)
    );
