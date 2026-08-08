-- Frozen ARMI v1 cross-domain constraints and indexes.

ALTER TABLE ONLY armi.party_input_interactions ADD CONSTRAINT party_input_interactions_pkey PRIMARY KEY (interaction_id);
ALTER TABLE ONLY armi.party_input_interactions ADD CONSTRAINT party_input_interactions_scope_key UNIQUE (interaction_id, subject_id, scene_id, source_party_id);
ALTER TABLE ONLY armi.party_input_interactions ADD CONSTRAINT party_input_interactions_idempotency_key UNIQUE (source_party_id, scene_id, purpose, idempotency_key);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_pkey PRIMARY KEY (action_intent_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_owner_key UNIQUE (action_intent_id, subject_id, scene_id, context_party_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_root_kind_key UNIQUE (root_opportunity_id, action_kind);
ALTER TABLE ONLY armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_pkey PRIMARY KEY (action_intent_revision_id);
ALTER TABLE ONLY armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_owner_key UNIQUE (action_intent_revision_id, action_intent_id);
ALTER TABLE ONLY armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_number_key UNIQUE (action_intent_id, revision_no);
ALTER TABLE ONLY armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_pkey PRIMARY KEY (dialogue_decision_id);
ALTER TABLE ONLY armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_opportunity_key UNIQUE (opportunity_id);
ALTER TABLE ONLY armi.action_operations ADD CONSTRAINT action_operations_pkey PRIMARY KEY (operation_id);
ALTER TABLE ONLY armi.action_operations ADD CONSTRAINT action_operations_root_key UNIQUE (root_opportunity_id);
ALTER TABLE ONLY armi.effects ADD CONSTRAINT effects_pkey PRIMARY KEY (effect_id);
ALTER TABLE ONLY armi.effects ADD CONSTRAINT effects_revision_key UNIQUE (action_intent_revision_id);
ALTER TABLE ONLY armi.local_inbox_deliveries ADD CONSTRAINT local_inbox_deliveries_pkey PRIMARY KEY (delivery_id);
ALTER TABLE ONLY armi.local_inbox_deliveries ADD CONSTRAINT local_inbox_deliveries_effect_key UNIQUE (effect_id);
ALTER TABLE ONLY armi.activity_decisions ADD CONSTRAINT activity_decisions_pkey PRIMARY KEY (activity_decision_id);
ALTER TABLE ONLY armi.activity_decisions ADD CONSTRAINT activity_decisions_source_opportunity_key UNIQUE (decision_source, opportunity_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_pkey PRIMARY KEY (evidence_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_interaction_key UNIQUE (interaction_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_artifact_key UNIQUE (artifact_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_pkey PRIMARY KEY (opportunity_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_subject_source_key UNIQUE (subject_id, source_kind, source_ref, source_version, purpose, reconsideration_no);
ALTER TABLE ONLY armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_pkey PRIMARY KEY (cognitive_episode_id);
ALTER TABLE ONLY armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_opportunity_key UNIQUE (opportunity_id);
ALTER TABLE ONLY armi.subject_commits ADD CONSTRAINT subject_commits_subject_commit_id_subject_id_key UNIQUE (subject_commit_id, subject_id);
ALTER TABLE ONLY armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_action_intent_revision_id_action_intent_id_key UNIQUE (action_intent_revision_id, action_intent_id);
ALTER TABLE ONLY armi.prompt_revisions ADD CONSTRAINT prompt_revisions_prompt_revision_id_prompt_document_id_key UNIQUE (prompt_revision_id, prompt_document_id);
ALTER TABLE ONLY armi.subject_component_revisions ADD CONSTRAINT subject_component_revisions_component_revision_owner_key UNIQUE (component_revision_id, subject_id, component_kind);

ALTER TABLE armi.schema_migrations ALTER COLUMN sequence_no ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME armi.schema_migrations_sequence_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_pkey PRIMARY KEY (experience_id);

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_activity_id_current_revision_id_key UNIQUE (activity_id, current_revision_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_activity_id_subject_id_key UNIQUE (activity_id, subject_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_origin_opportunity_id_key UNIQUE (origin_opportunity_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (activity_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_id_revision_no_key UNIQUE (activity_id, revision_no);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_revision_id_activity_id_key UNIQUE (activity_revision_id, activity_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_candidate_validation_id_proposal_ref_key UNIQUE (candidate_validation_id, proposal_ref);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_pkey PRIMARY KEY (activity_revision_id);

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_content_digest_key UNIQUE (content_digest);

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_id);

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_storage_locator_key UNIQUE (storage_locator);

ALTER TABLE ONLY armi.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (audit_event_id);

ALTER TABLE ONLY armi.capabilities
    ADD CONSTRAINT capabilities_capability_kind_key UNIQUE (capability_kind);

ALTER TABLE ONLY armi.capabilities
    ADD CONSTRAINT capabilities_pkey PRIMARY KEY (capability_id);

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_link_capability_request_id_context_key UNIQUE (capability_request_id, context_item_id);

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_pkey PRIMARY KEY (capability_request_id, ordinal);

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_capability_request_id_resultin_key UNIQUE (capability_request_id, resulting_request_version);

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_pkey PRIMARY KEY (capability_decision_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_pkey PRIMARY KEY (capability_request_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_codex_verification_id_key UNIQUE (codex_verification_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_id_key UNIQUE (evidence_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_opportunity_id_key UNIQUE (opportunity_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_pkey PRIMARY KEY (codex_result_source_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_pkey PRIMARY KEY (codex_task_source_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_source_bundle_artifact_id_key UNIQUE (source_bundle_artifact_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_artifact_id_key UNIQUE (task_manifest_artifact_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_digest_key UNIQUE (task_manifest_digest);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_attempt_id_key UNIQUE (effect_attempt_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_id_key UNIQUE (effect_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_pkey PRIMARY KEY (codex_verification_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_cognitive_episode_id_attempt_no_key UNIQUE (cognitive_episode_id, attempt_no);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_pkey PRIMARY KEY (model_attempt_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_work_id_work_attempt_id_key UNIQUE (work_id, work_attempt_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_candidate_validation_id_key UNIQUE (candidate_validation_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_pkey PRIMARY KEY (candidate_application_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_subject_commit_id_key UNIQUE (subject_commit_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_successor_opportunity_id_key UNIQUE (successor_opportunity_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_work_id_key UNIQUE (work_id);

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_lin_candidate_validation_id_propo_key UNIQUE (candidate_validation_id, proposal_ref, context_item_id);

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_links_pkey PRIMARY KEY (candidate_validation_id, proposal_ref, ordinal);

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validatio_candidate_validation_id_ordin_key UNIQUE (candidate_validation_id, ordinal);

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validation_items_pkey PRIMARY KEY (candidate_validation_id, proposal_ref);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_model_attempt_id_key UNIQUE (model_attempt_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_pkey PRIMARY KEY (candidate_validation_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_work_id_key UNIQUE (work_id);

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_cognitive_episode_id_ordinal_key UNIQUE (cognitive_episode_id, ordinal);

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_pkey PRIMARY KEY (context_item_id);

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_directory_name_key UNIQUE (creator_party_id, directory_name);

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_idempotency_key_key UNIQUE (creator_party_id, idempotency_key);

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_pkey PRIMARY KEY (creator_export_id);

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_deletion_order_id_target_kind_target_ref_key UNIQUE (deletion_order_id, target_kind, target_ref);

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_pkey PRIMARY KEY (deletion_item_id);

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_pkey PRIMARY KEY (deletion_order_id);

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_idempotency_key_key UNIQUE (requester_party_id, idempotency_key);

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_order_kind_key UNIQUE (requester_party_id, order_kind);

ALTER TABLE ONLY armi.deployment_environments
    ADD CONSTRAINT deployment_environments_environment_id_key UNIQUE (environment_id);

ALTER TABLE ONLY armi.deployment_environments
    ADD CONSTRAINT deployment_environments_pkey PRIMARY KEY (singleton_key);

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_owner_kind_owner_ref_work_kind_idempotency_key_key UNIQUE (owner_kind, owner_ref, work_kind, idempotency_key);

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_pkey PRIMARY KEY (work_id);

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_attempt_no_key UNIQUE (effect_id, attempt_no);

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_claim_token_key UNIQUE (effect_id, claim_token);

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_pkey PRIMARY KEY (effect_attempt_id);

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_attempt_id_observation_kind_obse_key UNIQUE (effect_attempt_id, observation_kind, observation_digest);

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_pkey PRIMARY KEY (effect_observation_id);

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_effect_id_key UNIQUE (effect_id);

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_pkey PRIMARY KEY (effect_outbox_item_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_execution_work_id_key UNIQUE (execution_work_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_pkey PRIMARY KEY (exact_life_query_intent_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_opportunity_id_key UNIQUE (result_opportunity_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_source_opportunity_id_key UNIQUE (source_opportunity_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_commit_id_key UNIQUE (subject_commit_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_id_source_opportunity_id_p_key UNIQUE (subject_id, source_opportunity_id, proposal_ref);

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_experience_id_evidence_id_context_key UNIQUE (experience_id, evidence_id, context_item_id);

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_pkey PRIMARY KEY (experience_id, ordinal);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_input_identity_unique UNIQUE (scene_id, subject_id, primary_party_id);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_party_key_unique UNIQUE (subject_id, primary_party_id, scene_key);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_pkey PRIMARY KEY (scene_id);

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_pkey PRIMARY KEY (life_generation_id);

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_subject_id_generation_no_key UNIQUE (subject_id, generation_no);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_life_material_revi_key UNIQUE (life_material_id, life_material_revision_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_revision_no_key UNIQUE (life_material_id, revision_no);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_pkey PRIMARY KEY (life_material_revision_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_life_material_id_current_revision_id_key UNIQUE (life_material_id, current_revision_id);

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_pkey PRIMARY KEY (life_material_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_application_id_key UNIQUE (candidate_application_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_validation_id_key UNIQUE (candidate_validation_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_revision_id_key UNIQUE (maintenance_revision_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_opportunity_id_key UNIQUE (opportunity_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_pkey PRIMARY KEY (maintenance_phase_result_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_subject_commit_id_key UNIQUE (subject_commit_id);

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_revision_id_maint_key UNIQUE (maintenance_revision_id, maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_session_id_revisi_key UNIQUE (maintenance_session_id, revision_no);

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_pkey PRIMARY KEY (maintenance_revision_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_pkey PRIMARY KEY (maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_sleep_decision_id_key UNIQUE (sleep_decision_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_subject_id_life_generation_id_cycle_an_key UNIQUE (subject_id, life_generation_id, cycle_anchor_ref);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_wake_request_id_key UNIQUE (wake_request_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_pkey PRIMARY KEY (memory_relation_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_pkey PRIMARY KEY (observation_attempt_id);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_attempt_no_key UNIQUE (web_observation_request_id, attempt_no);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_work_attemp_key UNIQUE (web_observation_request_id, work_attempt_id);

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_call_no_key UNIQUE (observation_attempt_id, call_no);

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_provider_iden_key UNIQUE (observation_attempt_id, provider_identity_digest);

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_pkey PRIMARY KEY (observation_tool_call_id);

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_pkey PRIMARY KEY (outbox_item_id);

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_work_id_message_kind_key UNIQUE (work_id, message_kind);

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_id_kind_unique UNIQUE (party_id, party_kind);

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_party_subject_unique UNIQUE (party_id, represented_subject_id);

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_pkey PRIMARY KEY (party_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_request_id_key UNIQUE (capability_request_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_pkey PRIMARY KEY (grant_id);

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_pkey PRIMARY KEY (policy_decision_id);

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_pkey PRIMARY KEY (prompt_document_id);

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_subject_id_prompt_kind_key UNIQUE (subject_id, prompt_kind);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_pkey PRIMARY KEY (prompt_revision_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_prompt_document_id_revision_no_key UNIQUE (prompt_document_id, revision_no);

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_pkey PRIMARY KEY (relationship_revision_id, experience_id, link_kind);

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_relationship_revision_id_ordi_key UNIQUE (relationship_revision_id, ordinal);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_pkey PRIMARY KEY (relationship_revision_id);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_relationship_revisio_key UNIQUE (relationship_id, relationship_revision_id);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_revision_no_key UNIQUE (relationship_id, revision_no);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_pkey PRIMARY KEY (relationship_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_relationship_id_current_revision_id_key UNIQUE (relationship_id, current_revision_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_id_other_party_id_scope_key UNIQUE (subject_id, other_party_id, scope);

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_pkey PRIMARY KEY (bundle_activation_id);

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_life_generation_id_fence_token_key UNIQUE (life_generation_id, fence_token);

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_pkey PRIMARY KEY (runtime_instance_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_pkey PRIMARY KEY (recovery_run_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_runtime_instance_id_key UNIQUE (runtime_instance_id);

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_pkey PRIMARY KEY (timeline_item_id);

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_scene_id_source_kind_source_ref_source_key UNIQUE (scene_id, source_kind, source_ref, source_event_no);

ALTER TABLE ONLY armi.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (migration_id);

ALTER TABLE ONLY armi.schema_migrations
    ADD CONSTRAINT schema_migrations_sequence_no_key UNIQUE (sequence_no);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_application_id_key UNIQUE (candidate_application_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_validation_id_key UNIQUE (candidate_validation_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_opportunity_id_key UNIQUE (opportunity_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_pkey PRIMARY KEY (sleep_decision_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_candidate_validation_id_key UNIQUE (candidate_validation_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_pkey PRIMARY KEY (subject_commit_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_subject_id_new_subject_version_key UNIQUE (subject_id, new_subject_version);

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_pkey PRIMARY KEY (subject_id, component_kind);

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_pkey PRIMARY KEY (component_revision_id);

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_subject_id_component_kind_compo_key UNIQUE (subject_id, component_kind, component_version);

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_pkey PRIMARY KEY (memory_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_memory_revision_id_key UNIQUE (memory_id, memory_revision_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_revision_no_key UNIQUE (memory_id, revision_no);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_pkey PRIMARY KEY (memory_revision_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_birth_idempotency_key_key UNIQUE (birth_idempotency_key);

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_birth_request_id_key UNIQUE (birth_request_id);

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (subject_id);

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_singleton_key_key UNIQUE (singleton_key);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_canonical_url_digest_key UNIQUE (evidence_id, canonical_url_digest);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_citation_no_key UNIQUE (evidence_id, citation_no);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_observation_attempt_id_citation_no_key UNIQUE (observation_attempt_id, citation_no);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_pkey PRIMARY KEY (web_evidence_source_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_pkey PRIMARY KEY (web_observation_request_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_subject_id_purpose_idempotency_key_key UNIQUE (subject_id, purpose, idempotency_key);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_web_research_intent_id_key UNIQUE (web_research_intent_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_work_id_key UNIQUE (work_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_admission_work_id_key UNIQUE (admission_work_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_pkey PRIMARY KEY (web_research_intent_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_source_opportunity_id_key UNIQUE (source_opportunity_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_commit_id_key UNIQUE (subject_commit_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_id_source_opportunity_id_propo_key UNIQUE (subject_id, source_opportunity_id, proposal_ref);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_web_observation_request_id_key UNIQUE (web_observation_request_id);

CREATE INDEX accepted_experiences_subject_idx ON armi.accepted_experiences USING btree (subject_commit_id, experience_id);

CREATE INDEX audit_events_request_idx ON armi.audit_events USING btree (request_kind, request_ref, occurred_at, audit_event_id) WHERE (request_ref IS NOT NULL);

CREATE INDEX audit_events_subject_idx ON armi.audit_events USING btree (subject_id, occurred_at, audit_event_id) WHERE (subject_id IS NOT NULL);

CREATE INDEX audit_events_target_idx ON armi.audit_events USING btree (target_kind, target_ref, occurred_at, audit_event_id);

CREATE INDEX audit_events_trace_idx ON armi.audit_events USING btree (trace_id, occurred_at, audit_event_id);

CREATE INDEX candidate_applications_resolution_idx ON armi.cognitive_candidate_applications USING btree (resolution, resolved_at, candidate_application_id);

CREATE INDEX capability_requests_creator_page_idx ON armi.capability_requests USING btree (creator_party_id, created_at DESC, capability_request_id DESC);

CREATE UNIQUE INDEX capability_requests_open_codex_idx ON armi.capability_requests USING btree (subject_id, capability_kind, operation_class) WHERE ((capability_kind = 'codex.delegated-work'::text) AND (current_status = ANY (ARRAY['pending'::text, 'granted'::text, 'limited'::text])));

CREATE INDEX capability_requests_pending_idx ON armi.capability_requests USING btree (current_status, created_at, capability_request_id);

CREATE INDEX cognitive_attempts_episode_status_idx ON armi.cognitive_attempts USING btree (cognitive_episode_id, dispatch_status, attempt_no);

CREATE INDEX cognitive_candidate_validations_status_idx ON armi.cognitive_candidate_validations USING btree (validation_status, validated_at, candidate_validation_id);

CREATE INDEX deletion_items_active_target_idx ON armi.deletion_items USING btree (target_kind, target_ref) WHERE (result_status = ANY (ARRAY['completed'::text, 'partial'::text]));

CREATE INDEX deletion_items_order_status_idx ON armi.deletion_items USING btree (deletion_order_id, result_status, target_kind);

CREATE INDEX deletion_orders_effective_party_idx ON armi.deletion_orders USING btree (requester_party_id, order_kind) WHERE (status = 'effective'::text);

CREATE INDEX durable_work_claim_idx ON armi.durable_work USING btree (status, not_before, priority DESC, work_id) WHERE (status = ANY (ARRAY['ready'::text, 'leased'::text]));

CREATE INDEX durable_work_expired_lease_idx ON armi.durable_work USING btree (lease_expires_at, work_id) WHERE (status = 'leased'::text);

CREATE UNIQUE INDEX life_generations_one_active_idx ON armi.life_generations USING btree (subject_id) WHERE (status = 'active'::text);

CREATE INDEX life_material_revisions_material_idx ON armi.life_material_revisions USING btree (life_material_id, revision_no DESC);

CREATE INDEX life_materials_subject_current_idx ON armi.life_materials USING btree (subject_id, updated_at DESC, life_material_id) WHERE (deleted_at IS NULL);

CREATE UNIQUE INDEX maintenance_sessions_one_unfinished ON armi.maintenance_sessions USING btree (subject_id) WHERE (finished_at IS NULL);

CREATE INDEX memory_relations_from_idx ON armi.memory_relations USING btree (from_memory_id, created_at DESC);

CREATE INDEX memory_relations_to_idx ON armi.memory_relations USING btree (to_memory_id, created_at DESC);

CREATE INDEX outbox_items_claim_idx ON armi.outbox_items USING btree (status, available_at, outbox_item_id) WHERE (status = ANY (ARRAY['ready'::text, 'claimed'::text]));

CREATE UNIQUE INDEX parties_one_creator_idx ON armi.parties USING btree (creator_role) WHERE (party_kind = 'creator'::text);

CREATE UNIQUE INDEX parties_one_subject_party_idx ON armi.parties USING btree (represented_subject_id) WHERE (party_kind = 'subject'::text);

CREATE UNIQUE INDEX parties_other_human_declared_identity_idx ON armi.parties USING btree (declared_identity_key) WHERE (party_kind = 'other_human'::text);

CREATE UNIQUE INDEX policy_decisions_one_current ON armi.policy_decisions USING btree (action_intent_revision_id) WHERE is_current;

CREATE INDEX relationship_revisions_relationship_idx ON armi.relationship_revisions USING btree (relationship_id, revision_no DESC);

CREATE INDEX relationships_subject_idx ON armi.relationships USING btree (subject_id, created_at DESC, relationship_id);

CREATE UNIQUE INDEX runtime_bundle_one_current_idx ON armi.runtime_bundle_activations USING btree (subject_id) WHERE (status = 'current'::text);

CREATE UNIQUE INDEX runtime_instances_one_active_generation_idx ON armi.runtime_instances USING btree (life_generation_id) WHERE (status = 'active'::text);

CREATE INDEX runtime_recovery_runs_status_idx ON armi.runtime_recovery_runs USING btree (status, started_at, recovery_run_id);

CREATE INDEX scene_timeline_items_page_idx ON armi.scene_timeline_items USING btree (scene_id, occurred_at DESC, timeline_item_id DESC);

CREATE UNIQUE INDEX schema_migrations_one_baseline_idx ON armi.schema_migrations USING btree (migration_kind) WHERE (migration_kind = 'baseline'::text);

CREATE INDEX subjective_memories_subject_idx ON armi.subjective_memories USING btree (subject_id, created_at DESC, memory_id);

CREATE INDEX subjective_memory_revisions_memory_idx ON armi.subjective_memory_revisions USING btree (memory_id, revision_no DESC);

CREATE UNIQUE INDEX subjective_memory_revisions_source_formation_idx ON armi.subjective_memory_revisions USING btree (source_experience_id) WHERE (revision_no = 1);

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_current_revision_fk FOREIGN KEY (current_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_origin_opportunity_id_fkey FOREIGN KEY (origin_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_previous_revision_id_activity_id_fkey FOREIGN KEY (previous_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_related_scene_id_fkey FOREIGN KEY (related_scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_capability_id_fkey FOREIGN KEY (capability_id) REFERENCES armi.capabilities(capability_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_resolved_by_party_id_fkey FOREIGN KEY (resolved_by_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_codex_verification_id_fkey FOREIGN KEY (codex_verification_id) REFERENCES armi.codex_verification_results(codex_verification_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_artifact_id_fkey FOREIGN KEY (evidence_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_source_bundle_artifact_id_fkey FOREIGN KEY (source_bundle_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_artifact_id_fkey FOREIGN KEY (task_manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_diagnostics_artifact_id_fkey FOREIGN KEY (diagnostics_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_attempt_id_fkey FOREIGN KEY (effect_attempt_id) REFERENCES armi.effect_attempts(effect_attempt_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_event_transcript_artifact_id_fkey FOREIGN KEY (event_transcript_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_final_result_artifact_id_fkey FOREIGN KEY (final_result_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_patch_artifact_id_fkey FOREIGN KEY (patch_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_result_bundle_artifact_id_fkey FOREIGN KEY (result_bundle_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_validation_report_artifact_id_fkey FOREIGN KEY (validation_report_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_successor_opportunity_id_fkey FOREIGN KEY (successor_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_lin_candidate_validation_id_prop_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validatio_validated_by_runtime_instanc_fkey FOREIGN KEY (validated_by_runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validation_ite_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_change_set_artifact_id_fkey FOREIGN KEY (change_set_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_model_attempt_id_fkey FOREIGN KEY (model_attempt_id) REFERENCES armi.cognitive_attempts(model_attempt_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_deletion_order_id_fkey FOREIGN KEY (deletion_order_id) REFERENCES armi.deletion_orders(deletion_order_id);

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_requester_kind_fkey FOREIGN KEY (requester_party_id, requester_kind) REFERENCES armi.parties(party_id, party_kind);

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_scope_party_id_requester_kind_fkey FOREIGN KEY (scope_party_id, requester_kind) REFERENCES armi.parties(party_id, party_kind);

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_subject_fk FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id) ON DELETE RESTRICT;

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_attempt_id_fkey FOREIGN KEY (effect_attempt_id) REFERENCES armi.effect_attempts(effect_attempt_id);

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_execution_work_id_fkey FOREIGN KEY (execution_work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_opportunity_id_fkey FOREIGN KEY (result_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_source_opportunity_id_fkey FOREIGN KEY (source_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_experience_id_fkey FOREIGN KEY (experience_id) REFERENCES armi.accepted_experiences(experience_id);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_primary_party_id_fkey FOREIGN KEY (primary_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_primary_party_kind_fk FOREIGN KEY (primary_party_id, primary_party_kind) REFERENCES armi.parties(party_id, party_kind);

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_fkey FOREIGN KEY (life_material_id) REFERENCES armi.life_materials(life_material_id);

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_previous_fk FOREIGN KEY (life_material_id, previous_revision_id) REFERENCES armi.life_material_revisions(life_material_id, life_material_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_current_revision_fk FOREIGN KEY (life_material_id, current_revision_id) REFERENCES armi.life_material_revisions(life_material_id, life_material_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_owner_party_id_subject_id_fkey FOREIGN KEY (owner_party_id, subject_id) REFERENCES armi.parties(party_id, represented_subject_id);

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_revision_id_maintena_fkey FOREIGN KEY (maintenance_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_session_id_fkey FOREIGN KEY (maintenance_session_id) REFERENCES armi.maintenance_sessions(maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES armi.subjective_memories(memory_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_session_id_fkey FOREIGN KEY (maintenance_session_id) REFERENCES armi.maintenance_sessions(maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_previous_revision_id_mainten_fkey FOREIGN KEY (previous_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_current_revision_fk FOREIGN KEY (current_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_origin_opportunity_id_fkey FOREIGN KEY (origin_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_sleep_decision_id_fkey FOREIGN KEY (sleep_decision_id) REFERENCES armi.sleep_decisions(sleep_decision_id);

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_from_memory_id_fkey FOREIGN KEY (from_memory_id) REFERENCES armi.subjective_memories(memory_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_from_memory_id_from_memory_revision_id_fkey FOREIGN KEY (from_memory_id, from_memory_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_to_memory_id_fkey FOREIGN KEY (to_memory_id) REFERENCES armi.subjective_memories(memory_id);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id) ON DELETE RESTRICT;

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_represented_subject_id_fkey FOREIGN KEY (represented_subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_id_fkey FOREIGN KEY (capability_id) REFERENCES armi.capabilities(capability_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_action_intent_revision_id_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_operation_id_fkey FOREIGN KEY (operation_id) REFERENCES armi.action_operations(operation_id);

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_matched_grant_id_fkey FOREIGN KEY (matched_grant_id) REFERENCES armi.permission_grants(grant_id);

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_supersedes_policy_decision_id_fkey FOREIGN KEY (supersedes_policy_decision_id) REFERENCES armi.policy_decisions(policy_decision_id);

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_current_revision_fk FOREIGN KEY (current_revision_id) REFERENCES armi.prompt_revisions(prompt_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_author_party_id_fkey FOREIGN KEY (author_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_content_artifact_id_fkey FOREIGN KEY (content_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_previous_revision_id_fkey FOREIGN KEY (previous_revision_id) REFERENCES armi.prompt_revisions(prompt_revision_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_prompt_document_id_fkey FOREIGN KEY (prompt_document_id) REFERENCES armi.prompt_documents(prompt_document_id);

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_subject_commit_fk FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_experience_id_fkey FOREIGN KEY (experience_id) REFERENCES armi.accepted_experiences(experience_id);

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_relationship_revision_id_fkey FOREIGN KEY (relationship_revision_id) REFERENCES armi.relationship_revisions(relationship_revision_id);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_previous_fk FOREIGN KEY (relationship_id, previous_revision_id) REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_fkey FOREIGN KEY (relationship_id) REFERENCES armi.relationships(relationship_id);

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_current_revision_fk FOREIGN KEY (relationship_id, current_revision_id) REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_party_id_fkey FOREIGN KEY (subject_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_activated_by_party_id_fkey FOREIGN KEY (activated_by_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_manifest_artifact_id_fkey FOREIGN KEY (manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_current_revision_id_fkey FOREIGN KEY (current_revision_id) REFERENCES armi.subject_component_revisions(component_revision_id);

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_commit_fk FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_previous_fk FOREIGN KEY (previous_revision_id) REFERENCES armi.subject_component_revisions(component_revision_id);

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_current_revision_fk FOREIGN KEY (memory_id, current_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES armi.subjective_memories(memory_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_previous_fk FOREIGN KEY (memory_id, previous_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_source_experience_id_fkey FOREIGN KEY (source_experience_id) REFERENCES armi.accepted_experiences(experience_id);

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_current_activation_fk FOREIGN KEY (current_bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_current_generation_fk FOREIGN KEY (current_generation_id) REFERENCES armi.life_generations(life_generation_id) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_observation_attempt_id_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_source_artifact_id_fkey FOREIGN KEY (source_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_web_research_intent_id_fkey FOREIGN KEY (web_research_intent_id) REFERENCES armi.web_research_intents(web_research_intent_id);

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_admission_work_id_fkey FOREIGN KEY (admission_work_id) REFERENCES armi.durable_work(work_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_query_artifact_id_fkey FOREIGN KEY (query_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_source_opportunity_id_fkey FOREIGN KEY (source_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_web_observation_request_id_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);

ALTER TABLE ONLY armi.party_input_interactions ADD CONSTRAINT party_input_interactions_scene_owner_fkey FOREIGN KEY (scene_id, subject_id, source_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);
ALTER TABLE ONLY armi.party_input_interactions ADD CONSTRAINT party_input_interactions_party_fkey FOREIGN KEY (source_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_scene_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_root_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);
ALTER TABLE ONLY armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_intent_fkey FOREIGN KEY (action_intent_id) REFERENCES armi.action_intents(action_intent_id);
ALTER TABLE ONLY armi.action_intents ADD CONSTRAINT action_intents_current_revision_fkey FOREIGN KEY (current_revision_id, action_intent_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id, action_intent_id);
ALTER TABLE ONLY armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);
ALTER TABLE ONLY armi.action_operations ADD CONSTRAINT action_operations_root_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);
ALTER TABLE ONLY armi.effects ADD CONSTRAINT effects_revision_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);
ALTER TABLE ONLY armi.effects ADD CONSTRAINT effects_destination_party_fkey FOREIGN KEY (destination_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.local_inbox_deliveries ADD CONSTRAINT local_inbox_deliveries_effect_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);
ALTER TABLE ONLY armi.local_inbox_deliveries ADD CONSTRAINT local_inbox_deliveries_party_fkey FOREIGN KEY (destination_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.activity_decisions ADD CONSTRAINT activity_decisions_activity_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_interaction_owner_fkey FOREIGN KEY (interaction_id, subject_id, scene_id, context_party_id) REFERENCES armi.party_input_interactions(interaction_id, subject_id, scene_id, source_party_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);
ALTER TABLE ONLY armi.external_evidence ADD CONSTRAINT external_evidence_artifact_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_context_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_evidence_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);
ALTER TABLE ONLY armi.opportunities ADD CONSTRAINT opportunities_root_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE ONLY armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_context_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);
ALTER TABLE ONLY armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);
ALTER TABLE ONLY armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);
ALTER TABLE ONLY armi.accepted_experiences ADD CONSTRAINT accepted_experiences_subject_commit_owner_fkey FOREIGN KEY (subject_commit_id, subject_id) REFERENCES armi.subject_commits(subject_commit_id, subject_id);
ALTER TABLE ONLY armi.prompt_documents DROP CONSTRAINT prompt_documents_current_revision_fk;
ALTER TABLE ONLY armi.prompt_documents ADD CONSTRAINT prompt_documents_current_revision_owner_fkey FOREIGN KEY (current_revision_id, prompt_document_id) REFERENCES armi.prompt_revisions(prompt_revision_id, prompt_document_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE ONLY armi.prompt_revisions DROP CONSTRAINT prompt_revisions_previous_revision_id_fkey;
ALTER TABLE ONLY armi.prompt_revisions ADD CONSTRAINT prompt_revisions_previous_revision_owner_fkey FOREIGN KEY (previous_revision_id, prompt_document_id) REFERENCES armi.prompt_revisions(prompt_revision_id, prompt_document_id);
ALTER TABLE ONLY armi.subject_component_heads DROP CONSTRAINT subject_component_heads_current_revision_id_fkey;
ALTER TABLE ONLY armi.subject_component_heads ADD CONSTRAINT subject_component_heads_current_revision_owner_fkey FOREIGN KEY (current_revision_id, subject_id, component_kind) REFERENCES armi.subject_component_revisions(component_revision_id, subject_id, component_kind);
ALTER TABLE ONLY armi.subject_component_revisions DROP CONSTRAINT subject_component_revisions_previous_fk;
ALTER TABLE ONLY armi.subject_component_revisions ADD CONSTRAINT subject_component_revisions_previous_revision_owner_fkey FOREIGN KEY (previous_revision_id, subject_id, component_kind) REFERENCES armi.subject_component_revisions(component_revision_id, subject_id, component_kind);

CREATE INDEX accepted_experiences_subject_page_idx ON armi.accepted_experiences USING btree (subject_id, accepted_at DESC, experience_id DESC);
CREATE INDEX accepted_experiences_gist_trgm_idx ON armi.accepted_experiences USING gin (first_person_gist armi_extensions.gin_trgm_ops);
CREATE INDEX subjective_memory_revisions_summary_trgm_idx ON armi.subjective_memory_revisions USING gin (summary armi_extensions.gin_trgm_ops);
CREATE INDEX life_material_revisions_title_trgm_idx ON armi.life_material_revisions USING gin (title armi_extensions.gin_trgm_ops);
CREATE INDEX relationship_revisions_interpretation_trgm_idx ON armi.relationship_revisions USING gin (interpretation armi_extensions.gin_trgm_ops);
CREATE INDEX subject_component_revisions_payload_trgm_idx ON armi.subject_component_revisions USING gin ((semantic_payload::text) armi_extensions.gin_trgm_ops);
