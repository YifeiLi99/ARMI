ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check
    CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_status_check,
    DROP CONSTRAINT cognitive_episodes_state_check,
    ADD COLUMN final_disposition text CHECK (
        final_disposition IS NULL
        OR final_disposition IN (
            'change',
            'no_change',
            'defer',
            'decline',
            'need_information'
        )
    ),
    ADD COLUMN validated_at timestamptz(6),
    ADD CONSTRAINT cognitive_episodes_status_check
    CHECK (
        status IN (
            'preparing',
            'prepared',
            'calling_model',
            'model_returned',
            'validating',
            'candidate_validated',
            'candidate_rejected',
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
            AND final_disposition IS NULL
            AND validated_at IS NULL
        )
        OR (
            status IN ('prepared', 'calling_model')
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NULL
            AND final_disposition IS NULL
            AND validated_at IS NULL
        )
        OR (
            status IN ('model_returned', 'validating')
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NOT NULL
            AND final_disposition IS NULL
            AND validated_at IS NULL
        )
        OR (
            status = 'candidate_validated'
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NOT NULL
            AND final_disposition IS NOT NULL
            AND validated_at IS NOT NULL
        )
        OR (
            status = 'candidate_rejected'
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code ~ '^CANDIDATE-[A-Z0-9-]+$'
            AND prepared_at IS NOT NULL
            AND model_returned_at IS NOT NULL
            AND final_disposition IS NULL
            AND validated_at IS NOT NULL
        )
        OR (
            status IN ('failed', 'cancelled')
            AND failure_code IS NOT NULL
            AND model_returned_at IS NULL
            AND final_disposition IS NULL
            AND validated_at IS NULL
        )
    );

CREATE TABLE armi.cognitive_candidate_validations (
    candidate_validation_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(candidate_validation_id) = 7),
    cognitive_episode_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    model_attempt_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_attempts(model_attempt_id),
    work_id uuid NOT NULL UNIQUE REFERENCES armi.durable_work(work_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL
        REFERENCES armi.life_generations(life_generation_id),
    bundle_activation_id uuid NOT NULL
        REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    base_subject_version bigint NOT NULL CHECK (base_subject_version >= 0),
    base_state_epoch bigint NOT NULL CHECK (base_state_epoch >= 0),
    context_digest text NOT NULL
        CHECK (context_digest ~ '^sha256:[0-9a-f]{64}$'),
    candidate_contract_version text NOT NULL CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2'
        )
    ),
    candidate_digest text NOT NULL
        CHECK (candidate_digest ~ '^sha256:[0-9a-f]{64}$'),
    validator_identity text NOT NULL
        CHECK (
            validator_identity = 'armi.candidate-validator.deterministic-v1'
        ),
    policy_digest text NOT NULL
        CHECK (policy_digest ~ '^sha256:[0-9a-f]{64}$'),
    validation_status text NOT NULL CHECK (
        validation_status IN (
            'accepted',
            'partially_accepted',
            'rejected'
        )
    ),
    final_disposition text CHECK (
        final_disposition IS NULL
        OR final_disposition IN (
            'change',
            'no_change',
            'defer',
            'decline',
            'need_information'
        )
    ),
    change_set_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
    change_set_digest text CHECK (
        change_set_digest IS NULL
        OR change_set_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    accepted_count smallint NOT NULL CHECK (accepted_count BETWEEN 0 AND 16),
    rejected_count smallint NOT NULL CHECK (rejected_count BETWEEN 0 AND 16),
    error_code text CHECK (
        error_code IS NULL OR error_code ~ '^CANDIDATE-[A-Z0-9-]+$'
    ),
    validated_by_runtime_instance_id uuid NOT NULL
        REFERENCES armi.runtime_instances(runtime_instance_id),
    validation_fence_token bigint NOT NULL CHECK (validation_fence_token > 0),
    validated_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (
            validation_status IN ('accepted', 'partially_accepted')
            AND final_disposition IS NOT NULL
            AND change_set_artifact_id IS NOT NULL
            AND change_set_digest IS NOT NULL
            AND error_code IS NULL
        )
        OR (
            validation_status = 'rejected'
            AND final_disposition IS NULL
            AND change_set_artifact_id IS NULL
            AND change_set_digest IS NULL
            AND accepted_count = 0
            AND error_code IS NOT NULL
        )
    )
);

CREATE TABLE armi.cognitive_candidate_validation_items (
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL
        CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    atomic_group_ref text NOT NULL
        CHECK (atomic_group_ref ~ '^group:[1-9][0-9]{0,2}$'),
    owner_kind text NOT NULL CHECK (
        owner_kind IN (
            'experience',
            'self',
            'mind',
            'life_mode',
            'memory',
            'relationship',
            'activity',
            'capability',
            'action'
        )
    ),
    fact_class text NOT NULL CHECK (
        fact_class IN (
            'objective_fact',
            'external_claim',
            'subjective_understanding',
            'inference',
            'unknown'
        )
    ),
    validation_status text NOT NULL
        CHECK (validation_status IN ('accepted', 'rejected')),
    reason_code text CHECK (
        reason_code IS NULL OR reason_code ~ '^CANDIDATE-[A-Z0-9-]+$'
    ),
    semantic_digest text NOT NULL
        CHECK (semantic_digest ~ '^sha256:[0-9a-f]{64}$'),
    ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 16),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    PRIMARY KEY (candidate_validation_id, proposal_ref),
    UNIQUE (candidate_validation_id, ordinal),
    CHECK (
        (validation_status = 'accepted' AND reason_code IS NULL)
        OR (validation_status = 'rejected' AND reason_code IS NOT NULL)
    )
);

CREATE TABLE armi.cognitive_candidate_basis_links (
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    context_item_id uuid NOT NULL
        REFERENCES armi.cognitive_context_items(context_item_id),
    ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 8),
    PRIMARY KEY (candidate_validation_id, proposal_ref, ordinal),
    UNIQUE (candidate_validation_id, proposal_ref, context_item_id),
    FOREIGN KEY (candidate_validation_id, proposal_ref)
        REFERENCES armi.cognitive_candidate_validation_items (
            candidate_validation_id,
            proposal_ref
        )
);

CREATE INDEX cognitive_candidate_validations_status_idx
    ON armi.cognitive_candidate_validations (
        validation_status,
        validated_at,
        candidate_validation_id
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_candidate_validation_count integer NOT NULL DEFAULT 0
        CHECK (resumable_candidate_validation_count >= 0);

REVOKE ALL ON TABLE
    armi.cognitive_candidate_validations,
    armi.cognitive_candidate_validation_items,
    armi.cognitive_candidate_basis_links
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.cognitive_candidate_validations,
    armi.cognitive_candidate_validation_items,
    armi.cognitive_candidate_basis_links
TO armi_runtime;

GRANT INSERT ON TABLE
    armi.cognitive_candidate_validations,
    armi.cognitive_candidate_validation_items,
    armi.cognitive_candidate_basis_links
TO armi_runtime;

GRANT UPDATE (
    status,
    final_disposition,
    failure_code,
    validated_at
) ON armi.cognitive_episodes TO armi_runtime;

GRANT INSERT (resumable_candidate_validation_count)
ON armi.runtime_recovery_runs TO armi_runtime;

GRANT UPDATE (resumable_candidate_validation_count)
ON armi.runtime_recovery_runs TO armi_runtime;
