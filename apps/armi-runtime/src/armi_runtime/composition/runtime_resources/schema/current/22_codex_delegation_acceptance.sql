CREATE TABLE armi.codex_task_sources (
    codex_task_source_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(codex_task_source_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    source_bundle_artifact_id uuid NOT NULL UNIQUE REFERENCES armi.artifacts(artifact_id),
    source_bundle_digest text NOT NULL CHECK (source_bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
    source_tree_digest text NOT NULL CHECK (source_tree_digest ~ '^sha256:[0-9a-f]{64}$'),
    task_manifest_artifact_id uuid NOT NULL UNIQUE REFERENCES armi.artifacts(artifact_id),
    task_manifest_digest text NOT NULL UNIQUE CHECK (task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
    path_scope_digest text NOT NULL CHECK (path_scope_digest ~ '^sha256:[0-9a-f]{64}$'),
    validator_id text NOT NULL CHECK (validator_id ~ '^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$'),
    deadline_seconds integer NOT NULL CHECK (deadline_seconds BETWEEN 60 AND 1800),
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)),
    admitted_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);

ALTER TABLE armi.external_evidence
    DROP CONSTRAINT external_evidence_source_kind_check,
    DROP CONSTRAINT external_evidence_privacy_scope_check,
    DROP CONSTRAINT external_evidence_source_identity_check,
    ADD COLUMN codex_task_source_id uuid UNIQUE
        REFERENCES armi.codex_task_sources(codex_task_source_id),
    ADD COLUMN codex_verification_id uuid UNIQUE,
    ADD CONSTRAINT external_evidence_source_kind_check
        CHECK (source_kind IN ('creator_input', 'web_search', 'codex_task_source', 'codex_result')),
    ADD CONSTRAINT external_evidence_privacy_scope_check
        CHECK (privacy_scope IN ('creator_visible', 'private')),
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
            AND creator_interaction_id IS NULL
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

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result'
        )
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check
        CHECK (owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action',
            'web_research', 'codex_delegation'
        ));

ALTER TABLE armi.action_intents
    DROP CONSTRAINT action_intents_purpose_check,
    ADD COLUMN action_kind text NOT NULL DEFAULT 'creator_response',
    ADD CONSTRAINT action_intents_action_kind_check
        CHECK (action_kind IN ('creator_response', 'codex_delegation')),
    ADD CONSTRAINT action_intents_purpose_check CHECK (
        (action_kind = 'creator_response' AND purpose = 'respond_to_creator')
        OR (action_kind = 'codex_delegation' AND purpose = 'delegate_codex_work')
    );

ALTER TABLE armi.action_intent_revisions
    DROP CONSTRAINT action_intent_revisions_response_digest_check,
    DROP CONSTRAINT action_intent_revisions_response_bytes_check,
    DROP CONSTRAINT action_intent_revisions_media_type_check,
    DROP CONSTRAINT action_intent_revisions_capability_kind_check,
    DROP CONSTRAINT action_intent_revisions_operation_class_check,
    DROP CONSTRAINT action_intent_revisions_audience_scope_check,
    DROP CONSTRAINT action_intent_revisions_data_scope_check,
    DROP CONSTRAINT action_intent_revisions_purpose_check,
    ALTER COLUMN response_artifact_id DROP NOT NULL,
    ALTER COLUMN response_digest DROP NOT NULL,
    ALTER COLUMN response_bytes DROP NOT NULL,
    ALTER COLUMN media_type DROP NOT NULL,
    ALTER COLUMN audience_scope DROP NOT NULL,
    ALTER COLUMN data_scope DROP NOT NULL,
    ADD COLUMN codex_task_source_id uuid REFERENCES armi.codex_task_sources(codex_task_source_id),
    ADD COLUMN task_manifest_digest text CHECK (
        task_manifest_digest IS NULL OR task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    ADD COLUMN validator_id text CHECK (
        validator_id IS NULL OR validator_id ~ '^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$'
    ),
    ADD CONSTRAINT action_intent_revisions_kind_check CHECK (
        (capability_kind = 'creator.scene.reply' AND operation_class = 'send'
            AND purpose = 'respond_to_creator'
            AND response_artifact_id IS NOT NULL
            AND response_digest ~ '^sha256:[0-9a-f]{64}$'
            AND response_bytes BETWEEN 1 AND 65536
            AND media_type = 'text/plain'
            AND audience_scope = 'creator'
            AND data_scope = 'creator_visible_response'
            AND codex_task_source_id IS NULL
            AND task_manifest_digest IS NULL AND validator_id IS NULL)
        OR (capability_kind = 'codex.delegated-work' AND operation_class = 'execute'
            AND purpose = 'delegate_codex_work'
            AND response_artifact_id IS NULL AND response_digest IS NULL
            AND response_bytes IS NULL AND media_type IS NULL
            AND audience_scope IS NULL AND data_scope IS NULL
            AND codex_task_source_id IS NOT NULL
            AND task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
            AND validator_id IS NOT NULL)
    );

ALTER TABLE armi.creator_response_operations
    DROP CONSTRAINT creator_response_operations_current_status_check,
    DROP CONSTRAINT creator_response_operations_check,
    DROP CONSTRAINT creator_response_operations_effect_state_check,
    DROP CONSTRAINT creator_response_operations_reason_code_check,
    ADD COLUMN operation_kind text NOT NULL DEFAULT 'creator_response',
    ADD CONSTRAINT creator_response_operations_operation_kind_check
        CHECK (operation_kind IN ('creator_response', 'codex_delegation')),
    ADD CONSTRAINT creator_response_operations_current_status_check CHECK (
        current_status IN (
            'pending', 'accepted', 'effect_registered', 'effect_dispatching',
            'effect_completed', 'effect_failed', 'effect_unknown', 'effect_cancelled',
            'codex_waiting_grant', 'codex_dispatching', 'codex_verifying',
            'codex_completed', 'codex_failed', 'codex_unknown', 'codex_cancelled',
            'codex_result_pending', 'codex_result_accepted',
            'codex_result_rejected',
            'no_action', 'unauthorized', 'unavailable', 'failed'
        )
    ),
    ADD CONSTRAINT creator_response_operations_reason_code_check CHECK (
        reason_code IS NULL
        OR reason_code ~ '^(?:RESPONSE|POLICY|ACTION|CANDIDATE)-[A-Z0-9-]+$'
    ),
    ADD CONSTRAINT creator_response_operations_check CHECK (
        (formal_no_action_id IS NOT NULL AND operation_kind = 'creator_response'
            AND action_intent_id IS NULL AND current_status = 'no_action')
        OR (formal_no_action_id IS NULL AND action_intent_id IS NOT NULL)
    ),
    ADD CONSTRAINT creator_response_operations_effect_state_check CHECK (
        (effect_id IS NULL AND current_policy_decision_id IS NULL
            AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
        OR (effect_id IS NOT NULL AND current_policy_decision_id IS NOT NULL
            AND effect_registration_digest IS NOT NULL AND effect_registered_at IS NOT NULL)
    );

ALTER TABLE armi.effects
    DROP CONSTRAINT effects_effect_kind_check,
    DROP CONSTRAINT effects_capability_kind_check,
    DROP CONSTRAINT effects_operation_class_check,
    DROP CONSTRAINT effects_audience_scope_check,
    DROP CONSTRAINT effects_data_scope_check,
    DROP CONSTRAINT effects_purpose_check,
    DROP CONSTRAINT effects_payload_bytes_check,
    DROP CONSTRAINT effects_check,
    ALTER COLUMN audience_scope DROP NOT NULL,
    ALTER COLUMN data_scope DROP NOT NULL,
    ADD CONSTRAINT effects_effect_kind_check
        CHECK (effect_kind IN ('creator_response', 'codex_delegation')),
    ADD CONSTRAINT effects_payload_bytes_check CHECK (payload_bytes BETWEEN 1 AND 65536),
    ADD CONSTRAINT effects_kind_scope_check CHECK (
        (effect_kind = 'creator_response'
            AND capability_kind = 'creator.scene.reply' AND operation_class = 'send'
            AND audience_scope = 'creator' AND data_scope = 'creator_visible_response'
            AND purpose = 'respond_to_creator')
        OR (effect_kind = 'codex_delegation'
            AND capability_kind = 'codex.delegated-work' AND operation_class = 'execute'
            AND audience_scope IS NULL AND data_scope IS NULL
            AND purpose = 'delegate_codex_work')
    ),
    ADD CONSTRAINT effects_check CHECK (
        (status = 'registered' AND verification_status = 'not_started'
            AND current_attempt_id IS NULL AND current_observation_id IS NULL
            AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'dispatching' AND verification_status = 'pending'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NULL
            AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status IN ('completed', 'failed') AND verification_status = 'verified'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'unknown' AND verification_status = 'inconclusive'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND (
            (verification_status = 'not_started' AND current_attempt_id IS NULL
                AND current_observation_id IS NULL AND settlement_digest IS NULL
                AND settled_at IS NULL AND cancelled_at IS NOT NULL)
            OR (verification_status = 'verified' AND current_attempt_id IS NOT NULL
                AND current_observation_id IS NOT NULL AND settlement_digest IS NOT NULL
                AND settled_at IS NOT NULL)
        ))
    );

ALTER TABLE armi.effect_outbox_items
    DROP CONSTRAINT effect_outbox_items_max_attempts_check,
    DROP CONSTRAINT effect_outbox_items_last_error_code_check,
    ADD CONSTRAINT effect_outbox_items_max_attempts_check
        CHECK (max_attempts BETWEEN 1 AND 2),
    ADD CONSTRAINT effect_outbox_items_last_error_code_check CHECK (
        last_error_code IS NULL OR last_error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'
    );

ALTER TABLE armi.effect_attempts
    DROP CONSTRAINT effect_attempts_attempt_no_check,
    DROP CONSTRAINT effect_attempts_adapter_binding_check,
    DROP CONSTRAINT effect_attempts_error_code_check,
    ADD CONSTRAINT effect_attempts_attempt_no_check CHECK (attempt_no BETWEEN 1 AND 2),
    ADD CONSTRAINT effect_attempts_adapter_binding_check CHECK (
        adapter_binding IN (
            'armi.creator-response-adapter.postgresql-inbox-v1',
            'armi.codex-runner.openai-python-sdk-v1'
        )
    ),
    ADD CONSTRAINT effect_attempts_error_code_check CHECK (
        error_code IS NULL OR error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'
    );

ALTER TABLE armi.effect_observations
    DROP CONSTRAINT effect_observations_observation_kind_check,
    ADD CONSTRAINT effect_observations_observation_kind_check CHECK (
        observation_kind IN (
            'receipt', 'query', 'rejection', 'ambiguous',
            'runner_verified', 'runner_failed', 'runner_unknown', 'runner_cancelled'
        )
    );

CREATE TABLE armi.codex_verification_results (
    codex_verification_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(codex_verification_id) = 7),
    effect_id uuid NOT NULL UNIQUE REFERENCES armi.effects(effect_id),
    effect_attempt_id uuid NOT NULL UNIQUE REFERENCES armi.effect_attempts(effect_attempt_id),
    execution_status text NOT NULL CHECK (execution_status IN ('verified', 'failed', 'unknown', 'cancelled')),
    cleanup_status text NOT NULL CHECK (cleanup_status IN ('clean', 'failed')),
    source_tree_digest text NOT NULL CHECK (source_tree_digest ~ '^sha256:[0-9a-f]{64}$'),
    final_tree_digest text CHECK (final_tree_digest IS NULL OR final_tree_digest ~ '^sha256:[0-9a-f]{64}$'),
    patch_digest text CHECK (patch_digest IS NULL OR patch_digest ~ '^sha256:[0-9a-f]{64}$'),
    event_transcript_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    final_result_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    patch_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    result_bundle_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    diagnostics_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    validation_report_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    validation_digest text NOT NULL CHECK (validation_digest ~ '^sha256:[0-9a-f]{64}$'),
    changed_path_count integer NOT NULL CHECK (changed_path_count BETWEEN 0 AND 500),
    execution_error_code text CHECK (execution_error_code IS NULL OR execution_error_code ~ '^CODEX-[A-Z0-9-]+$'),
    cleanup_error_code text CHECK (cleanup_error_code IS NULL OR cleanup_error_code ~ '^CODEX-[A-Z0-9-]+$'),
    completed_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (execution_status = 'verified' AND cleanup_status = 'clean'
            AND final_tree_digest IS NOT NULL AND patch_digest IS NOT NULL
            AND final_result_artifact_id IS NOT NULL AND patch_artifact_id IS NOT NULL
            AND result_bundle_artifact_id IS NOT NULL AND validation_report_artifact_id IS NOT NULL
            AND execution_error_code IS NULL AND cleanup_error_code IS NULL)
        OR execution_status <> 'verified'
    )
);

ALTER TABLE armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_verification_fk
    FOREIGN KEY (codex_verification_id)
    REFERENCES armi.codex_verification_results(codex_verification_id);

CREATE TABLE armi.codex_result_sources (
    codex_result_source_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(codex_result_source_id) = 7),
    codex_verification_id uuid NOT NULL UNIQUE
        REFERENCES armi.codex_verification_results(codex_verification_id),
    evidence_id uuid NOT NULL UNIQUE REFERENCES armi.external_evidence(evidence_id),
    opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    result_kind text NOT NULL CHECK (
        result_kind IN ('verified_completion', 'execution_failure', 'outcome_unknown', 'cancelled')
    ),
    evidence_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    evidence_digest text NOT NULL CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);

ALTER TABLE armi.accepted_experiences
    DROP CONSTRAINT accepted_experiences_experience_kind_check,
    DROP CONSTRAINT accepted_experiences_source_perspective_check,
    DROP CONSTRAINT accepted_experiences_source_pair_check,
    ADD CONSTRAINT accepted_experiences_experience_kind_check
        CHECK (experience_kind IN ('creator_input', 'web_observation', 'codex_observation')),
    ADD CONSTRAINT accepted_experiences_source_perspective_check
        CHECK (source_perspective IN ('creator_claim', 'web_claim', 'codex_observation')),
    ADD CONSTRAINT accepted_experiences_source_pair_check CHECK (
        (experience_kind = 'creator_input' AND source_perspective = 'creator_claim')
        OR (experience_kind = 'web_observation' AND source_perspective = 'web_claim')
        OR (experience_kind = 'codex_observation' AND source_perspective = 'codex_observation')
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_codex_task_count integer NOT NULL DEFAULT 0
        CHECK (resumable_codex_task_count >= 0),
    ADD COLUMN resumable_codex_effect_count integer NOT NULL DEFAULT 0
        CHECK (resumable_codex_effect_count >= 0),
    ADD COLUMN pending_codex_result_acceptance_count integer NOT NULL DEFAULT 0
        CHECK (pending_codex_result_acceptance_count >= 0);

REVOKE ALL ON TABLE
    armi.codex_task_sources,
    armi.codex_verification_results,
    armi.codex_result_sources
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.codex_task_sources,
    armi.codex_verification_results,
    armi.codex_result_sources
TO armi_runtime;

GRANT INSERT ON TABLE
    armi.codex_task_sources,
    armi.codex_verification_results,
    armi.codex_result_sources
TO armi_runtime;

GRANT INSERT (action_kind) ON armi.action_intents TO armi_runtime;
GRANT INSERT (codex_task_source_id, task_manifest_digest, validator_id)
ON armi.action_intent_revisions TO armi_runtime;
GRANT INSERT (operation_kind) ON armi.creator_response_operations TO armi_runtime;
GRANT INSERT (codex_task_source_id, codex_verification_id)
ON armi.external_evidence TO armi_runtime;
GRANT INSERT (
    resumable_codex_task_count,
    resumable_codex_effect_count,
    pending_codex_result_acceptance_count
) ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (
    resumable_codex_task_count,
    resumable_codex_effect_count,
    pending_codex_result_acceptance_count
) ON armi.runtime_recovery_runs TO armi_runtime;
