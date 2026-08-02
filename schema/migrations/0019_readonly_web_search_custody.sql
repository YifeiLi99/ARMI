CREATE TABLE armi.web_observation_requests (
    web_observation_request_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(web_observation_request_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    runtime_instance_id uuid NOT NULL REFERENCES armi.runtime_instances(runtime_instance_id),
    fence_token bigint NOT NULL CHECK (fence_token > 0),
    idempotency_key text NOT NULL CHECK (
        octet_length(idempotency_key) BETWEEN 1 AND 128
        AND idempotency_key ~ '^[A-Za-z0-9._:-]+$'
    ),
    purpose text NOT NULL CHECK (purpose = 'public_web_research'),
    operation_class text NOT NULL CHECK (operation_class = 'search_read_public'),
    request_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    binding_id text NOT NULL CHECK (
        binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'
    ),
    work_id uuid NOT NULL UNIQUE REFERENCES armi.durable_work(work_id),
    deadline_at timestamptz(6) NOT NULL,
    max_attempts smallint NOT NULL DEFAULT 2 CHECK (max_attempts = 2),
    max_cost_microyuan bigint NOT NULL DEFAULT 1000000
        CHECK (max_cost_microyuan = 1000000),
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed', 'unknown', 'cancelled')
    ),
    result_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    result_digest text CHECK (result_digest IS NULL OR result_digest ~ '^sha256:[0-9a-f]{64}$'),
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^WEB-[A-Z0-9-]+$'
    ),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, purpose, idempotency_key),
    CHECK (deadline_at > created_at),
    CHECK (
        (status IN ('pending', 'running') AND result_artifact_id IS NULL
            AND result_digest IS NULL AND last_error_code IS NULL AND completed_at IS NULL)
        OR (status = 'succeeded' AND result_artifact_id IS NOT NULL
            AND result_digest IS NOT NULL AND last_error_code IS NULL AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'unknown') AND result_artifact_id IS NULL
            AND result_digest IS NULL AND last_error_code IS NOT NULL AND completed_at IS NOT NULL)
        OR (status = 'cancelled' AND result_artifact_id IS NULL
            AND result_digest IS NULL AND completed_at IS NOT NULL)
    )
);

CREATE TABLE armi.observation_attempts (
    observation_attempt_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(observation_attempt_id) = 7),
    web_observation_request_id uuid NOT NULL
        REFERENCES armi.web_observation_requests(web_observation_request_id),
    work_id uuid NOT NULL REFERENCES armi.durable_work(work_id),
    work_attempt_id uuid NOT NULL CHECK (uuid_extract_version(work_attempt_id) = 7),
    work_lease_token bigint NOT NULL CHECK (work_lease_token > 0),
    attempt_no smallint NOT NULL CHECK (attempt_no BETWEEN 1 AND 2),
    binding_id text NOT NULL CHECK (
        binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'
    ),
    credential_identity text NOT NULL CHECK (
        credential_identity ~ '^sha256:[0-9a-f]{64}$'
    ),
    dispatch_state text NOT NULL CHECK (
        dispatch_state IN ('prepared', 'dispatched', 'settled')
    ),
    provider_request_digest text CHECK (
        provider_request_digest IS NULL OR provider_request_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    provider_model_id text CHECK (
        provider_model_id IS NULL OR provider_model_id ~ '^doubao-seed-evolving[a-z0-9-]*$'
    ),
    result_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    result_digest text CHECK (result_digest IS NULL OR result_digest ~ '^sha256:[0-9a-f]{64}$'),
    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens > 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens > 0),
    web_search_calls smallint CHECK (web_search_calls IS NULL OR web_search_calls BETWEEN 1 AND 8),
    citation_count smallint CHECK (citation_count IS NULL OR citation_count BETWEEN 1 AND 128),
    estimated_cost_microyuan bigint CHECK (
        estimated_cost_microyuan IS NULL OR estimated_cost_microyuan BETWEEN 0 AND 1000000
    ),
    result_status text CHECK (
        result_status IS NULL OR result_status IN ('succeeded', 'failed', 'outcome_unknown', 'cancelled')
    ),
    error_code text CHECK (error_code IS NULL OR error_code ~ '^WEB-[A-Z0-9-]+$'),
    prepared_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    dispatched_at timestamptz(6),
    settled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (web_observation_request_id, attempt_no),
    UNIQUE (web_observation_request_id, work_attempt_id),
    CHECK (
        (dispatch_state = 'prepared' AND result_status IS NULL
            AND provider_request_digest IS NULL AND provider_model_id IS NULL
            AND result_artifact_id IS NULL AND result_digest IS NULL
            AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NULL AND settled_at IS NULL)
        OR (dispatch_state = 'dispatched' AND result_status IS NULL
            AND provider_request_digest IS NULL AND provider_model_id IS NULL
            AND result_artifact_id IS NULL AND result_digest IS NULL
            AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NOT NULL AND settled_at IS NULL)
        OR (dispatch_state = 'settled' AND result_status = 'cancelled'
            AND settled_at IS NOT NULL)
        OR (dispatch_state = 'settled' AND result_status IN (
                'succeeded', 'failed', 'outcome_unknown'
            ) AND dispatched_at IS NOT NULL AND settled_at IS NOT NULL)
    ),
    CHECK (
        (result_status = 'succeeded' AND provider_request_digest IS NOT NULL
            AND provider_model_id IS NOT NULL AND result_artifact_id IS NOT NULL
            AND result_digest IS NOT NULL AND input_tokens IS NOT NULL
            AND output_tokens IS NOT NULL AND web_search_calls IS NOT NULL
            AND citation_count IS NOT NULL AND estimated_cost_microyuan IS NOT NULL
            AND error_code IS NULL)
        OR (result_status IN ('failed', 'outcome_unknown') AND error_code IS NOT NULL
            AND result_artifact_id IS NULL AND result_digest IS NULL)
        OR result_status IS NULL
        OR (result_status = 'cancelled' AND result_artifact_id IS NULL AND result_digest IS NULL)
    )
);

CREATE TABLE armi.observation_tool_calls (
    observation_tool_call_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(observation_tool_call_id) = 7),
    observation_attempt_id uuid NOT NULL
        REFERENCES armi.observation_attempts(observation_attempt_id),
    call_no smallint NOT NULL CHECK (call_no BETWEEN 1 AND 8),
    action_type text NOT NULL CHECK (
        action_type IN ('search', 'open_page', 'find_in_page')
    ),
    provider_identity_digest text NOT NULL CHECK (
        provider_identity_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    action_digest text NOT NULL CHECK (action_digest ~ '^sha256:[0-9a-f]{64}$'),
    completion_status text NOT NULL CHECK (completion_status = 'completed'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (observation_attempt_id, call_no),
    UNIQUE (observation_attempt_id, provider_identity_digest)
);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_web_observation_count integer NOT NULL DEFAULT 0
        CHECK (resumable_web_observation_count >= 0),
    ADD COLUMN unknown_web_observation_attempt_count integer NOT NULL DEFAULT 0
        CHECK (unknown_web_observation_attempt_count >= 0);

REVOKE ALL ON TABLE armi.web_observation_requests, armi.observation_attempts,
    armi.observation_tool_calls FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.web_observation_requests, armi.observation_attempts,
    armi.observation_tool_calls TO armi_runtime;
GRANT INSERT (web_observation_request_id, subject_id, runtime_instance_id, fence_token,
              idempotency_key, purpose, operation_class, request_artifact_id,
              request_digest, binding_id, work_id, deadline_at, max_attempts,
              max_cost_microyuan, status, schema_version)
ON armi.web_observation_requests TO armi_runtime;
GRANT UPDATE (status, result_artifact_id, result_digest, last_error_code, completed_at)
ON armi.web_observation_requests TO armi_runtime;
GRANT INSERT (observation_attempt_id, web_observation_request_id, work_id,
              work_attempt_id, work_lease_token, attempt_no, binding_id,
              credential_identity, dispatch_state, schema_version)
ON armi.observation_attempts TO armi_runtime;
GRANT UPDATE (dispatch_state, provider_request_digest, provider_model_id,
              result_artifact_id, result_digest, input_tokens, output_tokens,
              web_search_calls, citation_count, estimated_cost_microyuan,
              result_status, error_code, dispatched_at, settled_at)
ON armi.observation_attempts TO armi_runtime;
GRANT INSERT (observation_tool_call_id, observation_attempt_id, call_no,
              action_type, provider_identity_digest, action_digest,
              completion_status, schema_version)
ON armi.observation_tool_calls TO armi_runtime;
GRANT INSERT (resumable_web_observation_count, unknown_web_observation_attempt_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_web_observation_count, unknown_web_observation_attempt_count)
ON armi.runtime_recovery_runs TO armi_runtime;
