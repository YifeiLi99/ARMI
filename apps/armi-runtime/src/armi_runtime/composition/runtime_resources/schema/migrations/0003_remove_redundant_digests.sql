-- Remove derived digests that duplicate authoritative identifiers, versions, state, or artifact integrity.

ALTER TABLE armi.runtime_recovery_runs
    DROP CONSTRAINT runtime_recovery_runs_check;
ALTER TABLE armi.subject_component_revisions
    DROP CONSTRAINT subject_component_revisions_origin_check;
ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validations_check;
ALTER TABLE armi.cognitive_context_items
    DROP CONSTRAINT cognitive_context_items_check;
ALTER TABLE armi.exact_life_query_intents
    DROP CONSTRAINT exact_life_query_intents_check;
ALTER TABLE armi.deletion_items
    DROP CONSTRAINT deletion_items_check;
ALTER TABLE armi.observation_attempts
    DROP CONSTRAINT observation_attempts_check,
    DROP CONSTRAINT observation_attempts_check1;
ALTER TABLE armi.web_observation_requests
    DROP CONSTRAINT web_observation_requests_check1;
ALTER TABLE armi.action_operations
    DROP CONSTRAINT action_operations_effect_registration_check;
ALTER TABLE armi.effects
    DROP CONSTRAINT effects_lifecycle_check;

ALTER TABLE armi.runtime_bundle_activations
    DROP COLUMN fixed_prompt_set_digest,
    DROP COLUMN creator_asset_digest;
ALTER TABLE armi.runtime_recovery_runs
    DROP COLUMN summary_digest;
ALTER TABLE armi.subject_commits
    DROP COLUMN change_set_digest,
    DROP COLUMN commit_digest;
ALTER TABLE armi.subject_component_revisions
    DROP COLUMN semantic_digest;

ALTER TABLE armi.cognitive_attempts
    DROP COLUMN binding_digest,
    DROP COLUMN request_digest;
ALTER TABLE armi.cognitive_candidate_applications
    DROP COLUMN completion_digest;
ALTER TABLE armi.cognitive_candidate_validation_items
    DROP COLUMN semantic_digest;
ALTER TABLE armi.cognitive_candidate_validations
    DROP COLUMN candidate_digest,
    DROP COLUMN policy_digest,
    DROP COLUMN change_set_digest;
ALTER TABLE armi.cognitive_context_items
    DROP COLUMN source_digest;
ALTER TABLE armi.cognitive_episodes
    DROP COLUMN policy_digest,
    DROP COLUMN mechanism_config_digest;
ALTER TABLE armi.exact_life_query_intents
    DROP COLUMN result_digest;
ALTER TABLE armi.opportunities
    DROP COLUMN source_digest;
ALTER TABLE armi.life_material_revisions
    DROP COLUMN semantic_digest;
ALTER TABLE armi.relationship_revisions
    DROP COLUMN semantic_digest;
ALTER TABLE armi.activity_decisions
    DROP COLUMN resource_snapshot_digest;
ALTER TABLE armi.maintenance_sessions
    DROP COLUMN schedule_digest;
ALTER TABLE armi.sleep_decisions
    DROP COLUMN source_digest;

ALTER TABLE armi.capabilities
    DROP COLUMN configuration_digest;
ALTER TABLE armi.capability_request_decisions
    DROP COLUMN scope_digest;
ALTER TABLE armi.capability_requests
    DROP COLUMN request_digest;
ALTER TABLE armi.action_operations
    DROP COLUMN completion_digest,
    DROP COLUMN effect_registration_digest;
ALTER TABLE armi.effect_attempts
    DROP COLUMN request_digest;
ALTER TABLE armi.effect_outbox_items
    DROP COLUMN payload_digest;
ALTER TABLE armi.effects
    DROP COLUMN settlement_digest;
ALTER TABLE armi.dialogue_decisions
    DROP COLUMN basis_digest;
ALTER TABLE armi.outbox_items
    DROP COLUMN payload_digest;
ALTER TABLE armi.permission_grants
    DROP COLUMN scope_digest;
ALTER TABLE armi.policy_decisions
    DROP COLUMN decision_digest;

ALTER TABLE armi.audit_events
    DROP COLUMN request_digest,
    DROP COLUMN response_digest,
    DROP COLUMN artifact_digest,
    DROP COLUMN details_digest,
    DROP COLUMN bundle_digest;
ALTER TABLE armi.codex_result_sources
    DROP COLUMN evidence_digest;
ALTER TABLE armi.codex_task_sources
    DROP COLUMN path_scope_digest;
ALTER TABLE armi.codex_verification_results
    DROP COLUMN validation_digest;
ALTER TABLE armi.creator_exports
    DROP COLUMN manifest_digest;
ALTER TABLE armi.deletion_items
    DROP COLUMN execution_digest;
ALTER TABLE armi.observation_attempts
    DROP COLUMN result_digest;
ALTER TABLE armi.observation_tool_calls
    DROP COLUMN action_digest;
ALTER TABLE armi.web_evidence_sources
    DROP COLUMN title_digest,
    DROP COLUMN citation_digest;
ALTER TABLE armi.web_observation_requests
    DROP COLUMN result_digest;

ALTER TABLE armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_check CHECK (
        (status = 'running' AND completed_at IS NULL)
        OR (status IN ('safe', 'blocked', 'abandoned') AND completed_at IS NOT NULL)
    );

ALTER TABLE armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_origin_check CHECK (
        (origin_kind = 'bootstrap' AND component_version = 1
            AND previous_revision_id IS NULL AND subject_commit_id IS NULL AND proposal_ref IS NULL)
        OR (origin_kind = 'subject_commit' AND component_version > 1
            AND previous_revision_id IS NOT NULL AND subject_commit_id IS NOT NULL AND proposal_ref IS NOT NULL)
        OR (origin_kind = 'admin_correction' AND component_version > 1
            AND previous_revision_id IS NOT NULL AND subject_commit_id IS NULL AND proposal_ref IS NULL)
    );

ALTER TABLE armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_check CHECK (
        (validation_status IN ('accepted', 'partially_accepted')
            AND final_disposition IS NOT NULL AND change_set_artifact_id IS NOT NULL AND error_code IS NULL)
        OR (validation_status = 'rejected' AND final_disposition IS NULL
            AND change_set_artifact_id IS NULL AND accepted_count = 0 AND error_code IS NOT NULL)
    );

ALTER TABLE armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_check CHECK (
        (source_ref IS NULL AND source_version IS NULL)
        OR (source_ref IS NOT NULL AND source_version IS NOT NULL)
    );

ALTER TABLE armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_check CHECK (
        (status = 'pending' AND result_artifact_id IS NULL AND result_count IS NULL
            AND failure_code IS NULL AND result_opportunity_id IS NULL AND completed_at IS NULL)
        OR (status IN ('succeeded', 'empty') AND result_artifact_id IS NOT NULL
            AND result_count IS NOT NULL AND failure_code IS NULL
            AND result_opportunity_id IS NOT NULL AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'denied') AND result_artifact_id IS NOT NULL
            AND result_count = 0 AND failure_code IS NOT NULL
            AND result_opportunity_id IS NOT NULL AND completed_at IS NOT NULL)
    );

ALTER TABLE armi.deletion_items
    ADD CONSTRAINT deletion_items_check CHECK (
        (result_status = 'pending' AND completed_at IS NULL)
        OR (result_status <> 'pending' AND completed_at IS NOT NULL)
    );

ALTER TABLE armi.observation_attempts
    ADD CONSTRAINT observation_attempts_check CHECK (
        (dispatch_state = 'prepared' AND result_status IS NULL
            AND provider_request_digest IS NULL AND provider_model_id IS NULL
            AND result_artifact_id IS NULL AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NULL AND settled_at IS NULL)
        OR (dispatch_state = 'dispatched' AND result_status IS NULL
            AND provider_request_digest IS NULL AND provider_model_id IS NULL
            AND result_artifact_id IS NULL AND input_tokens IS NULL AND output_tokens IS NULL
            AND web_search_calls IS NULL AND citation_count IS NULL
            AND estimated_cost_microyuan IS NULL AND error_code IS NULL
            AND dispatched_at IS NOT NULL AND settled_at IS NULL)
        OR (dispatch_state = 'settled' AND result_status = 'cancelled' AND settled_at IS NOT NULL)
        OR (dispatch_state = 'settled' AND result_status IN ('succeeded', 'failed', 'outcome_unknown')
            AND dispatched_at IS NOT NULL AND settled_at IS NOT NULL)
    ),
    ADD CONSTRAINT observation_attempts_check1 CHECK (
        (result_status = 'succeeded' AND provider_request_digest IS NOT NULL
            AND provider_model_id IS NOT NULL AND result_artifact_id IS NOT NULL
            AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL
            AND web_search_calls IS NOT NULL AND citation_count IS NOT NULL
            AND estimated_cost_microyuan IS NOT NULL AND error_code IS NULL)
        OR (result_status IN ('failed', 'outcome_unknown')
            AND error_code IS NOT NULL AND result_artifact_id IS NULL)
        OR result_status IS NULL
        OR (result_status = 'cancelled' AND result_artifact_id IS NULL)
    );

ALTER TABLE armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_check1 CHECK (
        (status IN ('pending', 'running') AND result_artifact_id IS NULL
            AND last_error_code IS NULL AND completed_at IS NULL)
        OR (status = 'succeeded' AND result_artifact_id IS NOT NULL
            AND last_error_code IS NULL AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'unknown') AND result_artifact_id IS NULL
            AND last_error_code IS NOT NULL AND completed_at IS NOT NULL)
        OR (status = 'cancelled' AND result_artifact_id IS NULL AND completed_at IS NOT NULL)
    );

ALTER TABLE armi.action_operations
    ADD CONSTRAINT action_operations_effect_registration_check CHECK (
        (effect_id IS NULL AND effect_registered_at IS NULL)
        OR (effect_id IS NOT NULL AND effect_registered_at IS NOT NULL)
    );

ALTER TABLE armi.effects
    ADD CONSTRAINT effects_lifecycle_check CHECK (
        (status = 'registered' AND verification_status = 'not_started'
            AND current_attempt_id IS NULL AND current_observation_id IS NULL
            AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'dispatching' AND verification_status = 'pending'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NULL
            AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status IN ('completed', 'failed') AND verification_status = 'verified'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'unknown' AND verification_status = 'inconclusive'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND verification_status = 'verified'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settled_at IS NOT NULL AND cancelled_at = settled_at)
    );
