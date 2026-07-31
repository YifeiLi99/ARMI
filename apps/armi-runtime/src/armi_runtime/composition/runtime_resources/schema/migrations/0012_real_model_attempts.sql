ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_status_check,
    DROP CONSTRAINT cognitive_episodes_check,
    ADD COLUMN model_returned_at timestamptz(6),
    ADD CONSTRAINT cognitive_episodes_status_check
    CHECK (
        status IN (
            'preparing',
            'prepared',
            'calling_model',
            'model_returned',
            'failed',
            'cancelled'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_state_check
    CHECK (
        (
            status = 'preparing'
            AND context_manifest_artifact_id IS NULL
            AND compiled_context_artifact_id IS NULL
            AND context_digest IS NULL
            AND failure_code IS NULL
            AND prepared_at IS NULL
            AND model_returned_at IS NULL
        )
        OR (
            status IN ('prepared', 'calling_model')
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NULL
        )
        OR (
            status = 'model_returned'
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NOT NULL
        )
        OR (
            status IN ('failed', 'cancelled')
            AND failure_code IS NOT NULL
            AND model_returned_at IS NULL
        )
    );

CREATE TABLE armi.cognitive_attempts (
    model_attempt_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(model_attempt_id) = 7),
    cognitive_episode_id uuid NOT NULL
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    work_id uuid NOT NULL REFERENCES armi.durable_work(work_id),
    work_attempt_id uuid NOT NULL
        CHECK (uuid_extract_version(work_attempt_id) = 7),
    attempt_no smallint NOT NULL CHECK (attempt_no BETWEEN 1 AND 2),
    binding_digest text NOT NULL
        CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
    provider text NOT NULL CHECK (provider = 'volcengine_ark'),
    model_id text NOT NULL
        CHECK (model_id = 'doubao-seed-evolving'),
    version_policy text NOT NULL
        CHECK (version_policy = 'provider_evolving_alias'),
    profile text NOT NULL CHECK (profile = 'creator_input_cognition'),
    request_schema_version text NOT NULL
        CHECK (request_schema_version = 'armi.model-request.v1'),
    candidate_schema_version text NOT NULL
        CHECK (candidate_schema_version = 'armi.cognition-candidate.v1'),
    pricing_snapshot_id text NOT NULL
        CHECK (
            pricing_snapshot_id = 'volcengine-ark-cn-2026-07-31-evolving'
        ),
    credential_identity text NOT NULL
        CHECK (credential_identity = 'armi.model.ark-api-key.v1'),
    request_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    request_digest text NOT NULL
        CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    dispatch_status text NOT NULL
        CHECK (dispatch_status IN ('prepared', 'dispatched', 'settled')),
    provider_request_id text,
    provider_model_id text CHECK (
        provider_model_id IS NULL
        OR provider_model_id ~ '^doubao-seed-[a-z0-9-]{1,96}$'
    ),
    response_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
    cached_input_tokens integer
        CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0),
    estimated_cost_microyuan bigint
        CHECK (
            estimated_cost_microyuan IS NULL
            OR estimated_cost_microyuan >= 0
        ),
    result_status text CHECK (
        result_status IS NULL
        OR result_status IN (
            'succeeded',
            'rejected',
            'timed_out',
            'provider_failed',
            'cancelled',
            'outcome_unknown'
        )
    ),
    error_code text CHECK (
        error_code IS NULL OR error_code ~ '^MODEL-[A-Z0-9-]+$'
    ),
    prepared_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    dispatched_at timestamptz(6),
    settled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (cognitive_episode_id, attempt_no),
    UNIQUE (work_id, work_attempt_id),
    CHECK (
        (
            dispatch_status = 'prepared'
            AND dispatched_at IS NULL
            AND settled_at IS NULL
            AND result_status IS NULL
            AND provider_request_id IS NULL
            AND provider_model_id IS NULL
            AND response_artifact_id IS NULL
            AND input_tokens IS NULL
            AND output_tokens IS NULL
            AND cached_input_tokens IS NULL
            AND estimated_cost_microyuan IS NULL
            AND error_code IS NULL
        )
        OR (
            dispatch_status = 'dispatched'
            AND dispatched_at IS NOT NULL
            AND settled_at IS NULL
            AND result_status IS NULL
            AND response_artifact_id IS NULL
            AND error_code IS NULL
        )
        OR (
            dispatch_status = 'settled'
            AND settled_at IS NOT NULL
            AND result_status IS NOT NULL
            AND (
                (
                    result_status = 'succeeded'
                    AND dispatched_at IS NOT NULL
                    AND provider_request_id IS NOT NULL
                    AND provider_model_id IS NOT NULL
                    AND response_artifact_id IS NOT NULL
                    AND input_tokens IS NOT NULL
                    AND output_tokens IS NOT NULL
                    AND cached_input_tokens IS NOT NULL
                    AND estimated_cost_microyuan IS NOT NULL
                    AND error_code IS NULL
                )
                OR (
                    result_status <> 'succeeded'
                    AND response_artifact_id IS NULL
                    AND error_code IS NOT NULL
                    AND (
                        dispatched_at IS NOT NULL
                        OR (
                            result_status = 'cancelled'
                            AND provider_request_id IS NULL
                            AND provider_model_id IS NULL
                            AND input_tokens IS NULL
                            AND output_tokens IS NULL
                            AND cached_input_tokens IS NULL
                            AND estimated_cost_microyuan IS NULL
                        )
                    )
                )
            )
        )
    )
);

CREATE INDEX cognitive_attempts_episode_status_idx
    ON armi.cognitive_attempts (
        cognitive_episode_id,
        dispatch_status,
        attempt_no
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_model_attempt_count integer NOT NULL DEFAULT 0
        CHECK (resumable_model_attempt_count >= 0);

REVOKE ALL ON TABLE armi.cognitive_attempts
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_runtime;

GRANT INSERT (
    model_attempt_id,
    cognitive_episode_id,
    work_id,
    work_attempt_id,
    attempt_no,
    binding_digest,
    provider,
    model_id,
    version_policy,
    profile,
    request_schema_version,
    candidate_schema_version,
    pricing_snapshot_id,
    credential_identity,
    request_artifact_id,
    request_digest,
    dispatch_status,
    schema_version
) ON armi.cognitive_attempts TO armi_runtime;

GRANT UPDATE (
    dispatch_status,
    provider_request_id,
    provider_model_id,
    response_artifact_id,
    input_tokens,
    output_tokens,
    cached_input_tokens,
    estimated_cost_microyuan,
    result_status,
    error_code,
    dispatched_at,
    settled_at
) ON armi.cognitive_attempts TO armi_runtime;

GRANT UPDATE (status, failure_code, model_returned_at)
ON armi.cognitive_episodes TO armi_runtime;

GRANT INSERT (resumable_model_attempt_count)
ON armi.runtime_recovery_runs TO armi_runtime;

GRANT UPDATE (resumable_model_attempt_count)
ON armi.runtime_recovery_runs TO armi_runtime;
