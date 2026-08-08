ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check
    CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check
    CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validations_final_disposition_check,
    ADD CONSTRAINT cognitive_candidate_validations_final_disposition_check
    CHECK (
        final_disposition IS NULL
        OR final_disposition IN (
            'change', 'no_change', 'defer', 'decline',
            'no_action', 'need_information'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_final_disposition_check,
    ADD CONSTRAINT cognitive_episodes_final_disposition_check
    CHECK (
        final_disposition IS NULL
        OR final_disposition IN (
            'change', 'no_change', 'defer', 'decline',
            'no_action', 'need_information'
        )
    );

ALTER TABLE armi.cognitive_candidate_applications
    DROP CONSTRAINT cognitive_candidate_applications_resolution_check,
    ADD CONSTRAINT cognitive_candidate_applications_resolution_check
    CHECK (
        resolution IN (
            'applied', 'no_change', 'deferred', 'declined',
            'no_action', 'need_information', 'stale'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_application_resolution_check,
    DROP CONSTRAINT cognitive_episodes_state_check,
    ADD CONSTRAINT cognitive_episodes_application_resolution_check
    CHECK (
        application_resolution IS NULL
        OR application_resolution IN (
            'applied', 'no_change', 'deferred', 'declined',
            'no_action', 'need_information', 'stale'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_state_check
    CHECK (
        (status = 'preparing' AND context_digest IS NULL AND prepared_at IS NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('prepared', 'calling_model') AND context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('model_returned', 'validating') AND context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NOT NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('candidate_validated', 'committing') AND context_digest IS NOT NULL AND model_returned_at IS NOT NULL AND validated_at IS NOT NULL AND final_disposition IS NOT NULL AND failure_code IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status = 'candidate_rejected' AND validated_at IS NOT NULL AND final_disposition IS NULL AND failure_code ~ '^CANDIDATE-[A-Z0-9-]+$' AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status = 'completed' AND application_resolution IN ('applied', 'no_change', 'declined', 'no_action', 'deferred', 'need_information') AND committed_at IS NOT NULL)
        OR (status = 'stale' AND application_resolution = 'stale' AND committed_at IS NOT NULL)
        OR (status IN ('failed', 'cancelled') AND failure_code IS NOT NULL AND application_resolution IS NULL AND committed_at IS NULL)
    );

CREATE TABLE armi.action_intents (
    action_intent_id uuid PRIMARY KEY CHECK (uuid_extract_version(action_intent_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    root_opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    purpose text NOT NULL CHECK (purpose = 'respond_to_creator'),
    current_revision_id uuid,
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);

CREATE TABLE armi.action_intent_revisions (
    action_intent_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(action_intent_revision_id) = 7),
    action_intent_id uuid NOT NULL REFERENCES armi.action_intents(action_intent_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    response_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    response_digest text NOT NULL CHECK (response_digest ~ '^sha256:[0-9a-f]{64}$'),
    response_bytes integer NOT NULL CHECK (response_bytes BETWEEN 1 AND 65536),
    media_type text NOT NULL CHECK (media_type = 'text/plain'),
    capability_kind text NOT NULL CHECK (capability_kind = 'creator.scene.reply'),
    operation_class text NOT NULL CHECK (operation_class = 'send'),
    audience_scope text NOT NULL CHECK (audience_scope = 'creator'),
    data_scope text NOT NULL CHECK (data_scope = 'creator_visible_response'),
    purpose text NOT NULL CHECK (purpose = 'respond_to_creator'),
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (action_intent_id, revision_no),
    UNIQUE (candidate_validation_id, proposal_ref),
    UNIQUE (subject_commit_id)
);

ALTER TABLE armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_validation_item_fk
    FOREIGN KEY (candidate_validation_id, proposal_ref)
    REFERENCES armi.cognitive_candidate_validation_items (
        candidate_validation_id, proposal_ref
    );

ALTER TABLE armi.action_intents
    ADD CONSTRAINT action_intents_current_revision_fk
    FOREIGN KEY (current_revision_id)
    REFERENCES armi.action_intent_revisions(action_intent_revision_id);

CREATE TABLE armi.formal_no_action_decisions (
    formal_no_action_id uuid PRIMARY KEY CHECK (uuid_extract_version(formal_no_action_id) = 7),
    candidate_application_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    root_opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    decision_kind text NOT NULL CHECK (decision_kind IN ('decline', 'no_action')),
    reason_class text NOT NULL CHECK (
        (decision_kind = 'decline' AND reason_class = 'subjective_refusal')
        OR (decision_kind = 'no_action' AND reason_class = 'subjective_silence')
    ),
    basis_digest text NOT NULL CHECK (basis_digest ~ '^sha256:[0-9a-f]{64}$'),
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (candidate_validation_id, proposal_ref),
    FOREIGN KEY (candidate_validation_id, proposal_ref)
        REFERENCES armi.cognitive_candidate_validation_items (
            candidate_validation_id, proposal_ref
        )
);

CREATE TABLE armi.creator_response_operations (
    creator_response_operation_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(creator_response_operation_id) = 7),
    root_opportunity_id uuid NOT NULL UNIQUE REFERENCES armi.opportunities(opportunity_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    action_intent_id uuid UNIQUE REFERENCES armi.action_intents(action_intent_id),
    formal_no_action_id uuid UNIQUE REFERENCES armi.formal_no_action_decisions(formal_no_action_id),
    admission_work_id uuid UNIQUE REFERENCES armi.durable_work(work_id),
    current_status text NOT NULL CHECK (
        current_status IN ('pending', 'accepted', 'no_action', 'unauthorized', 'unavailable', 'failed')
    ),
    matched_grant_id uuid REFERENCES armi.permission_grants(grant_id),
    completion_digest text CHECK (completion_digest IS NULL OR completion_digest ~ '^sha256:[0-9a-f]{64}$'),
    reason_code text CHECK (reason_code IS NULL OR reason_code ~ '^(?:RESPONSE|POLICY|ACTION)-[A-Z0-9-]+$'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (current_status = 'pending' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NULL AND reason_code IS NULL AND completed_at IS NULL)
        OR (current_status = 'accepted' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status = 'no_action' AND action_intent_id IS NULL AND formal_no_action_id IS NOT NULL AND admission_work_id IS NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('unauthorized', 'unavailable', 'failed') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NOT NULL AND completed_at IS NOT NULL)
    )
);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_response_operation_count integer NOT NULL DEFAULT 0
        CHECK (resumable_response_operation_count >= 0);

REVOKE ALL ON TABLE armi.action_intents, armi.action_intent_revisions,
    armi.formal_no_action_decisions, armi.creator_response_operations
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.action_intents, armi.action_intent_revisions,
    armi.formal_no_action_decisions, armi.creator_response_operations
TO armi_runtime;
GRANT INSERT (
    action_intent_id, subject_id, interaction_scene_id, creator_party_id,
    root_opportunity_id, purpose, current_revision_id, schema_version
) ON armi.action_intents TO armi_runtime;
GRANT INSERT (
    action_intent_revision_id, action_intent_id, revision_no,
    response_artifact_id, response_digest, response_bytes, media_type,
    capability_kind, operation_class, audience_scope, data_scope, purpose,
    candidate_validation_id, proposal_ref, subject_commit_id, schema_version
) ON armi.action_intent_revisions TO armi_runtime;
GRANT INSERT (
    formal_no_action_id, candidate_application_id, candidate_validation_id,
    proposal_ref, root_opportunity_id, decision_kind, reason_class,
    basis_digest, schema_version
) ON armi.formal_no_action_decisions TO armi_runtime;
GRANT INSERT (
    creator_response_operation_id, root_opportunity_id, subject_id,
    interaction_scene_id, creator_party_id, action_intent_id,
    formal_no_action_id, admission_work_id, current_status, matched_grant_id,
    completion_digest, reason_code, completed_at, schema_version
) ON armi.creator_response_operations TO armi_runtime;
GRANT UPDATE (current_revision_id) ON armi.action_intents TO armi_runtime;
GRANT UPDATE (current_status, matched_grant_id, completion_digest, reason_code, completed_at)
ON armi.creator_response_operations TO armi_runtime;
GRANT INSERT (resumable_response_operation_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_response_operation_count)
ON armi.runtime_recovery_runs TO armi_runtime;
