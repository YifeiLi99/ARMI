-- Frozen ARMI v1 least-privilege grants.

GRANT USAGE ON SCHEMA armi TO armi_admin;

GRANT USAGE ON SCHEMA armi TO armi_migrator;

GRANT USAGE ON SCHEMA armi TO armi_runtime;

GRANT SELECT ON TABLE armi.accepted_experiences TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.accepted_experiences TO armi_runtime;





GRANT SELECT ON TABLE armi.activities TO armi_admin;

GRANT INSERT (activity_id, activity_kind, current_revision_id, head_version, origin_opportunity_id, privacy_scope, schema_version, subject_id), SELECT, UPDATE (current_revision_id, head_version) ON TABLE armi.activities TO armi_runtime;





GRANT SELECT ON TABLE armi.activity_revisions TO armi_admin;

GRANT INSERT (activity_id, activity_revision_id, candidate_validation_id, goal, next_safe_step, previous_revision_id, progress_summary, proposal_ref, related_scene_id, resume_not_before, resumption_cue, revision_no, schema_version, status, subject_commit_id, terminal_reason, transition_kind, waiting_condition, waiting_condition_kind), SELECT ON TABLE armi.activity_revisions TO armi_runtime;

GRANT DELETE, SELECT ON TABLE armi.artifacts TO armi_admin;

GRANT INSERT (artifact_id, byte_size, content_digest, logical_kind, media_type, privacy_scope, producer_kind, producer_trace_id, schema_version, storage_locator), SELECT, UPDATE (deleted_at, integrity_status, retention_status) ON TABLE armi.artifacts TO armi_runtime;

GRANT DELETE, SELECT ON TABLE armi.audit_events TO armi_admin;

GRANT INSERT (actor_kind, actor_ref, after_version, artifact_digest, audit_event_id, before_version, bundle_digest, details_digest, error_category, grant_ref, operation, policy_ref, purpose, request_digest, request_kind, request_ref, response_digest, result_status, schema_version, sensitivity, subject_id, target_kind, target_ref, trace_id), SELECT ON TABLE armi.audit_events TO armi_runtime;

GRANT SELECT ON TABLE armi.capabilities TO armi_admin;

GRANT SELECT ON TABLE armi.capabilities TO armi_runtime;

GRANT SELECT ON TABLE armi.capability_request_basis_links TO armi_admin;

GRANT INSERT (capability_request_id, context_item_id, ordinal), SELECT ON TABLE armi.capability_request_basis_links TO armi_runtime;

GRANT SELECT ON TABLE armi.capability_request_decisions TO armi_admin;

GRANT INSERT (capability_decision_id, capability_request_id, command_digest, creator_party_id, decision_kind, expected_request_version, reason_code, resulting_request_version, schema_version, scope_digest), SELECT ON TABLE armi.capability_request_decisions TO armi_runtime;

GRANT SELECT ON TABLE armi.capability_requests TO armi_admin;

GRANT INSERT (artifact_scope, audience_scope, capability_id, capability_kind, capability_request_id, creator_party_id, data_scope, interaction_scene_id, network_access, operation_class, proposal_ref, purpose, request_digest, requested_max_payload_bytes, requested_max_uses, requested_valid_for_seconds, schema_version, subject_commit_id, subject_id, workspace_scope), SELECT, UPDATE (current_status, request_version, resolution_reason_class, resolved_at, resolved_by_party_id) ON TABLE armi.capability_requests TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.codex_result_sources TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.codex_task_sources TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.codex_verification_results TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_admin;

GRANT INSERT (attempt_no, binding_digest, candidate_schema_version, cognitive_episode_id, credential_identity, dispatch_status, model_attempt_id, model_id, pricing_snapshot_id, profile, provider, request_artifact_id, request_digest, request_schema_version, schema_version, version_policy, work_attempt_id, work_id), SELECT, UPDATE (cached_input_tokens, dispatch_status, dispatched_at, error_code, estimated_cost_microyuan, input_tokens, output_tokens, provider_model_id, provider_request_id, response_artifact_id, result_status, settled_at) ON TABLE armi.cognitive_attempts TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_candidate_applications TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.cognitive_candidate_applications TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_candidate_basis_links TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.cognitive_candidate_basis_links TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_candidate_validation_items TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.cognitive_candidate_validation_items TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_candidate_validations TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.cognitive_candidate_validations TO armi_runtime;

GRANT SELECT ON TABLE armi.cognitive_context_items TO armi_admin;

GRANT INSERT (cognitive_episode_id, content_bytes, context_item_id, disposition, item_kind, ordinal, privacy_scope, reason_code, schema_version, section, source_digest, source_kind, source_ref, source_version, trust_class), SELECT ON TABLE armi.cognitive_context_items TO armi_runtime;



GRANT INSERT, SELECT, UPDATE (artifact_count, completed_at, error_code, manifest_digest, missing_artifacts, row_count, status, table_count) ON TABLE armi.creator_exports TO armi_runtime;







GRANT INSERT, SELECT, UPDATE (completed_at, execution_digest, remaining_location, result_status) ON TABLE armi.deletion_items TO armi_runtime;

GRANT INSERT, SELECT, UPDATE (completed_at, execution_status) ON TABLE armi.deletion_orders TO armi_runtime;

GRANT INSERT (bundle_digest, config_digest, data_root_identity_digest, database_identity_digest, environment_id, environment_kind, incarnation, resettable, schema_version, singleton_key, template_digest, test_controls_enabled), SELECT ON TABLE armi.deployment_environments TO armi_admin;

GRANT SELECT ON TABLE armi.deployment_environments TO armi_runtime;

GRANT INSERT (attempt_count, deadline_at, idempotency_key, lease_token, max_attempts, not_before, owner_kind, owner_ref, payload_digest, payload_kind, payload_ref, priority, schema_version, status, subject_id, trace_id, work_id, work_kind), SELECT, UPDATE (current_attempt_id, last_error_code, lease_expires_at, lease_owner, lease_token, not_before, result_kind, result_ref, status, updated_at) ON TABLE armi.durable_work TO armi_admin;

GRANT INSERT (attempt_count, deadline_at, idempotency_key, lease_token, max_attempts, not_before, owner_kind, owner_ref, payload_digest, payload_kind, payload_ref, priority, schema_version, status, subject_id, trace_id, work_id, work_kind), SELECT, UPDATE (attempt_count, current_attempt_id, last_error_code, lease_expires_at, lease_owner, lease_token, not_before, result_kind, result_ref, status, updated_at) ON TABLE armi.durable_work TO armi_runtime;

GRANT SELECT ON TABLE armi.effect_attempts TO armi_admin;

GRANT INSERT (adapter_binding, attempt_no, claim_token, dispatch_state, effect_attempt_id, effect_id, request_digest, schema_version), SELECT, UPDATE (dispatch_state, dispatched_at, error_code, result_status, settled_at) ON TABLE armi.effect_attempts TO armi_runtime;

GRANT INSERT (effect_attempt_id, effect_id, effect_observation_id, observation_digest, observation_kind, receiver_ref, reliability, schema_version), SELECT ON TABLE armi.effect_observations TO armi_admin;

GRANT INSERT (effect_attempt_id, effect_id, effect_observation_id, observation_digest, observation_kind, receiver_ref, reliability, schema_version), SELECT ON TABLE armi.effect_observations TO armi_runtime;

GRANT SELECT, UPDATE (claim_expires_at, claim_owner, delivered_at, last_error_code, status) ON TABLE armi.effect_outbox_items TO armi_admin;

GRANT INSERT, SELECT, UPDATE (attempt_count, available_at, cancelled_at, claim_expires_at, claim_owner, claim_token, delivered_at, last_error_code, status) ON TABLE armi.effect_outbox_items TO armi_runtime;



GRANT INSERT, SELECT, UPDATE (completed_at, failure_code, result_artifact_id, result_count, result_digest, result_opportunity_id, status) ON TABLE armi.exact_life_query_intents TO armi_runtime;

GRANT SELECT ON TABLE armi.experience_evidence_links TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.experience_evidence_links TO armi_runtime;





GRANT SELECT ON TABLE armi.interaction_scenes TO armi_admin;

GRANT INSERT (audience_scope, current_status, primary_party_id, primary_party_kind, scene_id, scene_key, scene_kind, schema_version, subject_id), SELECT, UPDATE (closed_at, current_status, recent_context_boundary) ON TABLE armi.interaction_scenes TO armi_runtime;

GRANT SELECT ON TABLE armi.life_generations TO armi_admin;

GRANT INSERT (activation_reason, generation_no, life_generation_id, opened_subject_version, status, subject_id), SELECT ON TABLE armi.life_generations TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.life_material_revisions TO armi_runtime;

GRANT INSERT, SELECT, UPDATE (current_revision_id, deleted_at, head_version, updated_at) ON TABLE armi.life_materials TO armi_runtime;

GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_admin;

GRANT INSERT (candidate_application_id, candidate_validation_id, cognitive_episode_id, creator_visible_problem, expected_head_version, maintenance_phase_result_id, maintenance_revision_id, maintenance_session_id, memory_id, opportunity_id, outcome, phase, result_summary, schema_version, subject_commit_id), SELECT ON TABLE armi.maintenance_phase_results TO armi_runtime;

GRANT SELECT ON TABLE armi.maintenance_session_revisions TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.maintenance_session_revisions TO armi_runtime;

GRANT SELECT ON TABLE armi.maintenance_sessions TO armi_admin;

GRANT INSERT, SELECT, UPDATE (current_revision_id, finished_at, head_version, quiet_until, wake_request_id, wake_requested_at) ON TABLE armi.maintenance_sessions TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.memory_relations TO armi_runtime;

GRANT SELECT ON TABLE armi.observation_attempts TO armi_admin;

GRANT INSERT (attempt_no, binding_id, credential_identity, dispatch_state, observation_attempt_id, schema_version, web_observation_request_id, work_attempt_id, work_id, work_lease_token), SELECT, UPDATE (citation_count, dispatch_state, dispatched_at, error_code, estimated_cost_microyuan, input_tokens, output_tokens, provider_model_id, provider_request_digest, result_artifact_id, result_digest, result_status, settled_at, web_search_calls) ON TABLE armi.observation_attempts TO armi_runtime;

GRANT SELECT ON TABLE armi.observation_tool_calls TO armi_admin;

GRANT INSERT (action_digest, action_type, call_no, completion_status, observation_attempt_id, observation_tool_call_id, provider_identity_digest, schema_version), SELECT ON TABLE armi.observation_tool_calls TO armi_runtime;









GRANT INSERT (attempt_count, available_at, claim_token, max_attempts, message_kind, outbox_item_id, payload_digest, schema_version, status, trace_id, work_id), SELECT, UPDATE (available_at, claim_expires_at, claim_token, claimed_by, delivered_at, last_error_code, status, updated_at) ON TABLE armi.outbox_items TO armi_admin;

GRANT INSERT (attempt_count, available_at, claim_token, max_attempts, message_kind, outbox_item_id, payload_digest, schema_version, status, trace_id, work_id), SELECT, UPDATE (attempt_count, available_at, claim_expires_at, claim_token, claimed_by, delivered_at, last_error_code, status, updated_at) ON TABLE armi.outbox_items TO armi_runtime;

GRANT SELECT ON TABLE armi.parties TO armi_admin;

GRANT INSERT (creator_role, declared_identity_key, display_label, party_id, party_kind, represented_subject_id), SELECT ON TABLE armi.parties TO armi_runtime;

GRANT SELECT ON TABLE armi.permission_grants TO armi_admin;

GRANT INSERT (artifact_scope, audience_scope, capability_id, capability_request_id, creator_party_id, data_scope, grant_id, interaction_scene_id, max_payload_bytes, max_uses, network_access, operation_class, purpose, schema_version, scope_digest, subject_id, valid_from, valid_until, workspace_scope), SELECT, UPDATE (consumed_uses, revoked_at, status) ON TABLE armi.permission_grants TO armi_runtime;

GRANT SELECT ON TABLE armi.policy_decisions TO armi_admin;

GRANT INSERT, SELECT, UPDATE (is_current) ON TABLE armi.policy_decisions TO armi_runtime;

GRANT SELECT ON TABLE armi.prompt_documents TO armi_admin;

GRANT INSERT (current_revision_id, prompt_document_id, prompt_kind, subject_id, write_authority), SELECT, UPDATE (current_revision_id, status) ON TABLE armi.prompt_documents TO armi_runtime;

GRANT SELECT ON TABLE armi.prompt_revisions TO armi_admin;

GRANT INSERT (author_party_id, change_reason, content_artifact_id, content_digest, previous_revision_id, prompt_document_id, prompt_revision_id, revision_no, subject_commit_id), SELECT ON TABLE armi.prompt_revisions TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.relationship_experience_links TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.relationship_revisions TO armi_runtime;

GRANT INSERT, SELECT, UPDATE (current_revision_id, head_version) ON TABLE armi.relationships TO armi_runtime;

GRANT SELECT ON TABLE armi.runtime_bundle_activations TO armi_admin;

GRANT INSERT (activated_by_party_id, bundle_activation_id, bundle_digest, bundle_version, creator_asset_digest, fixed_policy_digest, fixed_prompt_set_digest, manifest_artifact_id, status, subject_id), SELECT ON TABLE armi.runtime_bundle_activations TO armi_runtime;

GRANT SELECT, UPDATE (status, stopped_at) ON TABLE armi.runtime_instances TO armi_admin;

GRANT INSERT (bundle_activation_id, fence_token, lease_expires_at, life_generation_id, runtime_instance_id, schema_version, status, subject_id), SELECT, UPDATE (last_heartbeat_at, lease_expires_at, status, stopped_at) ON TABLE armi.runtime_instances TO armi_runtime;

GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_admin;

GRANT INSERT (blocker_count, bundle_activation_id, creator_response_delivery_count, critical_artifact_count, dead_outbox_count, fence_token, life_generation_id, pending_codex_result_acceptance_count, pending_web_evidence_acceptance_count, recovery_run_id, reliable_effect_observation_count, requeued_outbox_count, requeued_work_count, resumable_admin_correction_work_count, resumable_candidate_validation_count, resumable_capability_request_count, resumable_codex_effect_count, resumable_codex_task_count, resumable_cognitive_episode_count, resumable_effect_attempt_count, resumable_effect_count, resumable_effect_outbox_count, resumable_model_attempt_count, resumable_opportunity_count, resumable_outbox_count, resumable_response_operation_count, resumable_subject_commit_count, resumable_web_cognition_count, resumable_web_observation_count, resumable_web_research_intent_count, resumable_work_count, runtime_instance_id, schema_version, status, subject_id, terminal_work_count, unknown_web_observation_attempt_count), SELECT, UPDATE (blocker_count, completed_at, creator_response_delivery_count, critical_artifact_count, dead_outbox_count, pending_codex_result_acceptance_count, pending_web_evidence_acceptance_count, reliable_effect_observation_count, requeued_outbox_count, requeued_work_count, resumable_admin_correction_work_count, resumable_candidate_validation_count, resumable_capability_request_count, resumable_codex_effect_count, resumable_codex_task_count, resumable_cognitive_episode_count, resumable_effect_attempt_count, resumable_effect_count, resumable_effect_outbox_count, resumable_model_attempt_count, resumable_opportunity_count, resumable_outbox_count, resumable_response_operation_count, resumable_subject_commit_count, resumable_web_cognition_count, resumable_web_observation_count, resumable_web_research_intent_count, resumable_work_count, status, summary_digest, terminal_work_count, unknown_web_observation_attempt_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;

GRANT DELETE, SELECT ON TABLE armi.scene_timeline_items TO armi_admin;

GRANT INSERT (occurred_at, result_status, scene_id, schema_version, source_event_no, source_kind, source_ref, timeline_item_id), SELECT ON TABLE armi.scene_timeline_items TO armi_runtime;

GRANT SELECT ON TABLE armi.schema_migrations TO armi_admin;

GRANT SELECT ON TABLE armi.schema_migrations TO armi_migrator;

GRANT SELECT ON TABLE armi.schema_migrations TO armi_runtime;

GRANT SELECT ON TABLE armi.sleep_decisions TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.sleep_decisions TO armi_runtime;

GRANT SELECT ON TABLE armi.subject_commits TO armi_admin;

GRANT INSERT, SELECT ON TABLE armi.subject_commits TO armi_runtime;

GRANT SELECT, UPDATE (component_version, current_revision_id) ON TABLE armi.subject_component_heads TO armi_admin;

GRANT INSERT (component_kind, component_version, current_revision_id, subject_id), SELECT, UPDATE (component_version, current_revision_id) ON TABLE armi.subject_component_heads TO armi_runtime;

GRANT INSERT (component_kind, component_revision_id, component_version, origin_kind, origin_ref, previous_revision_id, privacy_scope, proposal_ref, semantic_digest, semantic_payload, subject_commit_id, subject_id), SELECT ON TABLE armi.subject_component_revisions TO armi_admin;

GRANT INSERT (component_kind, component_revision_id, component_version, origin_kind, origin_ref, previous_revision_id, privacy_scope, proposal_ref, semantic_digest, semantic_payload, subject_commit_id, subject_id), SELECT ON TABLE armi.subject_component_revisions TO armi_runtime;

GRANT INSERT, SELECT, UPDATE (current_revision_id, head_version) ON TABLE armi.subjective_memories TO armi_runtime;

GRANT INSERT, SELECT ON TABLE armi.subjective_memory_revisions TO armi_runtime;

GRANT SELECT, UPDATE (state_epoch) ON TABLE armi.subjects TO armi_admin;

GRANT INSERT (birth_idempotency_key, birth_manifest_digest, birth_request_id, current_bundle_activation_id, current_generation_id, singleton_key, subject_id), SELECT, UPDATE (state_epoch, subject_version) ON TABLE armi.subjects TO armi_runtime;

GRANT SELECT ON TABLE armi.web_evidence_sources TO armi_admin;

GRANT INSERT (acquisition_kind, canonical_url_digest, citation_digest, citation_no, evidence_id, observation_attempt_id, schema_version, source_artifact_id, title_digest, web_evidence_source_id), SELECT ON TABLE armi.web_evidence_sources TO armi_runtime;

GRANT SELECT ON TABLE armi.web_observation_requests TO armi_admin;

GRANT INSERT (binding_id, deadline_at, fence_token, idempotency_key, max_attempts, max_cost_microyuan, operation_class, purpose, request_artifact_id, request_digest, runtime_instance_id, schema_version, status, subject_id, web_observation_request_id, work_id), SELECT, UPDATE (completed_at, last_error_code, result_artifact_id, result_digest, status, web_research_intent_id) ON TABLE armi.web_observation_requests TO armi_runtime;

GRANT SELECT ON TABLE armi.web_research_intents TO armi_admin;

GRANT INSERT (admission_work_id, creator_party_id, idempotency_key, operation_class, proposal_ref, purpose, query_artifact_id, query_digest, scene_id, schema_version, source_opportunity_id, status, subject_commit_id, subject_id, trace_id, web_research_intent_id), SELECT, UPDATE (completed_at, status, web_observation_request_id) ON TABLE armi.web_research_intents TO armi_runtime;

GRANT SELECT ON TABLE armi.party_input_interactions, armi.action_intents, armi.action_intent_revisions, armi.dialogue_decisions, armi.action_operations, armi.effects, armi.local_inbox_deliveries, armi.activity_decisions TO armi_admin;
GRANT INSERT, SELECT, UPDATE ON TABLE armi.party_input_interactions, armi.action_intents, armi.action_intent_revisions, armi.dialogue_decisions, armi.action_operations, armi.effects, armi.local_inbox_deliveries, armi.activity_decisions TO armi_runtime;
GRANT DELETE ON TABLE armi.party_input_interactions, armi.dialogue_decisions, armi.local_inbox_deliveries TO armi_admin;

GRANT SELECT ON TABLE armi.external_evidence, armi.opportunities, armi.cognitive_episodes TO armi_admin;
GRANT INSERT, SELECT, UPDATE ON TABLE armi.external_evidence, armi.opportunities, armi.cognitive_episodes TO armi_runtime;
GRANT DELETE ON TABLE armi.external_evidence, armi.opportunities TO armi_admin;
