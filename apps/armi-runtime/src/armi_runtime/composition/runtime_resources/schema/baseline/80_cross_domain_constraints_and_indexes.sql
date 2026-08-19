-- Current ARMI keys, indexes and cross-domain constraints.

--
-- Name: accepted_experiences accepted_experiences_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_pkey PRIMARY KEY (experience_id);

--
-- Name: accepted_experiences accepted_experiences_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: action_intent_revisions action_intent_revisions_number_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_number_key UNIQUE (action_intent_id, revision_no);

--
-- Name: action_intent_revisions action_intent_revisions_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_owner_key UNIQUE (action_intent_revision_id, action_intent_id);

--
-- Name: action_intent_revisions action_intent_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_pkey PRIMARY KEY (action_intent_revision_id);

--
-- Name: action_intents action_intents_operation_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_operation_owner_key UNIQUE (action_intent_id, operation_ref);

--
-- Name: action_intents action_intents_operation_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_operation_ref_key UNIQUE (operation_ref);

--
-- Name: action_intents action_intents_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_owner_key UNIQUE (action_intent_id, subject_id, scene_id, context_party_id);

--
-- Name: action_intents action_intents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_pkey PRIMARY KEY (action_intent_id);

--
-- Name: action_intents action_intents_root_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_root_kind_key UNIQUE (root_opportunity_id, action_kind);

--
-- Name: activities activities_activity_id_subject_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_activity_id_subject_id_key UNIQUE (activity_id, subject_id);

--
-- Name: activities activities_origin_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_origin_opportunity_id_key UNIQUE (origin_opportunity_id);

--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (activity_id);

--
-- Name: activity_decisions activity_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_pkey PRIMARY KEY (activity_decision_id);

--
-- Name: activity_decisions activity_decisions_source_opportunity_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_source_opportunity_key UNIQUE (decision_source, opportunity_id);

--
-- Name: activity_revisions activity_revisions_activity_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_id_revision_no_key UNIQUE (activity_id, revision_no);

--
-- Name: activity_revisions activity_revisions_activity_revision_id_activity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_revision_id_activity_id_key UNIQUE (activity_revision_id, activity_id);

--
-- Name: activity_revisions activity_revisions_candidate_validation_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_candidate_validation_id_proposal_ref_key UNIQUE (candidate_validation_id, proposal_ref);

--
-- Name: activity_revisions activity_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_pkey PRIMARY KEY (activity_revision_id);

--
-- Name: artifacts artifacts_content_digest_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_content_digest_key UNIQUE (content_digest);

--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_id);

--
-- Name: artifacts artifacts_storage_locator_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.artifacts
    ADD CONSTRAINT artifacts_storage_locator_key UNIQUE (storage_locator);

--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (audit_event_id);

--
-- Name: capabilities capabilities_capability_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capabilities
    ADD CONSTRAINT capabilities_capability_kind_key UNIQUE (capability_kind);

--
-- Name: capabilities capabilities_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capabilities
    ADD CONSTRAINT capabilities_pkey PRIMARY KEY (capability_id);

--
-- Name: capability_request_basis_links capability_request_basis_link_capability_request_id_context_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_link_capability_request_id_context_key UNIQUE (capability_request_id, context_item_id);

--
-- Name: capability_request_basis_links capability_request_basis_links_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_pkey PRIMARY KEY (capability_request_id, ordinal);

--
-- Name: capability_request_decisions capability_request_decisions_capability_request_id_resultin_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_capability_request_id_resultin_key UNIQUE (capability_request_id, resulting_request_version);

--
-- Name: capability_request_decisions capability_request_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_pkey PRIMARY KEY (capability_decision_id);

--
-- Name: capability_requests capability_requests_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_pkey PRIMARY KEY (capability_request_id);

--
-- Name: capability_requests capability_requests_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: codex_result_sources codex_result_sources_codex_verification_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_codex_verification_id_key UNIQUE (codex_verification_id);

--
-- Name: codex_result_sources codex_result_sources_evidence_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_id_key UNIQUE (evidence_id);

--
-- Name: codex_result_sources codex_result_sources_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_opportunity_id_key UNIQUE (opportunity_id);

--
-- Name: codex_result_sources codex_result_sources_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_pkey PRIMARY KEY (codex_result_source_id);

--
-- Name: codex_task_sources codex_task_sources_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_pkey PRIMARY KEY (codex_task_source_id);

--
-- Name: codex_task_sources codex_task_sources_source_bundle_artifact_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_source_bundle_artifact_id_key UNIQUE (source_bundle_artifact_id);

--
-- Name: codex_task_sources codex_task_sources_task_manifest_artifact_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_artifact_id_key UNIQUE (task_manifest_artifact_id);

--
-- Name: codex_task_sources codex_task_sources_task_manifest_digest_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_digest_key UNIQUE (task_manifest_digest);

--
-- Name: codex_verification_results codex_verification_results_effect_attempt_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_attempt_id_key UNIQUE (effect_attempt_id);

--
-- Name: codex_verification_results codex_verification_results_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_id_key UNIQUE (effect_id);

--
-- Name: codex_verification_results codex_verification_results_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_pkey PRIMARY KEY (codex_verification_id);

--
-- Name: cognition_maintenance_batch_sources cognition_maintenance_batch_so_maintenance_batch_id_ordinal_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batch_sources
    ADD CONSTRAINT cognition_maintenance_batch_so_maintenance_batch_id_ordinal_key UNIQUE (maintenance_batch_id, ordinal);

--
-- Name: cognition_maintenance_batch_sources cognition_maintenance_batch_sources_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batch_sources
    ADD CONSTRAINT cognition_maintenance_batch_sources_pkey PRIMARY KEY (maintenance_batch_id, experience_id);

--
-- Name: cognition_maintenance_batches cognition_maintenance_batches_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batches
    ADD CONSTRAINT cognition_maintenance_batches_pkey PRIMARY KEY (maintenance_batch_id);

--
-- Name: cognition_maintenance_cursors cognition_maintenance_cursors_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_cursors
    ADD CONSTRAINT cognition_maintenance_cursors_pkey PRIMARY KEY (subject_id, life_generation_id);

--
-- Name: cognitive_attempts cognitive_attempts_branch_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_branch_attempt_no_key UNIQUE (cognitive_branch_id, attempt_no);

--
-- Name: cognitive_attempts cognitive_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_pkey PRIMARY KEY (model_attempt_id);

--
-- Name: cognitive_branches cognitive_branches_episode_role_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_branches
    ADD CONSTRAINT cognitive_branches_episode_role_key UNIQUE (cognitive_episode_id, branch_role);

--
-- Name: cognitive_branches cognitive_branches_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_branches
    ADD CONSTRAINT cognitive_branches_pkey PRIMARY KEY (cognitive_branch_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_candidate_validation_id_key UNIQUE (candidate_validation_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_pkey PRIMARY KEY (candidate_application_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_subject_commit_id_key UNIQUE (subject_commit_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_successor_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_successor_opportunity_id_key UNIQUE (successor_opportunity_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_work_id_key UNIQUE (work_id);

--
-- Name: cognitive_candidate_basis_links cognitive_candidate_basis_lin_candidate_validation_id_propo_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_lin_candidate_validation_id_propo_key UNIQUE (candidate_validation_id, proposal_ref, context_item_id);

--
-- Name: cognitive_candidate_basis_links cognitive_candidate_basis_links_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_links_pkey PRIMARY KEY (candidate_validation_id, proposal_ref, ordinal);

--
-- Name: cognitive_candidate_validation_items cognitive_candidate_validatio_candidate_validation_id_ordin_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validatio_candidate_validation_id_ordin_key UNIQUE (candidate_validation_id, ordinal);

--
-- Name: cognitive_candidate_validation_items cognitive_candidate_validation_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validation_items_pkey PRIMARY KEY (candidate_validation_id, proposal_ref);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_model_attempt_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_model_attempt_id_key UNIQUE (model_attempt_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_pkey PRIMARY KEY (candidate_validation_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_work_id_key UNIQUE (work_id);

--
-- Name: cognitive_context_items cognitive_context_items_cognitive_episode_id_ordinal_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_cognitive_episode_id_ordinal_key UNIQUE (cognitive_episode_id, ordinal);

--
-- Name: cognitive_context_items cognitive_context_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_pkey PRIMARY KEY (context_item_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_pkey PRIMARY KEY (cognitive_episode_id);

--
-- Name: cognitive_episodes cognitive_episodes_opportunity_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_key UNIQUE (opportunity_id);

--
-- Name: cognitive_episodes cognitive_episodes_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_pkey PRIMARY KEY (cognitive_episode_id);

--
-- Name: context_embedding_attempts context_embedding_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_attempts
    ADD CONSTRAINT context_embedding_attempts_pkey PRIMARY KEY (context_embedding_attempt_id);

--
-- Name: context_embedding_attempts context_embedding_attempts_source_kind_source_ref_source_ve_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_attempts
    ADD CONSTRAINT context_embedding_attempts_source_kind_source_ref_source_ve_key UNIQUE (source_kind, source_ref, source_version, chunk_ordinal, model_binding, context_embedding_attempt_id);

--
-- Name: context_embedding_coverage context_embedding_coverage_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_coverage
    ADD CONSTRAINT context_embedding_coverage_pkey PRIMARY KEY (model_binding);

--
-- Name: context_embedding_projections context_embedding_projections_context_embedding_attempt_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_context_embedding_attempt_id_key UNIQUE (context_embedding_attempt_id);

--
-- Name: context_embedding_projections context_embedding_projections_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_pkey PRIMARY KEY (context_embedding_projection_id);

--
-- Name: context_embedding_projections context_embedding_projections_source_kind_source_ref_source_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_source_kind_source_ref_source_key UNIQUE (source_kind, source_ref, source_version, chunk_ordinal, model_binding);

--
-- Name: creator_exports creator_exports_creator_party_id_directory_name_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_directory_name_key UNIQUE (creator_party_id, directory_name);

--
-- Name: creator_exports creator_exports_creator_party_id_idempotency_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_idempotency_key_key UNIQUE (creator_party_id, idempotency_key);

--
-- Name: creator_exports creator_exports_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_pkey PRIMARY KEY (creator_export_id);

--
-- Name: deletion_items deletion_items_deletion_order_id_target_kind_target_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_deletion_order_id_target_kind_target_ref_key UNIQUE (deletion_order_id, target_kind, target_ref);

--
-- Name: deletion_items deletion_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_pkey PRIMARY KEY (deletion_item_id);

--
-- Name: deletion_orders deletion_orders_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_pkey PRIMARY KEY (deletion_order_id);

--
-- Name: deletion_orders deletion_orders_requester_party_id_idempotency_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_idempotency_key_key UNIQUE (requester_party_id, idempotency_key);

--
-- Name: deletion_orders deletion_orders_requester_party_id_order_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_order_kind_key UNIQUE (requester_party_id, order_kind);

--
-- Name: deployment_environments deployment_environments_environment_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deployment_environments
    ADD CONSTRAINT deployment_environments_environment_id_key UNIQUE (environment_id);

--
-- Name: deployment_environments deployment_environments_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deployment_environments
    ADD CONSTRAINT deployment_environments_pkey PRIMARY KEY (singleton_key);

--
-- Name: dialogue_decisions dialogue_decisions_operation_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_operation_ref_key UNIQUE (operation_ref);

--
-- Name: dialogue_decisions dialogue_decisions_opportunity_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_opportunity_key UNIQUE (opportunity_id);

--
-- Name: dialogue_decisions dialogue_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_pkey PRIMARY KEY (dialogue_decision_id);

--
-- Name: durable_work durable_work_owner_kind_owner_ref_work_kind_idempotency_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_owner_kind_owner_ref_work_kind_idempotency_key_key UNIQUE (owner_kind, owner_ref, work_kind, idempotency_key);

--
-- Name: durable_work durable_work_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_pkey PRIMARY KEY (work_id);

--
-- Name: effect_attempts effect_attempts_attempt_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_attempt_owner_key UNIQUE (effect_attempt_id, effect_id);

--
-- Name: effect_attempts effect_attempts_effect_id_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_attempt_no_key UNIQUE (effect_id, attempt_no);

--
-- Name: effect_attempts effect_attempts_effect_id_claim_token_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_claim_token_key UNIQUE (effect_id, claim_token);

--
-- Name: effect_attempts effect_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_pkey PRIMARY KEY (effect_attempt_id);

--
-- Name: effect_observations effect_observations_effect_attempt_id_observation_kind_obse_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_attempt_id_observation_kind_obse_key UNIQUE (effect_attempt_id, observation_kind, observation_digest);

--
-- Name: effect_observations effect_observations_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_owner_key UNIQUE (effect_observation_id, effect_id, effect_attempt_id);

--
-- Name: effect_observations effect_observations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_pkey PRIMARY KEY (effect_observation_id);

--
-- Name: effect_outbox_items effect_outbox_items_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_effect_id_key UNIQUE (effect_id);

--
-- Name: effect_outbox_items effect_outbox_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_pkey PRIMARY KEY (effect_outbox_item_id);

--
-- Name: effects effects_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_pkey PRIMARY KEY (effect_id);

--
-- Name: effects effects_revision_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_revision_key UNIQUE (action_intent_revision_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_execution_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_execution_work_id_key UNIQUE (execution_work_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_pkey PRIMARY KEY (exact_life_query_intent_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_result_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_opportunity_id_key UNIQUE (result_opportunity_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_source_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_source_opportunity_id_key UNIQUE (source_opportunity_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_commit_id_key UNIQUE (subject_commit_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_subject_id_source_opportunity_id_p_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_id_source_opportunity_id_p_key UNIQUE (subject_id, source_opportunity_id, proposal_ref);

--
-- Name: experience_evidence_links experience_evidence_links_experience_id_evidence_id_context_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_experience_id_evidence_id_context_key UNIQUE (experience_id, evidence_id, context_item_id);

--
-- Name: experience_evidence_links experience_evidence_links_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_pkey PRIMARY KEY (experience_id, ordinal);

--
-- Name: external_channel_bindings external_channel_bindings_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_identity_unique UNIQUE (channel_kind, account_key, external_kind, external_key);

--
-- Name: external_channel_bindings external_channel_bindings_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_pkey PRIMARY KEY (external_binding_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_attem_external_message_part_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_attem_external_message_part_id_key UNIQUE (external_message_part_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_attempts_pkey PRIMARY KEY (recognition_attempt_id);

--
-- Name: external_evidence external_evidence_interaction_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_interaction_key UNIQUE (interaction_id);

--
-- Name: external_evidence external_evidence_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_pkey PRIMARY KEY (evidence_id);

--
-- Name: external_message_parts external_message_parts_interaction_id_ordinal_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_message_parts
    ADD CONSTRAINT external_message_parts_interaction_id_ordinal_key UNIQUE (interaction_id, ordinal);

--
-- Name: external_message_parts external_message_parts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_message_parts
    ADD CONSTRAINT external_message_parts_pkey PRIMARY KEY (external_message_part_id);

--
-- Name: interaction_scenes interaction_scenes_input_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_input_identity_unique UNIQUE (scene_id, subject_id, primary_party_id);

--
-- Name: interaction_scenes interaction_scenes_party_key_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_party_key_unique UNIQUE (subject_id, primary_party_id, scene_key);

--
-- Name: interaction_scenes interaction_scenes_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_pkey PRIMARY KEY (scene_id);

--
-- Name: interaction_scenes interaction_scenes_subject_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_subject_identity_unique UNIQUE (scene_id, subject_id);

--
-- Name: life_generations life_generations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_pkey PRIMARY KEY (life_generation_id);

--
-- Name: life_generations life_generations_subject_id_generation_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_subject_id_generation_no_key UNIQUE (subject_id, generation_no);

--
-- Name: life_material_revisions life_material_revisions_life_material_id_life_material_revi_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_life_material_revi_key UNIQUE (life_material_id, life_material_revision_id);

--
-- Name: life_material_revisions life_material_revisions_life_material_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_revision_no_key UNIQUE (life_material_id, revision_no);

--
-- Name: life_material_revisions life_material_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_pkey PRIMARY KEY (life_material_revision_id);

--
-- Name: life_material_revisions life_material_revisions_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: life_materials life_materials_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_pkey PRIMARY KEY (life_material_id);

--
-- Name: live_vision_observation_frames live_vision_observation_frames_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observation_frames
    ADD CONSTRAINT live_vision_observation_frames_pkey PRIMARY KEY (observation_id, ordinal);

--
-- Name: live_vision_observations live_vision_observations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observations
    ADD CONSTRAINT live_vision_observations_pkey PRIMARY KEY (observation_id);

--
-- Name: live_vision_observations live_vision_observations_session_id_observation_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observations
    ADD CONSTRAINT live_vision_observations_session_id_observation_no_key UNIQUE (session_id, observation_no);

--
-- Name: live_vision_sessions live_vision_sessions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_sessions
    ADD CONSTRAINT live_vision_sessions_pkey PRIMARY KEY (session_id);

--
-- Name: live_voice_playback_attempts live_voice_playback_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_playback_attempts
    ADD CONSTRAINT live_voice_playback_attempts_pkey PRIMARY KEY (playback_attempt_id);

--
-- Name: live_voice_playback_attempts live_voice_playback_attempts_turn_id_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_playback_attempts
    ADD CONSTRAINT live_voice_playback_attempts_turn_id_attempt_no_key UNIQUE (turn_id, attempt_no);

--
-- Name: live_voice_provider_attempts live_voice_provider_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_provider_attempts
    ADD CONSTRAINT live_voice_provider_attempts_pkey PRIMARY KEY (provider_attempt_id);

--
-- Name: live_voice_provider_attempts live_voice_provider_attempts_turn_id_service_kind_attempt_n_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_provider_attempts
    ADD CONSTRAINT live_voice_provider_attempts_turn_id_service_kind_attempt_n_key UNIQUE (turn_id, service_kind, attempt_no);

--
-- Name: live_voice_sessions live_voice_sessions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_sessions
    ADD CONSTRAINT live_voice_sessions_pkey PRIMARY KEY (session_id);

--
-- Name: live_voice_text_fragments live_voice_text_fragments_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_text_fragments
    ADD CONSTRAINT live_voice_text_fragments_pkey PRIMARY KEY (fragment_id);

--
-- Name: live_voice_text_fragments live_voice_text_fragments_turn_id_fragment_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_text_fragments
    ADD CONSTRAINT live_voice_text_fragments_turn_id_fragment_no_key UNIQUE (turn_id, fragment_no);

--
-- Name: live_voice_turns live_voice_turns_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_turns
    ADD CONSTRAINT live_voice_turns_pkey PRIMARY KEY (turn_id);

--
-- Name: live_voice_turns live_voice_turns_session_id_turn_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_turns
    ADD CONSTRAINT live_voice_turns_session_id_turn_no_key UNIQUE (session_id, turn_no);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_effect_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_effect_key UNIQUE (effect_id);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_pkey PRIMARY KEY (delivery_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_application_id_key UNIQUE (candidate_application_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_validation_id_key UNIQUE (candidate_validation_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_maintenance_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_revision_id_key UNIQUE (maintenance_revision_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_opportunity_id_key UNIQUE (opportunity_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_pkey PRIMARY KEY (maintenance_phase_result_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_subject_commit_id_key UNIQUE (subject_commit_id);

--
-- Name: maintenance_session_revisions maintenance_session_revisions_maintenance_revision_id_maint_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_revision_id_maint_key UNIQUE (maintenance_revision_id, maintenance_session_id);

--
-- Name: maintenance_session_revisions maintenance_session_revisions_maintenance_session_id_revisi_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_session_id_revisi_key UNIQUE (maintenance_session_id, revision_no);

--
-- Name: maintenance_session_revisions maintenance_session_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_pkey PRIMARY KEY (maintenance_revision_id);

--
-- Name: maintenance_sessions maintenance_sessions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_pkey PRIMARY KEY (maintenance_session_id);

--
-- Name: maintenance_sessions maintenance_sessions_sleep_decision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_sleep_decision_id_key UNIQUE (sleep_decision_id);

--
-- Name: maintenance_sessions maintenance_sessions_subject_id_life_generation_id_cycle_an_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_subject_id_life_generation_id_cycle_an_key UNIQUE (subject_id, life_generation_id, cycle_anchor_ref);

--
-- Name: maintenance_sessions maintenance_sessions_wake_request_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_wake_request_id_key UNIQUE (wake_request_id);

--
-- Name: memory_relations memory_relations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_pkey PRIMARY KEY (memory_relation_id);

--
-- Name: memory_relations memory_relations_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: mood_affective_events mood_affective_events_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_affective_events
    ADD CONSTRAINT mood_affective_events_pkey PRIMARY KEY (mood_affective_event_id);

--
-- Name: mood_affective_events mood_affective_events_revision_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_affective_events
    ADD CONSTRAINT mood_affective_events_revision_key UNIQUE (mood_revision_id, subject_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_identity_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_identity_key UNIQUE (mood_appraisal_event_id, subject_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_pkey PRIMARY KEY (mood_appraisal_event_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_revision_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_revision_key UNIQUE (mood_revision_id, subject_id);

--
-- Name: mood_heads mood_heads_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_heads
    ADD CONSTRAINT mood_heads_pkey PRIMARY KEY (subject_id);

--
-- Name: mood_revisions mood_revisions_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_owner_key UNIQUE (mood_revision_id, subject_id);

--
-- Name: mood_revisions mood_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_pkey PRIMARY KEY (mood_revision_id);

--
-- Name: mood_revisions mood_revisions_subject_version_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_subject_version_key UNIQUE (subject_id, mood_version);

--
-- Name: observation_attempts observation_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_pkey PRIMARY KEY (observation_attempt_id);

--
-- Name: observation_attempts observation_attempts_web_observation_request_id_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_attempt_no_key UNIQUE (web_observation_request_id, attempt_no);

--
-- Name: observation_attempts observation_attempts_web_observation_request_id_work_attemp_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_work_attemp_key UNIQUE (web_observation_request_id, work_attempt_id);

--
-- Name: observation_tool_calls observation_tool_calls_observation_attempt_id_call_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_call_no_key UNIQUE (observation_attempt_id, call_no);

--
-- Name: observation_tool_calls observation_tool_calls_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_pkey PRIMARY KEY (observation_tool_call_id);

--
-- Name: opportunities opportunities_episode_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_episode_owner_key UNIQUE (opportunity_id, subject_id);

--
-- Name: opportunities opportunities_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_pkey PRIMARY KEY (opportunity_id);

--
-- Name: opportunities opportunities_subject_source_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_subject_source_key UNIQUE (subject_id, source_kind, source_ref, source_version, purpose, reconsideration_no);

--
-- Name: parties parties_id_kind_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_id_kind_unique UNIQUE (party_id, party_kind);

--
-- Name: parties parties_party_subject_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_party_subject_unique UNIQUE (party_id, represented_subject_id);

--
-- Name: parties parties_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_pkey PRIMARY KEY (party_id);

--
-- Name: party_input_interactions party_input_interactions_idempotency_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_idempotency_key UNIQUE (source_party_id, scene_id, purpose, idempotency_key);

--
-- Name: party_input_interactions party_input_interactions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_pkey PRIMARY KEY (interaction_id);

--
-- Name: party_input_interactions party_input_interactions_scope_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_scope_key UNIQUE (interaction_id, subject_id, scene_id, source_party_id);

--
-- Name: permission_grants permission_grants_capability_request_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_request_id_key UNIQUE (capability_request_id);

--
-- Name: permission_grants permission_grants_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_pkey PRIMARY KEY (grant_id);

--
-- Name: policy_decisions policy_decisions_effect_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_effect_owner_key UNIQUE (policy_decision_id, action_intent_revision_id);

--
-- Name: policy_decisions policy_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_pkey PRIMARY KEY (policy_decision_id);

--
-- Name: prompt_documents prompt_documents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_pkey PRIMARY KEY (prompt_document_id);

--
-- Name: prompt_documents prompt_documents_subject_id_prompt_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_subject_id_prompt_kind_key UNIQUE (subject_id, prompt_kind);

--
-- Name: prompt_revisions prompt_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_pkey PRIMARY KEY (prompt_revision_id);

--
-- Name: prompt_revisions prompt_revisions_prompt_document_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_prompt_document_id_revision_no_key UNIQUE (prompt_document_id, revision_no);

--
-- Name: prompt_revisions prompt_revisions_prompt_revision_id_prompt_document_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_prompt_revision_id_prompt_document_id_key UNIQUE (prompt_revision_id, prompt_document_id);

--
-- Name: relationship_experience_links relationship_experience_links_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_pkey PRIMARY KEY (relationship_revision_id, experience_id, link_kind);

--
-- Name: relationship_experience_links relationship_experience_links_relationship_revision_id_ordi_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_relationship_revision_id_ordi_key UNIQUE (relationship_revision_id, ordinal);

--
-- Name: relationship_revisions relationship_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_pkey PRIMARY KEY (relationship_revision_id);

--
-- Name: relationship_revisions relationship_revisions_relationship_id_relationship_revisio_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_relationship_revisio_key UNIQUE (relationship_id, relationship_revision_id);

--
-- Name: relationship_revisions relationship_revisions_relationship_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_revision_no_key UNIQUE (relationship_id, revision_no);

--
-- Name: relationship_revisions relationship_revisions_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: relationships relationships_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_pkey PRIMARY KEY (relationship_id);

--
-- Name: relationships relationships_subject_id_other_party_id_scope_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_id_other_party_id_scope_key UNIQUE (subject_id, other_party_id, scope);

--
-- Name: runtime_bundle_activations runtime_bundle_activations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_pkey PRIMARY KEY (bundle_activation_id);

--
-- Name: runtime_instances runtime_instances_life_generation_id_fence_token_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_life_generation_id_fence_token_key UNIQUE (life_generation_id, fence_token);

--
-- Name: runtime_instances runtime_instances_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_pkey PRIMARY KEY (runtime_instance_id);

--
-- Name: runtime_recovery_metrics runtime_recovery_metrics_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_metrics
    ADD CONSTRAINT runtime_recovery_metrics_pkey PRIMARY KEY (recovery_run_id, metric_kind);

--
-- Name: runtime_recovery_runs runtime_recovery_runs_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_pkey PRIMARY KEY (recovery_run_id);

--
-- Name: runtime_recovery_runs runtime_recovery_runs_runtime_instance_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_runtime_instance_id_key UNIQUE (runtime_instance_id);

--
-- Name: scene_participants scene_participants_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_participants
    ADD CONSTRAINT scene_participants_identity_unique UNIQUE (scene_id, subject_id, party_id);

--
-- Name: scene_participants scene_participants_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_participants
    ADD CONSTRAINT scene_participants_pkey PRIMARY KEY (scene_id, party_id);

--
-- Name: scene_timeline_items scene_timeline_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_pkey PRIMARY KEY (timeline_item_id);

--
-- Name: scene_timeline_items scene_timeline_items_scene_id_source_kind_source_ref_source_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_scene_id_source_kind_source_ref_source_key UNIQUE (scene_id, source_kind, source_ref, source_event_no);

--
-- Name: sleep_decisions sleep_decisions_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_application_id_key UNIQUE (candidate_application_id);

--
-- Name: sleep_decisions sleep_decisions_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_validation_id_key UNIQUE (candidate_validation_id);

--
-- Name: sleep_decisions sleep_decisions_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

--
-- Name: sleep_decisions sleep_decisions_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_opportunity_id_key UNIQUE (opportunity_id);

--
-- Name: sleep_decisions sleep_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_pkey PRIMARY KEY (sleep_decision_id);

--
-- Name: subject_commits subject_commits_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_candidate_validation_id_key UNIQUE (candidate_validation_id);

--
-- Name: subject_commits subject_commits_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_cognitive_episode_id_key UNIQUE (cognitive_episode_id);

--
-- Name: subject_commits subject_commits_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_pkey PRIMARY KEY (subject_commit_id);

--
-- Name: subject_commits subject_commits_subject_commit_id_subject_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_subject_commit_id_subject_id_key UNIQUE (subject_commit_id, subject_id);

--
-- Name: subject_commits subject_commits_subject_id_new_subject_version_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_subject_id_new_subject_version_key UNIQUE (subject_id, new_subject_version);

--
-- Name: subject_component_heads subject_component_heads_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_pkey PRIMARY KEY (subject_id, component_kind);

--
-- Name: subject_component_revisions subject_component_revisions_component_revision_owner_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_component_revision_owner_key UNIQUE (component_revision_id, subject_id, component_kind);

--
-- Name: subject_component_revisions subject_component_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_pkey PRIMARY KEY (component_revision_id);

--
-- Name: subject_component_revisions subject_component_revisions_subject_id_component_kind_compo_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_subject_id_component_kind_compo_key UNIQUE (subject_id, component_kind, component_version);

--
-- Name: subjective_memories subjective_memories_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_pkey PRIMARY KEY (memory_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_memory_id_memory_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_memory_revision_id_key UNIQUE (memory_id, memory_revision_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_memory_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_revision_no_key UNIQUE (memory_id, revision_no);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_pkey PRIMARY KEY (memory_revision_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_subject_commit_id_proposal_ref_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_subject_commit_id_proposal_ref_key UNIQUE (subject_commit_id, proposal_ref);

--
-- Name: subjects subjects_birth_idempotency_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_birth_idempotency_key_key UNIQUE (birth_idempotency_key);

--
-- Name: subjects subjects_birth_request_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_birth_request_id_key UNIQUE (birth_request_id);

--
-- Name: subjects subjects_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (subject_id);

--
-- Name: subjects subjects_singleton_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_singleton_key_key UNIQUE (singleton_key);

--
-- Name: visual_recognition_attempts visual_recognition_attempts_observation_id_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.visual_recognition_attempts
    ADD CONSTRAINT visual_recognition_attempts_observation_id_attempt_no_key UNIQUE (observation_id, attempt_no);

--
-- Name: visual_recognition_attempts visual_recognition_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.visual_recognition_attempts
    ADD CONSTRAINT visual_recognition_attempts_pkey PRIMARY KEY (visual_attempt_id);

--
-- Name: web_evidence_sources web_evidence_sources_evidence_id_canonical_url_digest_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_canonical_url_digest_key UNIQUE (evidence_id, canonical_url_digest);

--
-- Name: web_evidence_sources web_evidence_sources_evidence_id_citation_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_citation_no_key UNIQUE (evidence_id, citation_no);

--
-- Name: web_evidence_sources web_evidence_sources_observation_attempt_id_citation_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_observation_attempt_id_citation_no_key UNIQUE (observation_attempt_id, citation_no);

--
-- Name: web_evidence_sources web_evidence_sources_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_pkey PRIMARY KEY (web_evidence_source_id);

--
-- Name: web_observation_requests web_observation_requests_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_pkey PRIMARY KEY (web_observation_request_id);

--
-- Name: web_observation_requests web_observation_requests_subject_id_purpose_idempotency_key_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_subject_id_purpose_idempotency_key_key UNIQUE (subject_id, purpose, idempotency_key);

--
-- Name: web_observation_requests web_observation_requests_web_research_intent_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_web_research_intent_id_key UNIQUE (web_research_intent_id);

--
-- Name: web_observation_requests web_observation_requests_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_work_id_key UNIQUE (work_id);

--
-- Name: web_research_intents web_research_intents_admission_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_admission_work_id_key UNIQUE (admission_work_id);

--
-- Name: web_research_intents web_research_intents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_pkey PRIMARY KEY (web_research_intent_id);

--
-- Name: web_research_intents web_research_intents_source_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_source_opportunity_id_key UNIQUE (source_opportunity_id);

--
-- Name: web_research_intents web_research_intents_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_commit_id_key UNIQUE (subject_commit_id);

--
-- Name: web_research_intents web_research_intents_subject_id_source_opportunity_id_propo_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_id_source_opportunity_id_propo_key UNIQUE (subject_id, source_opportunity_id, proposal_ref);

--
-- Name: web_research_intents web_research_intents_web_observation_request_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_web_observation_request_id_key UNIQUE (web_observation_request_id);

--
-- Name: accepted_experiences_gist_trgm_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX accepted_experiences_gist_trgm_idx ON armi.accepted_experiences USING gin (first_person_gist armi_extensions.gin_trgm_ops);

--
-- Name: accepted_experiences_subject_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX accepted_experiences_subject_idx ON armi.accepted_experiences USING btree (subject_commit_id, experience_id);

--
-- Name: accepted_experiences_subject_page_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX accepted_experiences_subject_page_idx ON armi.accepted_experiences USING btree (subject_id, accepted_at DESC, experience_id DESC);

--
-- Name: audit_events_request_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX audit_events_request_idx ON armi.audit_events USING btree (request_kind, request_ref, occurred_at, audit_event_id) WHERE (request_ref IS NOT NULL);

--
-- Name: audit_events_subject_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX audit_events_subject_idx ON armi.audit_events USING btree (subject_id, occurred_at, audit_event_id) WHERE (subject_id IS NOT NULL);

--
-- Name: audit_events_target_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX audit_events_target_idx ON armi.audit_events USING btree (target_kind, target_ref, occurred_at, audit_event_id);

--
-- Name: audit_events_trace_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX audit_events_trace_idx ON armi.audit_events USING btree (trace_id, occurred_at, audit_event_id);

--
-- Name: candidate_applications_resolution_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX candidate_applications_resolution_idx ON armi.cognitive_candidate_applications USING btree (resolution, resolved_at, candidate_application_id);

--
-- Name: capability_requests_creator_page_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX capability_requests_creator_page_idx ON armi.capability_requests USING btree (creator_party_id, created_at DESC, capability_request_id DESC);

--
-- Name: capability_requests_open_codex_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX capability_requests_open_codex_idx ON armi.capability_requests USING btree (subject_id, capability_kind, operation_class) WHERE ((capability_kind = 'codex.delegated-work'::text) AND (current_status = ANY (ARRAY['pending'::text, 'granted'::text, 'limited'::text])));

--
-- Name: capability_requests_pending_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX capability_requests_pending_idx ON armi.capability_requests USING btree (current_status, created_at, capability_request_id);

--
-- Name: cognition_maintenance_batches_active_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX cognition_maintenance_batches_active_idx ON armi.cognition_maintenance_batches USING btree (subject_id, life_generation_id) WHERE (status = ANY (ARRAY['prepared'::text, 'running'::text]));

--
-- Name: cognitive_attempts_branch_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_attempts_branch_status_idx ON armi.cognitive_attempts USING btree (cognitive_branch_id, dispatch_status, attempt_no);

--
-- Name: cognitive_attempts_episode_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_attempts_episode_status_idx ON armi.cognitive_attempts USING btree (cognitive_episode_id, dispatch_status, attempt_no);

--
-- Name: cognitive_branches_episode_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_branches_episode_status_idx ON armi.cognitive_branches USING btree (cognitive_episode_id, status, branch_role);

--
-- Name: cognitive_candidate_validations_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_candidate_validations_status_idx ON armi.cognitive_candidate_validations USING btree (validation_status, validated_at, candidate_validation_id);

--
-- Name: cognitive_episodes_subject_purpose_recent_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_episodes_subject_purpose_recent_idx ON armi.cognitive_episodes USING btree (subject_id, purpose, created_at DESC, cognitive_episode_id DESC);

--
-- Name: context_embedding_projections_current_source_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX context_embedding_projections_current_source_idx ON armi.context_embedding_projections USING btree (subject_id, life_generation_id, source_kind, source_ref, source_version, model_binding);

--
-- Name: context_embedding_projections_embedding_hnsw_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX context_embedding_projections_embedding_hnsw_idx ON armi.context_embedding_projections USING hnsw (((embedding)::armi_extensions.halfvec(1024)) armi_extensions.halfvec_cosine_ops) WITH (m='16', ef_construction='128');

--
-- Name: context_embedding_projections_retrieval_gist_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX context_embedding_projections_retrieval_gist_idx ON armi.context_embedding_projections USING gist (retrieval_text armi_extensions.gist_trgm_ops (siglen='256'));

--
-- Name: deletion_items_active_target_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX deletion_items_active_target_idx ON armi.deletion_items USING btree (target_kind, target_ref) WHERE (result_status = ANY (ARRAY['completed'::text, 'partial'::text]));

--
-- Name: deletion_items_order_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX deletion_items_order_status_idx ON armi.deletion_items USING btree (deletion_order_id, result_status, target_kind);

--
-- Name: deletion_orders_effective_party_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX deletion_orders_effective_party_idx ON armi.deletion_orders USING btree (requester_party_id, order_kind) WHERE (status = 'effective'::text);

--
-- Name: durable_work_claim_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX durable_work_claim_idx ON armi.durable_work USING btree (status, not_before, priority DESC, work_id) WHERE (status = ANY (ARRAY['ready'::text, 'leased'::text]));

--
-- Name: durable_work_expired_lease_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX durable_work_expired_lease_idx ON armi.durable_work USING btree (lease_expires_at, work_id) WHERE (status = 'leased'::text);

--
-- Name: effect_outbox_items_claim_expiry_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX effect_outbox_items_claim_expiry_idx ON armi.effect_outbox_items USING btree (claim_expires_at, effect_outbox_item_id) WHERE (status = 'claimed'::text);

--
-- Name: effect_outbox_items_ready_claim_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX effect_outbox_items_ready_claim_idx ON armi.effect_outbox_items USING btree (available_at, effect_outbox_item_id) WHERE (status = 'ready'::text);

--
-- Name: effects_unknown_settlement_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX effects_unknown_settlement_idx ON armi.effects USING btree (settled_at, effect_id) WHERE (status = 'unknown'::text);

--
-- Name: external_channel_bindings_group_scene_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX external_channel_bindings_group_scene_idx ON armi.external_channel_bindings USING btree (scene_id) WHERE (external_kind = 'group'::text);

--
-- Name: external_channel_bindings_person_party_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX external_channel_bindings_person_party_idx ON armi.external_channel_bindings USING btree (channel_kind, account_key, party_id) WHERE (external_kind = 'person'::text);

--
-- Name: external_message_parts_interaction_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX external_message_parts_interaction_idx ON armi.external_message_parts USING btree (interaction_id, ordinal);

--
-- Name: external_message_parts_pending_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX external_message_parts_pending_idx ON armi.external_message_parts USING btree (processing_status, interaction_id) WHERE (processing_status = 'pending'::text);

--
-- Name: life_generations_one_active_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX life_generations_one_active_idx ON armi.life_generations USING btree (subject_id) WHERE (status = 'active'::text);

--
-- Name: life_material_revisions_material_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX life_material_revisions_material_idx ON armi.life_material_revisions USING btree (life_material_id, revision_no DESC);

--
-- Name: life_material_revisions_title_trgm_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX life_material_revisions_title_trgm_idx ON armi.life_material_revisions USING gin (title armi_extensions.gin_trgm_ops);

--
-- Name: life_materials_subject_current_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX life_materials_subject_current_idx ON armi.life_materials USING btree (subject_id, updated_at DESC, life_material_id) WHERE (deleted_at IS NULL);

--
-- Name: live_vision_one_open_session; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX live_vision_one_open_session ON armi.live_vision_sessions USING btree (subject_id) WHERE (ended_at IS NULL);

--
-- Name: live_voice_one_open_session; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX live_voice_one_open_session ON armi.live_voice_sessions USING btree (subject_id) WHERE (ended_at IS NULL);

--
-- Name: maintenance_sessions_one_unfinished; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX maintenance_sessions_one_unfinished ON armi.maintenance_sessions USING btree (subject_id) WHERE (finished_at IS NULL);

--
-- Name: memory_relations_from_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX memory_relations_from_idx ON armi.memory_relations USING btree (from_memory_id, created_at DESC);

--
-- Name: memory_relations_to_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX memory_relations_to_idx ON armi.memory_relations USING btree (to_memory_id, created_at DESC);

--
-- Name: mood_affective_events_subject_time_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX mood_affective_events_subject_time_idx ON armi.mood_affective_events USING btree (subject_id, occurred_at DESC, mood_affective_event_id DESC);

--
-- Name: mood_appraisal_events_episode_time_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX mood_appraisal_events_episode_time_idx ON armi.mood_appraisal_events USING btree (subject_id, mood_episode_id, occurred_at DESC, mood_appraisal_event_id DESC);

--
-- Name: mood_appraisal_events_previous_unique_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX mood_appraisal_events_previous_unique_idx ON armi.mood_appraisal_events USING btree (previous_appraisal_event_id) WHERE (previous_appraisal_event_id IS NOT NULL);

--
-- Name: mood_appraisal_events_subject_time_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX mood_appraisal_events_subject_time_idx ON armi.mood_appraisal_events USING btree (subject_id, occurred_at DESC, mood_appraisal_event_id DESC);

--
-- Name: mood_revisions_subject_created_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX mood_revisions_subject_created_idx ON armi.mood_revisions USING btree (subject_id, created_at DESC, mood_revision_id DESC);

--
-- Name: parties_one_creator_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX parties_one_creator_idx ON armi.parties USING btree (creator_role) WHERE (party_kind = 'creator'::text);

--
-- Name: parties_one_subject_party_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX parties_one_subject_party_idx ON armi.parties USING btree (represented_subject_id) WHERE (party_kind = 'subject'::text);

--
-- Name: parties_other_human_declared_identity_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX parties_other_human_declared_identity_idx ON armi.parties USING btree (declared_identity_key) WHERE (party_kind = 'other_human'::text);

--
-- Name: parties_social_group_declared_identity_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX parties_social_group_declared_identity_idx ON armi.parties USING btree (declared_identity_key) WHERE (party_kind = 'social_group'::text);

--
-- Name: party_input_interactions_external_message_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX party_input_interactions_external_message_idx ON armi.party_input_interactions USING btree (external_binding_id, external_message_key) WHERE (external_binding_id IS NOT NULL);

--
-- Name: policy_decisions_one_current; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX policy_decisions_one_current ON armi.policy_decisions USING btree (action_intent_revision_id) WHERE is_current;

--
-- Name: relationship_revisions_interpretation_trgm_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX relationship_revisions_interpretation_trgm_idx ON armi.relationship_revisions USING gin (interpretation armi_extensions.gin_trgm_ops);

--
-- Name: relationship_revisions_relationship_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX relationship_revisions_relationship_idx ON armi.relationship_revisions USING btree (relationship_id, revision_no DESC);

--
-- Name: relationships_active_other_party_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX relationships_active_other_party_idx ON armi.relationships USING btree (other_party_id, scope) WHERE (tombstoned_at IS NULL);

--
-- Name: relationships_subject_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX relationships_subject_idx ON armi.relationships USING btree (subject_id, created_at DESC, relationship_id);

--
-- Name: runtime_bundle_one_current_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX runtime_bundle_one_current_idx ON armi.runtime_bundle_activations USING btree (subject_id) WHERE (status = 'current'::text);

--
-- Name: runtime_instances_one_active_generation_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX runtime_instances_one_active_generation_idx ON armi.runtime_instances USING btree (life_generation_id) WHERE (status = 'active'::text);

--
-- Name: runtime_recovery_runs_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX runtime_recovery_runs_status_idx ON armi.runtime_recovery_runs USING btree (status, started_at, recovery_run_id);

--
-- Name: scene_timeline_items_page_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX scene_timeline_items_page_idx ON armi.scene_timeline_items USING btree (scene_id, occurred_at DESC, timeline_item_id DESC);

--
-- Name: subject_component_revisions_payload_trgm_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX subject_component_revisions_payload_trgm_idx ON armi.subject_component_revisions USING gin (((semantic_payload)::text) armi_extensions.gin_trgm_ops);

--
-- Name: subjective_memories_subject_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX subjective_memories_subject_idx ON armi.subjective_memories USING btree (subject_id, created_at DESC, memory_id);

--
-- Name: subjective_memory_revisions_memory_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX subjective_memory_revisions_memory_idx ON armi.subjective_memory_revisions USING btree (memory_id, revision_no DESC);

--
-- Name: subjective_memory_revisions_source_formation_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX subjective_memory_revisions_source_formation_idx ON armi.subjective_memory_revisions USING btree (source_experience_id) WHERE (revision_no = 1);

--
-- Name: subjective_memory_revisions_summary_trgm_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX subjective_memory_revisions_summary_trgm_idx ON armi.subjective_memory_revisions USING gin (summary armi_extensions.gin_trgm_ops);

--
-- Name: accepted_experiences accepted_experiences_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: accepted_experiences accepted_experiences_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: accepted_experiences accepted_experiences_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: accepted_experiences accepted_experiences_subject_commit_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_subject_commit_owner_fkey FOREIGN KEY (subject_commit_id, subject_id) REFERENCES armi.subject_commits(subject_commit_id, subject_id);

--
-- Name: action_intent_revisions action_intent_revisions_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_artifact_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: action_intent_revisions action_intent_revisions_candidate_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_candidate_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);

--
-- Name: action_intent_revisions action_intent_revisions_codex_source_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_codex_source_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);

--
-- Name: action_intent_revisions action_intent_revisions_commit_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: action_intent_revisions action_intent_revisions_intent_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_intent_fkey FOREIGN KEY (action_intent_id) REFERENCES armi.action_intents(action_intent_id);

--
-- Name: action_intents action_intents_current_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_current_revision_fkey FOREIGN KEY (current_revision_id, action_intent_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id, action_intent_id);

--
-- Name: action_intents action_intents_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);

--
-- Name: action_intents action_intents_root_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_root_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: action_intents action_intents_scene_participant_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_scene_participant_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

--
-- Name: activities activities_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_current_revision_fk FOREIGN KEY (current_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

--
-- Name: activities activities_origin_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_origin_opportunity_id_fkey FOREIGN KEY (origin_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: activities activities_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: activity_decisions activity_decisions_activity_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_activity_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);

--
-- Name: activity_decisions activity_decisions_application_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_application_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

--
-- Name: activity_decisions activity_decisions_episode_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_episode_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: activity_decisions activity_decisions_expected_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_expected_revision_fkey FOREIGN KEY (expected_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

--
-- Name: activity_decisions activity_decisions_opportunity_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: activity_decisions activity_decisions_output_material_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_output_material_fkey FOREIGN KEY (output_material_id) REFERENCES armi.life_materials(life_material_id);

--
-- Name: activity_decisions activity_decisions_result_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_result_revision_fkey FOREIGN KEY (result_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

--
-- Name: activity_decisions activity_decisions_validation_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_decisions
    ADD CONSTRAINT activity_decisions_validation_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: activity_revisions activity_revisions_activity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);

--
-- Name: activity_revisions activity_revisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: activity_revisions activity_revisions_previous_revision_id_activity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_previous_revision_id_activity_id_fkey FOREIGN KEY (previous_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);

--
-- Name: activity_revisions activity_revisions_related_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_related_scene_id_fkey FOREIGN KEY (related_scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: activity_revisions activity_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_revisions
    ADD CONSTRAINT activity_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: capability_request_basis_links capability_request_basis_links_capability_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

--
-- Name: capability_request_basis_links capability_request_basis_links_context_item_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_basis_links
    ADD CONSTRAINT capability_request_basis_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

--
-- Name: capability_request_decisions capability_request_decisions_capability_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

--
-- Name: capability_request_decisions capability_request_decisions_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_request_decisions
    ADD CONSTRAINT capability_request_decisions_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: capability_requests capability_requests_capability_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_capability_id_fkey FOREIGN KEY (capability_id) REFERENCES armi.capabilities(capability_id);

--
-- Name: capability_requests capability_requests_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: capability_requests capability_requests_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: capability_requests capability_requests_resolved_by_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_resolved_by_party_id_fkey FOREIGN KEY (resolved_by_party_id) REFERENCES armi.parties(party_id);

--
-- Name: capability_requests capability_requests_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: capability_requests capability_requests_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.capability_requests
    ADD CONSTRAINT capability_requests_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: codex_result_sources codex_result_sources_codex_verification_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_codex_verification_id_fkey FOREIGN KEY (codex_verification_id) REFERENCES armi.codex_verification_results(codex_verification_id);

--
-- Name: codex_result_sources codex_result_sources_evidence_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_artifact_id_fkey FOREIGN KEY (evidence_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_result_sources codex_result_sources_evidence_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

--
-- Name: codex_result_sources codex_result_sources_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_result_sources
    ADD CONSTRAINT codex_result_sources_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: codex_task_sources codex_task_sources_source_bundle_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_source_bundle_artifact_id_fkey FOREIGN KEY (source_bundle_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_task_sources codex_task_sources_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: codex_task_sources codex_task_sources_task_manifest_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_task_sources
    ADD CONSTRAINT codex_task_sources_task_manifest_artifact_id_fkey FOREIGN KEY (task_manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_diagnostics_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_diagnostics_artifact_id_fkey FOREIGN KEY (diagnostics_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_effect_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_attempt_id_fkey FOREIGN KEY (effect_attempt_id) REFERENCES armi.effect_attempts(effect_attempt_id);

--
-- Name: codex_verification_results codex_verification_results_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: codex_verification_results codex_verification_results_event_transcript_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_event_transcript_artifact_id_fkey FOREIGN KEY (event_transcript_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_final_result_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_final_result_artifact_id_fkey FOREIGN KEY (final_result_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_patch_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_patch_artifact_id_fkey FOREIGN KEY (patch_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_result_bundle_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_result_bundle_artifact_id_fkey FOREIGN KEY (result_bundle_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: codex_verification_results codex_verification_results_validation_report_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.codex_verification_results
    ADD CONSTRAINT codex_verification_results_validation_report_artifact_id_fkey FOREIGN KEY (validation_report_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognition_maintenance_batch_sources cognition_maintenance_batch_sources_experience_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batch_sources
    ADD CONSTRAINT cognition_maintenance_batch_sources_experience_id_fkey FOREIGN KEY (experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: cognition_maintenance_batch_sources cognition_maintenance_batch_sources_maintenance_batch_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batch_sources
    ADD CONSTRAINT cognition_maintenance_batch_sources_maintenance_batch_id_fkey FOREIGN KEY (maintenance_batch_id) REFERENCES armi.cognition_maintenance_batches(maintenance_batch_id);

--
-- Name: cognition_maintenance_batches cognition_maintenance_batches_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batches
    ADD CONSTRAINT cognition_maintenance_batches_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: cognition_maintenance_batches cognition_maintenance_batches_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_batches
    ADD CONSTRAINT cognition_maintenance_batches_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: cognition_maintenance_cursors cognition_maintenance_cursors_last_experience_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_cursors
    ADD CONSTRAINT cognition_maintenance_cursors_last_experience_id_fkey FOREIGN KEY (last_experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: cognition_maintenance_cursors cognition_maintenance_cursors_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_cursors
    ADD CONSTRAINT cognition_maintenance_cursors_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: cognition_maintenance_cursors cognition_maintenance_cursors_processed_through_experience_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_cursors
    ADD CONSTRAINT cognition_maintenance_cursors_processed_through_experience_fkey FOREIGN KEY (processed_through_experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: cognition_maintenance_cursors cognition_maintenance_cursors_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognition_maintenance_cursors
    ADD CONSTRAINT cognition_maintenance_cursors_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: cognitive_attempts cognitive_attempts_branch_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_branch_fkey FOREIGN KEY (cognitive_branch_id) REFERENCES armi.cognitive_branches(cognitive_branch_id);

--
-- Name: cognitive_attempts cognitive_attempts_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_attempts cognitive_attempts_late_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_late_response_artifact_id_fkey FOREIGN KEY (late_response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_attempts cognitive_attempts_request_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_attempts cognitive_attempts_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_attempts cognitive_attempts_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: cognitive_branches cognitive_branches_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_branches
    ADD CONSTRAINT cognitive_branches_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_branches cognitive_branches_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_branches
    ADD CONSTRAINT cognitive_branches_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_branches cognitive_branches_selected_attempt_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_branches
    ADD CONSTRAINT cognitive_branches_selected_attempt_fkey FOREIGN KEY (selected_attempt_id) REFERENCES armi.cognitive_attempts(model_attempt_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_runtime_instance_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_successor_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_successor_opportunity_id_fkey FOREIGN KEY (successor_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: cognitive_candidate_applications cognitive_candidate_applications_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_applications
    ADD CONSTRAINT cognitive_candidate_applications_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: cognitive_candidate_basis_links cognitive_candidate_basis_lin_candidate_validation_id_prop_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_lin_candidate_validation_id_prop_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);

--
-- Name: cognitive_candidate_basis_links cognitive_candidate_basis_links_context_item_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_basis_links
    ADD CONSTRAINT cognitive_candidate_basis_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validatio_validated_by_runtime_instanc_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validatio_validated_by_runtime_instanc_fkey FOREIGN KEY (validated_by_runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

--
-- Name: cognitive_candidate_validation_items cognitive_candidate_validation_ite_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validation_items
    ADD CONSTRAINT cognitive_candidate_validation_ite_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_bundle_activation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_change_set_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_change_set_artifact_id_fkey FOREIGN KEY (change_set_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_model_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_model_attempt_id_fkey FOREIGN KEY (model_attempt_id) REFERENCES armi.cognitive_attempts(model_attempt_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: cognitive_candidate_validations cognitive_candidate_validations_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_candidate_validations
    ADD CONSTRAINT cognitive_candidate_validations_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: cognitive_context_items cognitive_context_items_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_context_items
    ADD CONSTRAINT cognitive_context_items_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_aggregate_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_aggregate_artifact_id_fkey FOREIGN KEY (aggregate_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_appraisal_branch_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_appraisal_branch_id_fkey FOREIGN KEY (appraisal_branch_id) REFERENCES armi.cognitive_branches(cognitive_branch_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_primary_model_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_primary_model_attempt_id_fkey FOREIGN KEY (primary_model_attempt_id) REFERENCES armi.cognitive_attempts(model_attempt_id);

--
-- Name: cognitive_dialogue_aggregates cognitive_dialogue_aggregates_response_branch_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_dialogue_aggregates
    ADD CONSTRAINT cognitive_dialogue_aggregates_response_branch_id_fkey FOREIGN KEY (response_branch_id) REFERENCES armi.cognitive_branches(cognitive_branch_id);

--
-- Name: cognitive_episodes cognitive_episodes_bundle_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_bundle_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

--
-- Name: cognitive_episodes cognitive_episodes_compiled_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_compiled_artifact_fkey FOREIGN KEY (compiled_context_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_episodes cognitive_episodes_context_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_context_artifact_fkey FOREIGN KEY (context_manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: cognitive_episodes cognitive_episodes_context_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_context_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);

--
-- Name: cognitive_episodes cognitive_episodes_opportunity_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: cognitive_episodes cognitive_episodes_opportunity_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_owner_fkey FOREIGN KEY (opportunity_id, subject_id) REFERENCES armi.opportunities(opportunity_id, subject_id);

--
-- Name: cognitive_episodes cognitive_episodes_scene_participant_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_scene_participant_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

--
-- Name: cognitive_episodes cognitive_episodes_subject_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: context_embedding_attempts context_embedding_attempts_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_attempts
    ADD CONSTRAINT context_embedding_attempts_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: context_embedding_attempts context_embedding_attempts_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_attempts
    ADD CONSTRAINT context_embedding_attempts_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: context_embedding_projections context_embedding_projections_context_embedding_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_context_embedding_attempt_id_fkey FOREIGN KEY (context_embedding_attempt_id) REFERENCES armi.context_embedding_attempts(context_embedding_attempt_id);

--
-- Name: context_embedding_projections context_embedding_projections_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: context_embedding_projections context_embedding_projections_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.context_embedding_projections
    ADD CONSTRAINT context_embedding_projections_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: creator_exports creator_exports_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: deletion_items deletion_items_deletion_order_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_items
    ADD CONSTRAINT deletion_items_deletion_order_id_fkey FOREIGN KEY (deletion_order_id) REFERENCES armi.deletion_orders(deletion_order_id);

--
-- Name: deletion_orders deletion_orders_requester_party_id_requester_kind_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_requester_party_id_requester_kind_fkey FOREIGN KEY (requester_party_id, requester_kind) REFERENCES armi.parties(party_id, party_kind);

--
-- Name: deletion_orders deletion_orders_scope_party_id_requester_kind_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.deletion_orders
    ADD CONSTRAINT deletion_orders_scope_party_id_requester_kind_fkey FOREIGN KEY (scope_party_id, requester_kind) REFERENCES armi.parties(party_id, party_kind);

--
-- Name: dialogue_decisions dialogue_decisions_application_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_application_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

--
-- Name: dialogue_decisions dialogue_decisions_candidate_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_candidate_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);

--
-- Name: dialogue_decisions dialogue_decisions_commit_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: dialogue_decisions dialogue_decisions_effect_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_effect_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: dialogue_decisions dialogue_decisions_episode_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_episode_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: dialogue_decisions dialogue_decisions_intent_operation_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_intent_operation_fkey FOREIGN KEY (action_intent_id, operation_ref) REFERENCES armi.action_intents(action_intent_id, operation_ref);

--
-- Name: dialogue_decisions dialogue_decisions_intent_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_intent_owner_fkey FOREIGN KEY (action_intent_id, subject_id, scene_id, context_party_id) REFERENCES armi.action_intents(action_intent_id, subject_id, scene_id, context_party_id);

--
-- Name: dialogue_decisions dialogue_decisions_opportunity_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: dialogue_decisions dialogue_decisions_scene_participant_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_scene_participant_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

--
-- Name: dialogue_decisions dialogue_decisions_subject_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: durable_work durable_work_subject_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.durable_work
    ADD CONSTRAINT durable_work_subject_fk FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id) ON DELETE RESTRICT;

--
-- Name: effect_attempts effect_attempts_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_attempts
    ADD CONSTRAINT effect_attempts_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: effect_observations effect_observations_attempt_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_attempt_owner_fkey FOREIGN KEY (effect_attempt_id, effect_id) REFERENCES armi.effect_attempts(effect_attempt_id, effect_id);

--
-- Name: effect_observations effect_observations_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: effect_outbox_items effect_outbox_items_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_outbox_items
    ADD CONSTRAINT effect_outbox_items_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: effects effects_action_intent_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_action_intent_owner_fkey FOREIGN KEY (action_intent_id, subject_id, scene_id, context_party_id) REFERENCES armi.action_intents(action_intent_id, subject_id, scene_id, context_party_id);

--
-- Name: effects effects_current_attempt_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_current_attempt_fkey FOREIGN KEY (current_attempt_id, effect_id) REFERENCES armi.effect_attempts(effect_attempt_id, effect_id);

--
-- Name: effects effects_current_observation_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_current_observation_fkey FOREIGN KEY (current_observation_id, effect_id, current_attempt_id) REFERENCES armi.effect_observations(effect_observation_id, effect_id, effect_attempt_id);

--
-- Name: effects effects_destination_binding_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_destination_binding_fkey FOREIGN KEY (destination_binding_id) REFERENCES armi.external_channel_bindings(external_binding_id);

--
-- Name: effects effects_destination_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_destination_party_fkey FOREIGN KEY (destination_party_id) REFERENCES armi.parties(party_id);

--
-- Name: effects effects_payload_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_payload_artifact_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: effects effects_policy_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_policy_owner_fkey FOREIGN KEY (policy_decision_id, action_intent_revision_id) REFERENCES armi.policy_decisions(policy_decision_id, action_intent_revision_id);

--
-- Name: effects effects_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_revision_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);

--
-- Name: effects effects_revision_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_revision_owner_fkey FOREIGN KEY (action_intent_revision_id, action_intent_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id, action_intent_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_execution_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_execution_work_id_fkey FOREIGN KEY (execution_work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_result_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_result_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_result_opportunity_id_fkey FOREIGN KEY (result_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_source_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_source_opportunity_id_fkey FOREIGN KEY (source_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: exact_life_query_intents exact_life_query_intents_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.exact_life_query_intents
    ADD CONSTRAINT exact_life_query_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: experience_evidence_links experience_evidence_links_context_item_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_context_item_id_fkey FOREIGN KEY (context_item_id) REFERENCES armi.cognitive_context_items(context_item_id);

--
-- Name: experience_evidence_links experience_evidence_links_evidence_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

--
-- Name: experience_evidence_links experience_evidence_links_experience_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.experience_evidence_links
    ADD CONSTRAINT experience_evidence_links_experience_id_fkey FOREIGN KEY (experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: external_channel_bindings external_channel_bindings_party_kind_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_party_kind_fkey FOREIGN KEY (party_id, party_kind) REFERENCES armi.parties(party_id, party_kind);

--
-- Name: external_channel_bindings external_channel_bindings_scene_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_atte_external_message_part_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_atte_external_message_part_id_fkey FOREIGN KEY (external_message_part_id) REFERENCES armi.external_message_parts(external_message_part_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_attempts_request_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_attempts_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_attempts_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_attempts_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: external_content_recognition_attempts external_content_recognition_attempts_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_content_recognition_attempts
    ADD CONSTRAINT external_content_recognition_attempts_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: external_evidence external_evidence_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_artifact_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: external_evidence external_evidence_codex_source_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_source_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);

--
-- Name: external_evidence external_evidence_codex_verification_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_verification_fkey FOREIGN KEY (codex_verification_id) REFERENCES armi.codex_verification_results(codex_verification_id);

--
-- Name: external_evidence external_evidence_interaction_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_interaction_owner_fkey FOREIGN KEY (interaction_id, subject_id, scene_id, context_party_id) REFERENCES armi.party_input_interactions(interaction_id, subject_id, scene_id, source_party_id);

--
-- Name: external_evidence external_evidence_observation_attempt_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_observation_attempt_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);

--
-- Name: external_evidence external_evidence_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);

--
-- Name: external_evidence external_evidence_scene_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: external_evidence external_evidence_subject_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: external_evidence external_evidence_visual_observation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_visual_observation_id_fkey FOREIGN KEY (visual_observation_id) REFERENCES armi.live_vision_observations(observation_id);

--
-- Name: external_evidence external_evidence_web_request_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_web_request_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);

--
-- Name: external_message_parts external_message_parts_interaction_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_message_parts
    ADD CONSTRAINT external_message_parts_interaction_id_fkey FOREIGN KEY (interaction_id) REFERENCES armi.party_input_interactions(interaction_id);

--
-- Name: external_message_parts external_message_parts_interpretation_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_message_parts
    ADD CONSTRAINT external_message_parts_interpretation_artifact_id_fkey FOREIGN KEY (interpretation_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: external_message_parts external_message_parts_raw_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_message_parts
    ADD CONSTRAINT external_message_parts_raw_artifact_id_fkey FOREIGN KEY (raw_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: interaction_scenes interaction_scenes_primary_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_primary_party_id_fkey FOREIGN KEY (primary_party_id) REFERENCES armi.parties(party_id);

--
-- Name: interaction_scenes interaction_scenes_primary_party_kind_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_primary_party_kind_fk FOREIGN KEY (primary_party_id, primary_party_kind) REFERENCES armi.parties(party_id, party_kind);

--
-- Name: interaction_scenes interaction_scenes_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: life_generations life_generations_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_generations
    ADD CONSTRAINT life_generations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: life_material_revisions life_material_revisions_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: life_material_revisions life_material_revisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: life_material_revisions life_material_revisions_life_material_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_life_material_id_fkey FOREIGN KEY (life_material_id) REFERENCES armi.life_materials(life_material_id);

--
-- Name: life_material_revisions life_material_revisions_previous_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_previous_fk FOREIGN KEY (life_material_id, previous_revision_id) REFERENCES armi.life_material_revisions(life_material_id, life_material_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: life_material_revisions life_material_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: life_materials life_materials_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_current_revision_fk FOREIGN KEY (life_material_id, current_revision_id) REFERENCES armi.life_material_revisions(life_material_id, life_material_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: life_materials life_materials_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: life_materials life_materials_owner_party_id_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_owner_party_id_subject_id_fkey FOREIGN KEY (owner_party_id, subject_id) REFERENCES armi.parties(party_id, represented_subject_id);

--
-- Name: life_materials life_materials_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: live_vision_observations live_vision_observation_evidence_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observations
    ADD CONSTRAINT live_vision_observation_evidence_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

--
-- Name: live_vision_observation_frames live_vision_observation_frames_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observation_frames
    ADD CONSTRAINT live_vision_observation_frames_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: live_vision_observation_frames live_vision_observation_frames_observation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observation_frames
    ADD CONSTRAINT live_vision_observation_frames_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES armi.live_vision_observations(observation_id);

--
-- Name: live_vision_observations live_vision_observations_session_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observations
    ADD CONSTRAINT live_vision_observations_session_id_fkey FOREIGN KEY (session_id) REFERENCES armi.live_vision_sessions(session_id);

--
-- Name: live_vision_observations live_vision_observations_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_observations
    ADD CONSTRAINT live_vision_observations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: live_vision_sessions live_vision_sessions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_vision_sessions
    ADD CONSTRAINT live_vision_sessions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: live_voice_playback_attempts live_voice_playback_attempts_turn_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_playback_attempts
    ADD CONSTRAINT live_voice_playback_attempts_turn_id_fkey FOREIGN KEY (turn_id) REFERENCES armi.live_voice_turns(turn_id);

--
-- Name: live_voice_provider_attempts live_voice_provider_attempts_turn_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_provider_attempts
    ADD CONSTRAINT live_voice_provider_attempts_turn_id_fkey FOREIGN KEY (turn_id) REFERENCES armi.live_voice_turns(turn_id);

--
-- Name: live_voice_sessions live_voice_sessions_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_sessions
    ADD CONSTRAINT live_voice_sessions_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: live_voice_sessions live_voice_sessions_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_sessions
    ADD CONSTRAINT live_voice_sessions_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: live_voice_sessions live_voice_sessions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_sessions
    ADD CONSTRAINT live_voice_sessions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: live_voice_text_fragments live_voice_text_fragments_turn_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_text_fragments
    ADD CONSTRAINT live_voice_text_fragments_turn_id_fkey FOREIGN KEY (turn_id) REFERENCES armi.live_voice_turns(turn_id);

--
-- Name: live_voice_turns live_voice_turns_interaction_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_turns
    ADD CONSTRAINT live_voice_turns_interaction_id_fkey FOREIGN KEY (interaction_id) REFERENCES armi.party_input_interactions(interaction_id);

--
-- Name: live_voice_turns live_voice_turns_session_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.live_voice_turns
    ADD CONSTRAINT live_voice_turns_session_id_fkey FOREIGN KEY (session_id) REFERENCES armi.live_voice_sessions(session_id);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_artifact_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_artifact_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_effect_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_effect_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_party_fkey FOREIGN KEY (destination_party_id) REFERENCES armi.parties(party_id);

--
-- Name: local_inbox_deliveries local_inbox_deliveries_scene_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_maintenance_revision_id_maintena_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_revision_id_maintena_fkey FOREIGN KEY (maintenance_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_maintenance_session_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_maintenance_session_id_fkey FOREIGN KEY (maintenance_session_id) REFERENCES armi.maintenance_sessions(maintenance_session_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_memory_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES armi.subjective_memories(memory_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: maintenance_phase_results maintenance_phase_results_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_phase_results
    ADD CONSTRAINT maintenance_phase_results_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: maintenance_session_revisions maintenance_session_revisions_maintenance_session_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_maintenance_session_id_fkey FOREIGN KEY (maintenance_session_id) REFERENCES armi.maintenance_sessions(maintenance_session_id);

--
-- Name: maintenance_session_revisions maintenance_session_revisions_previous_revision_id_mainten_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_session_revisions
    ADD CONSTRAINT maintenance_session_revisions_previous_revision_id_mainten_fkey FOREIGN KEY (previous_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id);

--
-- Name: maintenance_sessions maintenance_sessions_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_current_revision_fk FOREIGN KEY (current_revision_id, maintenance_session_id) REFERENCES armi.maintenance_session_revisions(maintenance_revision_id, maintenance_session_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: maintenance_sessions maintenance_sessions_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: maintenance_sessions maintenance_sessions_origin_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_origin_opportunity_id_fkey FOREIGN KEY (origin_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: maintenance_sessions maintenance_sessions_sleep_decision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_sleep_decision_id_fkey FOREIGN KEY (sleep_decision_id) REFERENCES armi.sleep_decisions(sleep_decision_id);

--
-- Name: maintenance_sessions maintenance_sessions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.maintenance_sessions
    ADD CONSTRAINT maintenance_sessions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: memory_relations memory_relations_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: memory_relations memory_relations_from_memory_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_from_memory_id_fkey FOREIGN KEY (from_memory_id) REFERENCES armi.subjective_memories(memory_id);

--
-- Name: memory_relations memory_relations_from_memory_id_from_memory_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_from_memory_id_from_memory_revision_id_fkey FOREIGN KEY (from_memory_id, from_memory_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id);

--
-- Name: memory_relations memory_relations_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: memory_relations memory_relations_to_memory_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.memory_relations
    ADD CONSTRAINT memory_relations_to_memory_id_fkey FOREIGN KEY (to_memory_id) REFERENCES armi.subjective_memories(memory_id);

--
-- Name: mood_affective_events mood_affective_events_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_affective_events
    ADD CONSTRAINT mood_affective_events_revision_fkey FOREIGN KEY (mood_revision_id, subject_id) REFERENCES armi.mood_revisions(mood_revision_id, subject_id);

--
-- Name: mood_affective_events mood_affective_events_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_affective_events
    ADD CONSTRAINT mood_affective_events_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_previous_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_previous_fkey FOREIGN KEY (previous_appraisal_event_id, subject_id) REFERENCES armi.mood_appraisal_events(mood_appraisal_event_id, subject_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_revision_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_revision_fkey FOREIGN KEY (mood_revision_id, subject_id) REFERENCES armi.mood_revisions(mood_revision_id, subject_id);

--
-- Name: mood_appraisal_events mood_appraisal_events_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_appraisal_events
    ADD CONSTRAINT mood_appraisal_events_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: mood_heads mood_heads_current_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_heads
    ADD CONSTRAINT mood_heads_current_owner_fkey FOREIGN KEY (current_revision_id, subject_id) REFERENCES armi.mood_revisions(mood_revision_id, subject_id);

--
-- Name: mood_heads mood_heads_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_heads
    ADD CONSTRAINT mood_heads_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: mood_revisions mood_revisions_previous_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_previous_owner_fkey FOREIGN KEY (previous_revision_id, subject_id) REFERENCES armi.mood_revisions(mood_revision_id, subject_id);

--
-- Name: mood_revisions mood_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: mood_revisions mood_revisions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.mood_revisions
    ADD CONSTRAINT mood_revisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: observation_attempts observation_attempts_result_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: observation_attempts observation_attempts_web_observation_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_web_observation_request_id_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);

--
-- Name: observation_attempts observation_attempts_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_attempts
    ADD CONSTRAINT observation_attempts_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: observation_tool_calls observation_tool_calls_observation_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);

--
-- Name: opportunities opportunities_activity_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_activity_owner_fkey FOREIGN KEY (activity_id, subject_id) REFERENCES armi.activities(activity_id, subject_id);

--
-- Name: opportunities opportunities_context_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_context_party_fkey FOREIGN KEY (context_party_id) REFERENCES armi.parties(party_id);

--
-- Name: opportunities opportunities_evidence_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_evidence_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

--
-- Name: opportunities opportunities_predecessor_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_predecessor_fkey FOREIGN KEY (predecessor_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: opportunities opportunities_root_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_root_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: opportunities opportunities_scene_participant_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_scene_participant_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

--
-- Name: opportunities opportunities_subject_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: parties parties_represented_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_represented_subject_id_fkey FOREIGN KEY (represented_subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: party_input_interactions party_input_interactions_external_binding_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_external_binding_fkey FOREIGN KEY (external_binding_id) REFERENCES armi.external_channel_bindings(external_binding_id);

--
-- Name: party_input_interactions party_input_interactions_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_party_fkey FOREIGN KEY (source_party_id) REFERENCES armi.parties(party_id);

--
-- Name: party_input_interactions party_input_interactions_scene_participant_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_scene_participant_fkey FOREIGN KEY (scene_id, subject_id, source_party_id) REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

--
-- Name: permission_grants permission_grants_capability_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_id_fkey FOREIGN KEY (capability_id) REFERENCES armi.capabilities(capability_id);

--
-- Name: permission_grants permission_grants_capability_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_capability_request_id_fkey FOREIGN KEY (capability_request_id) REFERENCES armi.capability_requests(capability_request_id);

--
-- Name: permission_grants permission_grants_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: permission_grants permission_grants_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: permission_grants permission_grants_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.permission_grants
    ADD CONSTRAINT permission_grants_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: policy_decisions policy_decisions_action_intent_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_action_intent_revision_id_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);

--
-- Name: policy_decisions policy_decisions_matched_grant_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_matched_grant_id_fkey FOREIGN KEY (matched_grant_id) REFERENCES armi.permission_grants(grant_id);

--
-- Name: policy_decisions policy_decisions_supersedes_policy_decision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_supersedes_policy_decision_id_fkey FOREIGN KEY (supersedes_policy_decision_id) REFERENCES armi.policy_decisions(policy_decision_id);

--
-- Name: prompt_documents prompt_documents_current_revision_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_current_revision_owner_fkey FOREIGN KEY (current_revision_id, prompt_document_id) REFERENCES armi.prompt_revisions(prompt_revision_id, prompt_document_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: prompt_documents prompt_documents_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: prompt_revisions prompt_revisions_author_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_author_party_id_fkey FOREIGN KEY (author_party_id) REFERENCES armi.parties(party_id);

--
-- Name: prompt_revisions prompt_revisions_content_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_content_artifact_id_fkey FOREIGN KEY (content_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: prompt_revisions prompt_revisions_previous_revision_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_previous_revision_owner_fkey FOREIGN KEY (previous_revision_id, prompt_document_id) REFERENCES armi.prompt_revisions(prompt_revision_id, prompt_document_id);

--
-- Name: prompt_revisions prompt_revisions_prompt_document_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_prompt_document_id_fkey FOREIGN KEY (prompt_document_id) REFERENCES armi.prompt_documents(prompt_document_id);

--
-- Name: prompt_revisions prompt_revisions_subject_commit_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_subject_commit_fk FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: relationship_experience_links relationship_experience_links_experience_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_experience_id_fkey FOREIGN KEY (experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: relationship_experience_links relationship_experience_links_relationship_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_experience_links
    ADD CONSTRAINT relationship_experience_links_relationship_revision_id_fkey FOREIGN KEY (relationship_revision_id) REFERENCES armi.relationship_revisions(relationship_revision_id);

--
-- Name: relationship_revisions relationship_revisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: relationship_revisions relationship_revisions_previous_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_previous_fk FOREIGN KEY (relationship_id, previous_revision_id) REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: relationship_revisions relationship_revisions_relationship_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_relationship_id_fkey FOREIGN KEY (relationship_id) REFERENCES armi.relationships(relationship_id);

--
-- Name: relationship_revisions relationship_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: relationships relationships_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_current_revision_fk FOREIGN KEY (relationship_id, current_revision_id) REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: relationships relationships_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: relationships relationships_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);

--
-- Name: relationships relationships_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: relationships relationships_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_subject_party_id_fkey FOREIGN KEY (subject_party_id) REFERENCES armi.parties(party_id);

--
-- Name: relationships relationships_tombstone_order_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_tombstone_order_id_fkey FOREIGN KEY (tombstone_order_id) REFERENCES armi.deletion_orders(deletion_order_id);

--
-- Name: runtime_bundle_activations runtime_bundle_activations_activated_by_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_activated_by_party_id_fkey FOREIGN KEY (activated_by_party_id) REFERENCES armi.parties(party_id);

--
-- Name: runtime_bundle_activations runtime_bundle_activations_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: runtime_instances runtime_instances_bundle_activation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

--
-- Name: runtime_instances runtime_instances_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: runtime_instances runtime_instances_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_instances
    ADD CONSTRAINT runtime_instances_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: runtime_recovery_metrics runtime_recovery_metrics_run_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_metrics
    ADD CONSTRAINT runtime_recovery_metrics_run_fkey FOREIGN KEY (recovery_run_id) REFERENCES armi.runtime_recovery_runs(recovery_run_id) ON DELETE CASCADE;

--
-- Name: runtime_recovery_runs runtime_recovery_runs_bundle_activation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

--
-- Name: runtime_recovery_runs runtime_recovery_runs_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: runtime_recovery_runs runtime_recovery_runs_runtime_instance_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

--
-- Name: runtime_recovery_runs runtime_recovery_runs_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_recovery_runs
    ADD CONSTRAINT runtime_recovery_runs_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: scene_participants scene_participants_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_participants
    ADD CONSTRAINT scene_participants_party_fkey FOREIGN KEY (party_id) REFERENCES armi.parties(party_id);

--
-- Name: scene_participants scene_participants_scene_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_participants
    ADD CONSTRAINT scene_participants_scene_fkey FOREIGN KEY (scene_id, subject_id) REFERENCES armi.interaction_scenes(scene_id, subject_id);

--
-- Name: scene_timeline_items scene_timeline_items_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.scene_timeline_items
    ADD CONSTRAINT scene_timeline_items_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: sleep_decisions sleep_decisions_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);

--
-- Name: sleep_decisions sleep_decisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: sleep_decisions sleep_decisions_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: sleep_decisions sleep_decisions_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: sleep_decisions sleep_decisions_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: sleep_decisions sleep_decisions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.sleep_decisions
    ADD CONSTRAINT sleep_decisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: subject_commits subject_commits_bundle_activation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);

--
-- Name: subject_commits subject_commits_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: subject_commits subject_commits_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);

--
-- Name: subject_commits subject_commits_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: subject_commits subject_commits_runtime_instance_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

--
-- Name: subject_commits subject_commits_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_commits
    ADD CONSTRAINT subject_commits_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: subject_component_heads subject_component_heads_current_revision_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_current_revision_owner_fkey FOREIGN KEY (current_revision_id, subject_id, component_kind) REFERENCES armi.subject_component_revisions(component_revision_id, subject_id, component_kind);

--
-- Name: subject_component_heads subject_component_heads_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: subject_component_revisions subject_component_revisions_commit_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_commit_fk FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: subject_component_revisions subject_component_revisions_previous_revision_owner_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_previous_revision_owner_fkey FOREIGN KEY (previous_revision_id, subject_id, component_kind) REFERENCES armi.subject_component_revisions(component_revision_id, subject_id, component_kind);

--
-- Name: subject_component_revisions subject_component_revisions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: subjective_memories subjective_memories_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_current_revision_fk FOREIGN KEY (memory_id, current_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: subjective_memories subjective_memories_life_generation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_life_generation_id_fkey FOREIGN KEY (life_generation_id) REFERENCES armi.life_generations(life_generation_id);

--
-- Name: subjective_memories subjective_memories_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memories
    ADD CONSTRAINT subjective_memories_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_memory_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES armi.subjective_memories(memory_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_previous_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_previous_fk FOREIGN KEY (memory_id, previous_revision_id) REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: subjective_memory_revisions subjective_memory_revisions_source_experience_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_source_experience_id_fkey FOREIGN KEY (source_experience_id) REFERENCES armi.accepted_experiences(experience_id);

--
-- Name: subjective_memory_revisions subjective_memory_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: subjects subjects_current_activation_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_current_activation_fk FOREIGN KEY (current_bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: subjects subjects_current_generation_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subjects
    ADD CONSTRAINT subjects_current_generation_fk FOREIGN KEY (current_generation_id) REFERENCES armi.life_generations(life_generation_id) DEFERRABLE INITIALLY DEFERRED;

--
-- Name: visual_recognition_attempts visual_recognition_attempts_observation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.visual_recognition_attempts
    ADD CONSTRAINT visual_recognition_attempts_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES armi.live_vision_observations(observation_id);

--
-- Name: visual_recognition_attempts visual_recognition_attempts_request_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.visual_recognition_attempts
    ADD CONSTRAINT visual_recognition_attempts_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: visual_recognition_attempts visual_recognition_attempts_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.visual_recognition_attempts
    ADD CONSTRAINT visual_recognition_attempts_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: web_evidence_sources web_evidence_sources_evidence_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES armi.external_evidence(evidence_id);

--
-- Name: web_evidence_sources web_evidence_sources_observation_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_observation_attempt_id_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);

--
-- Name: web_evidence_sources web_evidence_sources_source_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_evidence_sources
    ADD CONSTRAINT web_evidence_sources_source_artifact_id_fkey FOREIGN KEY (source_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: web_observation_requests web_observation_requests_request_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_request_artifact_id_fkey FOREIGN KEY (request_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: web_observation_requests web_observation_requests_result_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_result_artifact_id_fkey FOREIGN KEY (result_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: web_observation_requests web_observation_requests_runtime_instance_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_runtime_instance_id_fkey FOREIGN KEY (runtime_instance_id) REFERENCES armi.runtime_instances(runtime_instance_id);

--
-- Name: web_observation_requests web_observation_requests_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: web_observation_requests web_observation_requests_web_research_intent_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_web_research_intent_id_fkey FOREIGN KEY (web_research_intent_id) REFERENCES armi.web_research_intents(web_research_intent_id);

--
-- Name: web_observation_requests web_observation_requests_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_observation_requests
    ADD CONSTRAINT web_observation_requests_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: web_research_intents web_research_intents_admission_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_admission_work_id_fkey FOREIGN KEY (admission_work_id) REFERENCES armi.durable_work(work_id);

--
-- Name: web_research_intents web_research_intents_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);

--
-- Name: web_research_intents web_research_intents_query_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_query_artifact_id_fkey FOREIGN KEY (query_artifact_id) REFERENCES armi.artifacts(artifact_id);

--
-- Name: web_research_intents web_research_intents_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);

--
-- Name: web_research_intents web_research_intents_source_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_source_opportunity_id_fkey FOREIGN KEY (source_opportunity_id) REFERENCES armi.opportunities(opportunity_id);

--
-- Name: web_research_intents web_research_intents_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);

--
-- Name: web_research_intents web_research_intents_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);

--
-- Name: web_research_intents web_research_intents_web_observation_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.web_research_intents
    ADD CONSTRAINT web_research_intents_web_observation_request_id_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);
