--
-- Name: accepted_experiences; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.accepted_experiences (
    experience_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    experience_kind text NOT NULL,
    fact_class text NOT NULL,
    first_person_gist text NOT NULL,
    scene_id uuid NOT NULL,
    occurred_at timestamp(6) with time zone NOT NULL,
    learned_at timestamp(6) with time zone NOT NULL,
    accepted_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    source_perspective text NOT NULL,
    uncertainty text,
    privacy_scope text NOT NULL,
    CONSTRAINT accepted_experiences_experience_id_check CHECK ((uuid_extract_version(experience_id) = 7)),
    CONSTRAINT accepted_experiences_experience_kind_check CHECK ((experience_kind = ANY (ARRAY['creator_input'::text, 'web_observation'::text, 'codex_observation'::text, 'other_human_input'::text]))),
    CONSTRAINT accepted_experiences_fact_class_check CHECK ((fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT accepted_experiences_first_person_gist_check CHECK (((length(first_person_gist) >= 1) AND (length(first_person_gist) <= 1024))),
    CONSTRAINT accepted_experiences_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT accepted_experiences_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT accepted_experiences_source_pair_check CHECK ((((experience_kind = 'creator_input'::text) AND (source_perspective = 'creator_claim'::text)) OR ((experience_kind = 'web_observation'::text) AND (source_perspective = 'web_claim'::text)) OR ((experience_kind = 'codex_observation'::text) AND (source_perspective = 'codex_observation'::text)) OR ((experience_kind = 'other_human_input'::text) AND (source_perspective = 'other_human_claim'::text)))),
    CONSTRAINT accepted_experiences_source_perspective_check CHECK ((source_perspective = ANY (ARRAY['creator_claim'::text, 'web_claim'::text, 'codex_observation'::text, 'other_human_claim'::text]))),
    CONSTRAINT accepted_experiences_uncertainty_check CHECK (((uncertainty IS NULL) OR ((length(uncertainty) >= 1) AND (length(uncertainty) <= 512))))
);

--
-- Name: cognitive_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_attempts (
    model_attempt_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    work_id uuid NOT NULL,
    work_attempt_id uuid NOT NULL,
    attempt_no smallint NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    version_policy text NOT NULL,
    profile text NOT NULL,
    request_schema_version text NOT NULL,
    candidate_schema_version text NOT NULL,
    pricing_snapshot_id text NOT NULL,
    credential_identity text NOT NULL,
    request_artifact_id uuid NOT NULL,
    dispatch_status text NOT NULL,
    provider_request_id text,
    provider_model_id text,
    response_artifact_id uuid,
    input_tokens integer,
    output_tokens integer,
    cached_input_tokens integer,
    estimated_cost_microyuan bigint,
    result_status text,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT cognitive_attempts_attempt_no_check CHECK ((attempt_no >= 1)),
    CONSTRAINT cognitive_attempts_cached_input_tokens_check CHECK (((cached_input_tokens IS NULL) OR (cached_input_tokens >= 0))),
    CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK ((candidate_schema_version = ANY (ARRAY['armi.cognition-candidate.v1'::text, 'armi.cognition-candidate.v2'::text, 'armi.cognition-candidate.v3'::text, 'armi.cognition-candidate.v4'::text, 'armi.cognition-candidate.v5'::text, 'armi.cognition-candidate.v6'::text, 'armi.cognition-candidate.v7'::text, 'armi.creator-dialogue-candidate.v5'::text, 'armi.creator-dialogue-candidate.v6'::text, 'armi.creator-dialogue-candidate.v7'::text, 'armi.creator-dialogue-candidate.v8'::text, 'armi.creator-dialogue-candidate.v9'::text, 'armi.creator-dialogue-candidate.v10'::text, 'armi.creator-dialogue-candidate.v11'::text, 'armi.creator-dialogue-candidate.v12'::text, 'armi.creator-dialogue-candidate.v13'::text, 'armi.creator-dialogue-candidate.v14'::text, 'armi.creator-dialogue-candidate.v15'::text, 'armi.creator-dialogue-candidate.v16'::text, 'armi.creator-dialogue-candidate.v17'::text, 'armi.creator-dialogue-candidate.v18'::text, 'armi.autonomous-activity-candidate.v1'::text, 'armi.activity-attention-candidate.v1'::text, 'armi.activity-attention-candidate.v2'::text, 'armi.activity-internal-work-candidate.v1'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v2'::text]))),
    CONSTRAINT cognitive_attempts_check CHECK ((((dispatch_status = 'prepared'::text) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (response_artifact_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'dispatched'::text) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (response_artifact_id IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'settled'::text) AND (settled_at IS NOT NULL) AND (result_status IS NOT NULL) AND (((result_status = 'succeeded'::text) AND (dispatched_at IS NOT NULL) AND (provider_request_id IS NOT NULL) AND (provider_model_id IS NOT NULL) AND (response_artifact_id IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (cached_input_tokens IS NOT NULL) AND (estimated_cost_microyuan IS NOT NULL) AND (error_code IS NULL)) OR ((result_status <> 'succeeded'::text) AND (response_artifact_id IS NULL) AND (error_code IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = 'cancelled'::text) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL) AND (estimated_cost_microyuan IS NULL)))))))),
    CONSTRAINT cognitive_attempts_credential_identity_check CHECK ((credential_identity = 'armi.model.ark-api-key.v1'::text)),
    CONSTRAINT cognitive_attempts_dispatch_status_check CHECK ((dispatch_status = ANY (ARRAY['prepared'::text, 'dispatched'::text, 'settled'::text]))),
    CONSTRAINT cognitive_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^MODEL-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_attempts_estimated_cost_microyuan_check CHECK (((estimated_cost_microyuan IS NULL) OR (estimated_cost_microyuan >= 0))),
    CONSTRAINT cognitive_attempts_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens >= 0))),
    CONSTRAINT cognitive_attempts_model_attempt_id_check CHECK ((uuid_extract_version(model_attempt_id) = 7)),
    CONSTRAINT cognitive_attempts_model_id_check CHECK ((model_id = 'doubao-seed-evolving'::text)),
    CONSTRAINT cognitive_attempts_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens >= 0))),
    CONSTRAINT cognitive_attempts_pricing_snapshot_id_check CHECK ((pricing_snapshot_id = 'volcengine-ark-cn-2026-07-31-evolving'::text)),
    CONSTRAINT cognitive_attempts_profile_check CHECK ((profile = ANY (ARRAY['creator_input_cognition'::text, 'creator_dialogue'::text, 'creator_outreach'::text, 'other_human_dialogue'::text, 'autonomous_activity'::text, 'activity_attention'::text, 'activity_internal_work'::text, 'sleep_decision'::text, 'memory_maintenance'::text, 'subject_self_check'::text]))),
    CONSTRAINT cognitive_attempts_provider_check CHECK ((provider = 'volcengine_ark'::text)),
    CONSTRAINT cognitive_attempts_provider_model_id_check CHECK (((provider_model_id IS NULL) OR (provider_model_id ~ '^doubao-seed-[a-z0-9-]{1,96}$'::text))),
    CONSTRAINT cognitive_attempts_request_schema_version_check CHECK ((request_schema_version = 'armi.model-request.v1'::text)),
    CONSTRAINT cognitive_attempts_result_status_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'rejected'::text, 'timed_out'::text, 'provider_failed'::text, 'cancelled'::text, 'outcome_unknown'::text])))),
    CONSTRAINT cognitive_attempts_version_policy_check CHECK ((version_policy = 'provider_evolving_alias'::text)),
    CONSTRAINT cognitive_attempts_work_attempt_id_check CHECK ((uuid_extract_version(work_attempt_id) = 7))
);

--
-- Name: cognitive_candidate_applications; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_candidate_applications (
    candidate_application_id uuid CONSTRAINT cognitive_candidate_applicati_candidate_application_id_not_null NOT NULL,
    candidate_validation_id uuid CONSTRAINT cognitive_candidate_applicatio_candidate_validation_id_not_null NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    work_id uuid NOT NULL,
    resolution text NOT NULL,
    subject_commit_id uuid,
    successor_opportunity_id uuid,
    base_subject_version bigint NOT NULL,
    observed_subject_version bigint CONSTRAINT cognitive_candidate_applicati_observed_subject_version_not_null NOT NULL,
    runtime_instance_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    resolved_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT cognitive_candidate_applications_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_applications_candidate_application_id_check CHECK ((uuid_extract_version(candidate_application_id) = 7)),
    CONSTRAINT cognitive_candidate_applications_check CHECK (((resolution = 'applied'::text) = (subject_commit_id IS NOT NULL))),
    CONSTRAINT cognitive_candidate_applications_check1 CHECK (((successor_opportunity_id IS NULL) OR (resolution = 'stale'::text))),
    CONSTRAINT cognitive_candidate_applications_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT cognitive_candidate_applications_observed_subject_version_check CHECK ((observed_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_applications_resolution_check CHECK ((resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'deferred'::text, 'declined'::text, 'no_action'::text, 'need_information'::text, 'stale'::text])))
);

--
-- Name: cognitive_candidate_basis_links; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_candidate_basis_links (
    candidate_validation_id uuid CONSTRAINT cognitive_candidate_basis_link_candidate_validation_id_not_null NOT NULL,
    proposal_ref text NOT NULL,
    context_item_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    CONSTRAINT cognitive_candidate_basis_links_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 8)))
);

--
-- Name: cognitive_candidate_validation_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_candidate_validation_items (
    candidate_validation_id uuid CONSTRAINT cognitive_candidate_validatio_candidate_validation_id_not_null1 NOT NULL,
    proposal_ref text NOT NULL,
    atomic_group_ref text NOT NULL,
    owner_kind text NOT NULL,
    fact_class text NOT NULL,
    validation_status text NOT NULL,
    reason_code text,
    ordinal smallint NOT NULL,
    CONSTRAINT cognitive_candidate_validation_items_atomic_group_ref_check CHECK ((atomic_group_ref ~ '^group:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT cognitive_candidate_validation_items_check CHECK ((((validation_status = 'accepted'::text) AND (reason_code IS NULL)) OR ((validation_status = 'rejected'::text) AND (reason_code IS NOT NULL)))),
    CONSTRAINT cognitive_candidate_validation_items_fact_class_check CHECK ((fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT cognitive_candidate_validation_items_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 16))),
    CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['experience'::text, 'self'::text, 'mind'::text, 'life_mode'::text, 'memory'::text, 'relationship'::text, 'activity'::text, 'capability'::text, 'action'::text, 'web_research'::text, 'codex_delegation'::text, 'sleep'::text, 'material'::text, 'prompt'::text, 'exact_life_query'::text, 'maintenance'::text]))),
    CONSTRAINT cognitive_candidate_validation_items_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT cognitive_candidate_validation_items_reason_code_check CHECK (((reason_code IS NULL) OR (reason_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_candidate_validation_items_validation_status_check CHECK ((validation_status = ANY (ARRAY['accepted'::text, 'rejected'::text])))
);

--
-- Name: cognitive_candidate_validations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_candidate_validations (
    candidate_validation_id uuid CONSTRAINT cognitive_candidate_validation_candidate_validation_id_not_null NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    model_attempt_id uuid NOT NULL,
    work_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    bundle_activation_id uuid NOT NULL,
    base_subject_version bigint NOT NULL,
    base_state_epoch bigint NOT NULL,
    context_digest text NOT NULL,
    candidate_contract_version text CONSTRAINT cognitive_candidate_validat_candidate_contract_version_not_null NOT NULL,
    validator_identity text NOT NULL,
    validation_status text NOT NULL,
    final_disposition text,
    change_set_artifact_id uuid,
    accepted_count smallint NOT NULL,
    rejected_count smallint NOT NULL,
    error_code text,
    validated_by_runtime_instance_id uuid CONSTRAINT cognitive_candidate_validat_validated_by_runtime_insta_not_null NOT NULL,
    validation_fence_token bigint NOT NULL,
    validated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK ((candidate_contract_version = ANY (ARRAY['armi.cognition-candidate.v1'::text, 'armi.cognition-candidate.v2'::text, 'armi.cognition-candidate.v3'::text, 'armi.cognition-candidate.v4'::text, 'armi.cognition-candidate.v5'::text, 'armi.cognition-candidate.v6'::text, 'armi.cognition-candidate.v7'::text, 'armi.creator-dialogue-candidate.v5'::text, 'armi.creator-dialogue-candidate.v6'::text, 'armi.creator-dialogue-candidate.v7'::text, 'armi.creator-dialogue-candidate.v8'::text, 'armi.creator-dialogue-candidate.v9'::text, 'armi.creator-dialogue-candidate.v10'::text, 'armi.creator-dialogue-candidate.v11'::text, 'armi.creator-dialogue-candidate.v12'::text, 'armi.creator-dialogue-candidate.v13'::text, 'armi.creator-dialogue-candidate.v14'::text, 'armi.creator-dialogue-candidate.v15'::text, 'armi.creator-dialogue-candidate.v16'::text, 'armi.creator-dialogue-candidate.v17'::text, 'armi.creator-dialogue-candidate.v18'::text, 'armi.autonomous-activity-candidate.v1'::text, 'armi.activity-attention-candidate.v1'::text, 'armi.activity-attention-candidate.v2'::text, 'armi.activity-internal-work-candidate.v1'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v2'::text]))),
    CONSTRAINT cognitive_candidate_validations_accepted_count_check CHECK (((accepted_count >= 0) AND (accepted_count <= 16))),
    CONSTRAINT cognitive_candidate_validations_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT cognitive_candidate_validations_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_validations_candidate_validation_id_check CHECK ((uuid_extract_version(candidate_validation_id) = 7)),
    CONSTRAINT cognitive_candidate_validations_check CHECK ((((validation_status = ANY (ARRAY['accepted'::text, 'partially_accepted'::text])) AND (final_disposition IS NOT NULL) AND (change_set_artifact_id IS NOT NULL) AND (error_code IS NULL)) OR ((validation_status = 'rejected'::text) AND (final_disposition IS NULL) AND (change_set_artifact_id IS NULL) AND (accepted_count = 0) AND (error_code IS NOT NULL)))),
    CONSTRAINT cognitive_candidate_validations_context_digest_check CHECK ((context_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_candidate_validations_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_candidate_validations_final_disposition_check CHECK (((final_disposition IS NULL) OR (final_disposition = ANY (ARRAY['change'::text, 'no_change'::text, 'defer'::text, 'decline'::text, 'no_action'::text, 'need_information'::text])))),
    CONSTRAINT cognitive_candidate_validations_rejected_count_check CHECK (((rejected_count >= 0) AND (rejected_count <= 16))),
    CONSTRAINT cognitive_candidate_validations_validation_fence_token_check CHECK ((validation_fence_token > 0)),
    CONSTRAINT cognitive_candidate_validations_validation_status_check CHECK ((validation_status = ANY (ARRAY['accepted'::text, 'partially_accepted'::text, 'rejected'::text]))),
    CONSTRAINT cognitive_candidate_validations_validator_identity_check CHECK ((validator_identity = 'armi.candidate-validator.deterministic-v1'::text))
);

--
-- Name: cognitive_context_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_context_items (
    context_item_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    section text NOT NULL,
    item_kind text NOT NULL,
    source_kind text NOT NULL,
    source_ref uuid,
    source_version bigint,
    trust_class text NOT NULL,
    privacy_scope text NOT NULL,
    disposition text NOT NULL,
    reason_code text,
    content_bytes integer NOT NULL,
    CONSTRAINT cognitive_context_items_check CHECK ((((source_ref IS NULL) AND (source_version IS NULL)) OR ((source_ref IS NOT NULL) AND (source_version IS NOT NULL)))),
    CONSTRAINT cognitive_context_items_check1 CHECK ((((disposition = ANY (ARRAY['included'::text, 'excluded_policy'::text])) AND (reason_code IS NULL)) OR ((disposition = ANY (ARRAY['excluded_budget'::text, 'unavailable'::text, 'read_failed'::text])) AND (reason_code IS NOT NULL)))),
    CONSTRAINT cognitive_context_items_content_bytes_check CHECK ((content_bytes >= 0)),
    CONSTRAINT cognitive_context_items_context_item_id_check CHECK ((uuid_extract_version(context_item_id) = 7)),
    CONSTRAINT cognitive_context_items_disposition_check CHECK ((disposition = ANY (ARRAY['included'::text, 'excluded_policy'::text, 'excluded_budget'::text, 'unavailable'::text, 'read_failed'::text]))),
    CONSTRAINT cognitive_context_items_item_kind_check CHECK ((item_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT cognitive_context_items_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT cognitive_context_items_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['internal'::text, 'private'::text, 'restricted'::text]))),
    CONSTRAINT cognitive_context_items_reason_code_check CHECK (((reason_code IS NULL) OR (reason_code ~ '^CTX-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_context_items_section_check CHECK ((section = ANY (ARRAY['runtime_truth'::text, 'purpose'::text, 'self'::text, 'mind'::text, 'life_mode'::text, 'scene'::text, 'relationship'::text, 'memory'::text, 'activity'::text, 'material'::text, 'evidence'::text, 'capability'::text, 'prompt'::text]))),
    CONSTRAINT cognitive_context_items_source_kind_check CHECK ((source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT cognitive_context_items_source_ref_check CHECK (((source_ref IS NULL) OR (uuid_extract_version(source_ref) = 7))),
    CONSTRAINT cognitive_context_items_source_version_check CHECK (((source_version IS NULL) OR (source_version >= 0))),
    CONSTRAINT cognitive_context_items_trust_class_check CHECK ((trust_class = ANY (ARRAY['runtime_authority'::text, 'subjective_state'::text, 'external_claim'::text, 'policy'::text])))
);

--
-- Name: cognitive_episodes; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_episodes (
    cognitive_episode_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid,
    context_party_id uuid,
    purpose text NOT NULL,
    status text NOT NULL,
    base_subject_version bigint NOT NULL,
    base_state_epoch bigint NOT NULL,
    bundle_activation_id uuid NOT NULL,
    mechanism_identity text NOT NULL,
    context_manifest_artifact_id uuid,
    compiled_context_artifact_id uuid,
    context_digest text,
    failure_code text,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    prepared_at timestamp(6) with time zone,
    model_returned_at timestamp(6) with time zone,
    final_disposition text,
    validated_at timestamp(6) with time zone,
    application_resolution text,
    committed_at timestamp(6) with time zone,
    CONSTRAINT cognitive_episodes_application_resolution_check CHECK (((application_resolution IS NULL) OR (application_resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'deferred'::text, 'declined'::text, 'no_action'::text, 'need_information'::text, 'stale'::text])))),
    CONSTRAINT cognitive_episodes_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT cognitive_episodes_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_episodes_cognitive_episode_id_check CHECK ((uuid_extract_version(cognitive_episode_id) = 7)),
    CONSTRAINT cognitive_episodes_context_digest_check CHECK (((context_digest IS NULL) OR (context_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT cognitive_episodes_failure_code_check CHECK (((failure_code IS NULL) OR (failure_code ~ '^[A-Z][A-Z0-9-]{2,127}$'::text))),
    CONSTRAINT cognitive_episodes_final_disposition_check CHECK (((final_disposition IS NULL) OR (final_disposition = ANY (ARRAY['change'::text, 'no_change'::text, 'defer'::text, 'decline'::text, 'no_action'::text, 'need_information'::text])))),
    CONSTRAINT cognitive_episodes_mechanism_identity_check CHECK ((mechanism_identity = 'armi.context-compiler.deterministic-v1'::text)),
    CONSTRAINT cognitive_episodes_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_web_evidence'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text]))),
    CONSTRAINT cognitive_episodes_scene_shape_check CHECK ((((purpose = ANY (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text])) AND (scene_id IS NULL) AND (context_party_id IS NULL)) OR ((purpose <> ALL (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text])) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL)))),
    CONSTRAINT cognitive_episodes_state_check CHECK ((((status = 'preparing'::text) AND (context_digest IS NULL) AND (prepared_at IS NULL) AND (model_returned_at IS NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['prepared'::text, 'calling_model'::text])) AND (context_digest IS NOT NULL) AND (prepared_at IS NOT NULL) AND (model_returned_at IS NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['model_returned'::text, 'validating'::text])) AND (context_digest IS NOT NULL) AND (prepared_at IS NOT NULL) AND (model_returned_at IS NOT NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['candidate_validated'::text, 'committing'::text])) AND (context_digest IS NOT NULL) AND (model_returned_at IS NOT NULL) AND (validated_at IS NOT NULL) AND (final_disposition IS NOT NULL) AND (failure_code IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = 'candidate_rejected'::text) AND (validated_at IS NOT NULL) AND (final_disposition IS NULL) AND (failure_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = 'completed'::text) AND (application_resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'declined'::text, 'no_action'::text, 'deferred'::text, 'need_information'::text])) AND (committed_at IS NOT NULL)) OR ((status = 'stale'::text) AND (application_resolution = 'stale'::text) AND (committed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'cancelled'::text])) AND (failure_code IS NOT NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)))),
    CONSTRAINT cognitive_episodes_status_check CHECK ((status = ANY (ARRAY['preparing'::text, 'prepared'::text, 'calling_model'::text, 'model_returned'::text, 'validating'::text, 'candidate_validated'::text, 'candidate_rejected'::text, 'committing'::text, 'completed'::text, 'stale'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT cognitive_episodes_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);

--
-- Name: exact_life_query_intents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.exact_life_query_intents (
    exact_life_query_intent_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    source_opportunity_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    record_kind text NOT NULL,
    query_text text,
    result_limit smallint NOT NULL,
    query_digest text NOT NULL,
    execution_work_id uuid NOT NULL,
    status text NOT NULL,
    result_artifact_id uuid,
    result_count smallint,
    failure_code text,
    result_opportunity_id uuid,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT exact_life_query_intents_check CHECK ((((status = 'pending'::text) AND (result_artifact_id IS NULL) AND (result_count IS NULL) AND (failure_code IS NULL) AND (result_opportunity_id IS NULL) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'empty'::text])) AND (result_artifact_id IS NOT NULL) AND (result_count IS NOT NULL) AND (failure_code IS NULL) AND (result_opportunity_id IS NOT NULL) AND (completed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'denied'::text])) AND (result_count = 0) AND (failure_code IS NOT NULL) AND (completed_at IS NOT NULL) AND (((result_artifact_id IS NOT NULL) AND (result_opportunity_id IS NOT NULL)) OR ((status = 'failed'::text) AND (result_artifact_id IS NULL) AND (result_opportunity_id IS NULL)))))),
    CONSTRAINT exact_life_query_intents_check1 CHECK (((status = 'empty'::text) = ((result_count = 0) AND (failure_code IS NULL)))),
    CONSTRAINT exact_life_query_intents_check2 CHECK (((status = 'succeeded'::text) = (result_count > 0))),
    CONSTRAINT exact_life_query_intents_exact_life_query_intent_id_check CHECK ((uuid_extract_version(exact_life_query_intent_id) = 7)),
    CONSTRAINT exact_life_query_intents_failure_code_check CHECK (((failure_code IS NULL) OR (failure_code ~ '^LIFE-QUERY-[A-Z0-9-]+$'::text))),
    CONSTRAINT exact_life_query_intents_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT exact_life_query_intents_query_digest_check CHECK ((query_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT exact_life_query_intents_query_text_check CHECK (((query_text IS NULL) OR ((octet_length(query_text) >= 1) AND (octet_length(query_text) <= 1024) AND (btrim(query_text) <> ''::text)))),
    CONSTRAINT exact_life_query_intents_record_kind_check CHECK ((record_kind = ANY (ARRAY['activity'::text, 'conversation'::text, 'material'::text, 'memory'::text, 'relationship'::text, 'self_change'::text]))),
    CONSTRAINT exact_life_query_intents_result_count_check CHECK (((result_count IS NULL) OR ((result_count >= 0) AND (result_count <= 20)))),
    CONSTRAINT exact_life_query_intents_result_limit_check CHECK (((result_limit >= 1) AND (result_limit <= 20))),
    CONSTRAINT exact_life_query_intents_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'succeeded'::text, 'empty'::text, 'failed'::text, 'denied'::text]))),
    CONSTRAINT exact_life_query_intents_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);

--
-- Name: experience_evidence_links; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.experience_evidence_links (
    experience_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    context_item_id uuid NOT NULL,
    link_kind text NOT NULL,
    ordinal smallint NOT NULL,
    CONSTRAINT experience_evidence_links_link_kind_check CHECK ((link_kind = 'relied_on'::text)),
    CONSTRAINT experience_evidence_links_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 8)))
);

--
-- Name: external_evidence; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.external_evidence (
    evidence_id uuid NOT NULL,
    interaction_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    context_party_id uuid,
    artifact_id uuid NOT NULL,
    source_kind text NOT NULL,
    trust_status text NOT NULL,
    privacy_scope text NOT NULL,
    acceptance_status text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    web_observation_request_id uuid,
    observation_attempt_id uuid,
    codex_task_source_id uuid,
    codex_verification_id uuid,
    CONSTRAINT external_evidence_acceptance_status_check CHECK ((acceptance_status = 'accepted'::text)),
    CONSTRAINT external_evidence_evidence_id_check CHECK ((uuid_extract_version(evidence_id) = 7)),
    CONSTRAINT external_evidence_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['creator_visible'::text, 'private'::text]))),
    CONSTRAINT external_evidence_source_identity_check CHECK ((((source_kind = ANY (ARRAY['creator_input'::text, 'other_human_input'::text])) AND (interaction_id IS NOT NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL)) OR ((source_kind = 'web_search'::text) AND (interaction_id IS NULL) AND (web_observation_request_id IS NOT NULL) AND (observation_attempt_id IS NOT NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL)) OR ((source_kind = 'codex_task_source'::text) AND (interaction_id IS NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NOT NULL) AND (codex_verification_id IS NULL)) OR ((source_kind = 'codex_result'::text) AND (interaction_id IS NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NOT NULL)))),
    CONSTRAINT external_evidence_source_kind_check CHECK ((source_kind = ANY (ARRAY['creator_input'::text, 'web_search'::text, 'codex_task_source'::text, 'codex_result'::text, 'other_human_input'::text]))),
    CONSTRAINT external_evidence_trust_status_check CHECK ((trust_status = 'external_claim'::text))
);

--
-- Name: opportunities; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.opportunities (
    opportunity_id uuid NOT NULL,
    evidence_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid,
    context_party_id uuid,
    purpose text NOT NULL,
    eligibility_status text NOT NULL,
    current_disposition text NOT NULL,
    available_after timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    expires_at timestamp(6) with time zone,
    selected_at timestamp(6) with time zone,
    root_opportunity_id uuid NOT NULL,
    predecessor_opportunity_id uuid,
    reconsideration_no smallint DEFAULT 0 NOT NULL,
    resolved_at timestamp(6) with time zone,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_version bigint NOT NULL,
    activity_id uuid,
    CONSTRAINT opportunities_current_disposition_check CHECK ((current_disposition = ANY (ARRAY['open'::text, 'selected'::text, 'resolved'::text, 'superseded'::text, 'cancelled'::text]))),
    CONSTRAINT opportunities_eligibility_status_check CHECK ((eligibility_status = 'eligible'::text)),
    CONSTRAINT opportunities_expiry_check CHECK (((expires_at IS NULL) OR (expires_at > available_after))),
    CONSTRAINT opportunities_lineage_check CHECK ((((reconsideration_no = 0) AND (root_opportunity_id = opportunity_id) AND (predecessor_opportunity_id IS NULL)) OR ((reconsideration_no = 1) AND (root_opportunity_id <> opportunity_id) AND (predecessor_opportunity_id IS NOT NULL)))),
    CONSTRAINT opportunities_opportunity_id_check CHECK ((uuid_extract_version(opportunity_id) = 7)),
    CONSTRAINT opportunities_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_web_evidence'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text]))),
    CONSTRAINT opportunities_reconsideration_check CHECK (((reconsideration_no >= 0) AND (reconsideration_no <= 1))),
    CONSTRAINT opportunities_resolution_state_check CHECK ((((current_disposition = 'open'::text) AND (selected_at IS NULL) AND (resolved_at IS NULL)) OR ((current_disposition = 'selected'::text) AND (selected_at IS NOT NULL) AND (resolved_at IS NULL)) OR ((current_disposition = ANY (ARRAY['resolved'::text, 'superseded'::text])) AND (selected_at IS NOT NULL) AND (resolved_at IS NOT NULL)) OR ((current_disposition = 'cancelled'::text) AND (resolved_at IS NOT NULL)))),
    CONSTRAINT opportunities_source_kind_check CHECK ((source_kind = ANY (ARRAY['external_evidence'::text, 'life_generation_available'::text, 'subject_component_revision'::text, 'activity_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text, 'life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_activity'::text, 'creator_outreach_relationship'::text]))),
    CONSTRAINT opportunities_source_shape_check CHECK ((((source_kind = 'external_evidence'::text) AND (evidence_id = source_ref) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NULL)) OR ((source_kind = ANY (ARRAY['life_generation_available'::text, 'subject_component_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text])) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = 'activity_revision'::text) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NOT NULL)) OR ((source_kind = ANY (ARRAY['life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_relationship'::text])) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NULL)) OR ((source_kind = 'creator_outreach_activity'::text) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NOT NULL)))),
    CONSTRAINT opportunities_source_version_check CHECK ((source_version > 0))
);
