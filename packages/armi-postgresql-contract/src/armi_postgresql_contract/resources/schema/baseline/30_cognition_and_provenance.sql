-- Current ARMI schema tables owned by this baseline module.

--
-- Name: accepted_experiences; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.accepted_experiences (
    evidence_links jsonb DEFAULT '[]'::jsonb NOT NULL CHECK (jsonb_typeof(evidence_links)='array' AND jsonb_array_length(evidence_links)<=8),
    acceptance_ordinal bigint GENERATED ALWAYS AS IDENTITY,
    experience_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    experience_kind text NOT NULL,
    fact_class text NOT NULL,
    first_person_gist text,
    scene_id uuid,
    occurred_at timestamp(6) with time zone NOT NULL,
    learned_at timestamp(6) with time zone NOT NULL,
    accepted_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    source_perspective text NOT NULL,
    uncertainty text,
    data_rights_order_id uuid,
    data_rights_hidden_at timestamp(6) with time zone,
    CONSTRAINT accepted_experiences_experience_id_check CHECK ((uuid_extract_version(experience_id) = 7)),
    CONSTRAINT accepted_experiences_acceptance_ordinal_check CHECK ((acceptance_ordinal > 0)),
    CONSTRAINT accepted_experiences_experience_kind_check CHECK ((experience_kind = ANY (ARRAY['creator_input'::text, 'codex_observation'::text, 'other_human_input'::text, 'visual_observation'::text]))),
    CONSTRAINT accepted_experiences_fact_class_check CHECK ((fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT accepted_experiences_first_person_gist_check CHECK ((((data_rights_hidden_at IS NULL) AND (length(first_person_gist) BETWEEN 1 AND 1024)) OR ((data_rights_hidden_at IS NOT NULL) AND (first_person_gist IS NULL)))),
    CONSTRAINT accepted_experiences_data_rights_check CHECK (((data_rights_order_id IS NULL) = (data_rights_hidden_at IS NULL))),
    CONSTRAINT accepted_experiences_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT accepted_experiences_source_pair_check CHECK ((((experience_kind = 'creator_input'::text) AND (source_perspective = 'creator_claim'::text) AND (scene_id IS NOT NULL)) OR ((experience_kind = 'codex_observation'::text) AND (source_perspective = 'codex_observation'::text) AND (scene_id IS NOT NULL)) OR ((experience_kind = 'other_human_input'::text) AND (source_perspective = 'other_human_claim'::text) AND (scene_id IS NOT NULL)) OR ((experience_kind = 'visual_observation'::text) AND (source_perspective = 'visual_model_observation'::text) AND (scene_id IS NULL) AND (fact_class = ANY (ARRAY['external_claim'::text, 'inference'::text, 'unknown'::text]))))),
    CONSTRAINT accepted_experiences_source_perspective_check CHECK ((source_perspective = ANY (ARRAY['creator_claim'::text, 'codex_observation'::text, 'other_human_claim'::text, 'visual_model_observation'::text]))),
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
    credential_identity text NOT NULL,
    request_artifact_id uuid,
    dispatch_status text NOT NULL,
    provider_request_id text,
    provider_model_id text,
    response_artifact_id uuid,
    input_tokens integer,
    output_tokens integer,
    cached_input_tokens integer,
    result_status text,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object'),
    CONSTRAINT cognitive_attempts_attempt_no_check CHECK ((attempt_no >= 1)),
    CONSTRAINT cognitive_attempts_cached_input_tokens_check CHECK (((cached_input_tokens IS NULL) OR (cached_input_tokens >= 0))),
    CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK ((candidate_schema_version = ANY (ARRAY['armi.cognition-candidate.v12'::text, 'armi.creator-dialogue-candidate.v25'::text, 'armi.creator-dialogue-candidate.v26'::text, 'armi.creator-cognitive-act-candidate.v3'::text, 'armi.creator-voice-act-candidate.v3'::text, 'armi.autonomous-activity-candidate.v4'::text, 'armi.activity-attention-candidate.v4'::text, 'armi.activity-internal-work-candidate.v3'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.owner-reflection-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v6'::text, 'armi.visual-observation-candidate.v1'::text, 'armi.creator-cognitive-act-candidate.v4'::text, 'armi.creator-cognitive-act-candidate.v5'::text, 'armi.creator-cognitive-act-candidate.v6'::text, 'armi.creator-cognitive-act-candidate.v8'::text, 'armi.creator-voice-act-candidate.v4'::text, 'armi.creator-voice-act-candidate.v5'::text, 'armi.creator-voice-act-candidate.v6'::text, 'armi.creator-voice-act-candidate.v8'::text, 'armi.cognition-candidate.v13'::text, 'armi.cognition-candidate.v14'::text, 'armi.cognition-candidate.v15'::text, 'armi.cognition-candidate.v16'::text, 'armi.cognition-candidate.v18'::text, 'armi.activity-attention-candidate.v5'::text, 'armi.activity-internal-work-candidate.v4'::text, 'armi.activity-internal-work-candidate.v5'::text, 'armi.autonomous-activity-candidate.v5'::text, 'armi.autonomous-activity-candidate.v6'::text, 'armi.autonomous-activity-candidate.v7'::text, 'armi.autonomous-activity-candidate.v8'::text, 'armi.autonomous-activity-candidate.v9'::text, 'armi.autonomous-activity-candidate.v10'::text, 'armi.autonomous-activity-candidate.v12'::text, 'armi.autonomy-check-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v7'::text, 'armi.other-human-dialogue-candidate.v8'::text, 'armi.other-human-dialogue-candidate.v9'::text, 'armi.visual-observation-candidate.v2'::text, 'armi.visual-observation-candidate.v3'::text, 'armi.visual-observation-candidate.v4'::text, 'armi.owner-reflection-candidate.v2'::text, 'armi.owner-reflection-candidate.v3'::text, 'armi.owner-reflection-candidate.v4'::text, 'armi.maintenance-work-candidate.v2'::text, 'armi.maintenance-work-candidate.v3'::text]))),
    CONSTRAINT cognitive_attempts_check CHECK ((((dispatch_status = 'prepared'::text) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (response_artifact_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'dispatched'::text) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (response_artifact_id IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'settled'::text) AND (settled_at IS NOT NULL) AND (result_status IS NOT NULL) AND (((result_status = 'succeeded'::text) AND (dispatched_at IS NOT NULL) AND (provider_request_id IS NOT NULL) AND (provider_model_id IS NOT NULL) AND (response_artifact_id IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (cached_input_tokens IS NOT NULL) AND (error_code IS NULL)) OR ((result_status <> 'succeeded'::text) AND (response_artifact_id IS NULL) AND (error_code IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = 'cancelled'::text) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL)))))))),
    CONSTRAINT cognitive_attempts_credential_identity_check CHECK (credential_identity IN ('armi.model.ark-api-key.v1', 'armi.model.qwen-api-key.v1', 'armi.model.deepseek-api-key.v1')),
    CONSTRAINT cognitive_attempts_dispatch_status_check CHECK ((dispatch_status = ANY (ARRAY['prepared'::text, 'dispatched'::text, 'settled'::text]))),
    CONSTRAINT cognitive_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^MODEL-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_attempts_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens >= 0))),
    CONSTRAINT cognitive_attempts_model_attempt_id_check CHECK ((uuid_extract_version(model_attempt_id) = 7)),
    CONSTRAINT cognitive_attempts_model_id_check CHECK (model_id ~ '^[a-z0-9][a-z0-9._-]{0,127}$'),
    CONSTRAINT cognitive_attempts_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens >= 0))),
    CONSTRAINT cognitive_attempts_profile_check CHECK ((profile = ANY (ARRAY['creator_input_cognition'::text, 'creator_cognitive_act'::text, 'creator_voice_act'::text, 'creator_outreach'::text, 'other_human_dialogue'::text, 'autonomous_activity'::text, 'activity_attention'::text, 'activity_internal_work'::text, 'sleep_decision'::text, 'memory_maintenance'::text, 'subject_self_check'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text, 'codex_task'::text, 'codex_result'::text, 'visual_observation'::text]))),
    CONSTRAINT cognitive_attempts_provider_check CHECK (provider IN ('volcengine_ark', 'qwen', 'deepseek')),
    CONSTRAINT cognitive_attempts_provider_model_id_check CHECK (provider_model_id IS NULL OR provider_model_id ~ '^[a-z0-9][a-z0-9._-]{0,127}$'),
    CONSTRAINT cognitive_attempts_request_schema_version_check CHECK ((request_schema_version = 'armi.model-request.v1'::text)),
    CONSTRAINT cognitive_attempts_result_status_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'rejected'::text, 'timed_out'::text, 'provider_failed'::text, 'cancelled'::text, 'outcome_unknown'::text])))),
    CONSTRAINT cognitive_attempts_version_policy_check CHECK ((version_policy = ANY (ARRAY['provider_evolving_alias'::text, 'fixed_provider_model'::text]))),
    CONSTRAINT cognitive_attempts_work_attempt_id_check CHECK ((uuid_extract_version(work_attempt_id) = 7))
);

--
--



--
-- Name: cognitive_episodes; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.cognitive_episodes (
    context_items jsonb DEFAULT '[]'::jsonb NOT NULL CHECK (jsonb_typeof(context_items)='array'),
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
    maintenance_source_episode_id uuid,
    maintenance_trigger_kind text,
    maintenance_status text,
    maintenance_from_ordinal bigint,
    maintenance_through_ordinal bigint,
    maintenance_experience_ids uuid[],
    maintenance_finished_at timestamp(6) with time zone,
    CONSTRAINT cognitive_episodes_maintenance_shape CHECK (
        (maintenance_trigger_kind IS NULL AND maintenance_status IS NULL
         AND maintenance_from_ordinal IS NULL AND maintenance_through_ordinal IS NULL
         AND maintenance_experience_ids IS NULL AND maintenance_finished_at IS NULL)
        OR (maintenance_trigger_kind IS NOT NULL AND maintenance_status IS NOT NULL
            AND maintenance_source_episode_id IS NOT NULL
            AND maintenance_source_episode_id=cognitive_episode_id
            AND purpose='maintain_subjective_memory'
            AND maintenance_from_ordinal IS NOT NULL AND maintenance_from_ordinal>=0
            AND maintenance_through_ordinal IS NOT NULL
            AND maintenance_through_ordinal>maintenance_from_ordinal
            AND maintenance_experience_ids IS NOT NULL
            AND cardinality(maintenance_experience_ids)<=64
            AND (cardinality(maintenance_experience_ids)=0 OR array_ndims(maintenance_experience_ids)=1)
            AND array_position(maintenance_experience_ids,NULL) IS NULL)
    ),
    CONSTRAINT cognitive_episodes_maintenance_trigger CHECK (
        maintenance_trigger_kind IN ('runtime_idle','sleep')
    ),
    CONSTRAINT cognitive_episodes_maintenance_status CHECK (
        maintenance_status='running' OR maintenance_status='completed'
    ),
    CONSTRAINT cognitive_episodes_maintenance_finished CHECK (
        maintenance_status IS NULL OR
        ((maintenance_status='completed') = (maintenance_finished_at IS NOT NULL))
    ),
    context_manifest_artifact_id uuid,
    compiled_context_artifact_id uuid,
    compiled_context_digest text,
    failure_code text,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    prepared_at timestamp(6) with time zone,
    model_returned_at timestamp(6) with time zone,
    final_disposition text,
    validated_at timestamp(6) with time zone,
    application_resolution text,
    committed_at timestamp(6) with time zone,
    candidate_validation_id uuid UNIQUE,
    validated_model_attempt_id uuid UNIQUE,
    validation_status text,
    change_set_artifact_id uuid,
    candidate_application_id uuid UNIQUE,
    subject_commit_id uuid UNIQUE,
    new_subject_version bigint,
    commit_runtime_instance_id uuid,
    commit_fence_token bigint,
    CONSTRAINT cognitive_episodes_subject_commit_key UNIQUE (subject_commit_id,subject_id),
    CONSTRAINT cognitive_episodes_subject_version_key UNIQUE (subject_id,new_subject_version),
    CONSTRAINT cognitive_episodes_commit_ledger_check CHECK (
        (subject_commit_id IS NULL AND new_subject_version IS NULL
         AND commit_runtime_instance_id IS NULL AND commit_fence_token IS NULL)
        OR (subject_commit_id IS NOT NULL AND candidate_validation_id IS NOT NULL
            AND new_subject_version IS NOT NULL AND new_subject_version=base_subject_version+1
            AND commit_runtime_instance_id IS NOT NULL
            AND commit_fence_token IS NOT NULL AND commit_fence_token>0
            AND uuid_extract_version(subject_commit_id)=7)
    ),
    successor_opportunity_id uuid UNIQUE,
    observed_subject_version bigint,
    exact_life_query_intent_id uuid,
    life_query_creator_party_id uuid,
    life_query_proposal_ref text,
    life_query_record_kind text,
    life_query_text text,
    life_query_result_limit smallint,
    life_query_digest text,
    life_query_work_id uuid,
    life_query_status text,
    life_query_result_artifact_id uuid,
    life_query_result_count smallint,
    life_query_failure_code text,
    life_query_result_opportunity_id uuid,
    life_query_created_at timestamp(6) with time zone,
    life_query_completed_at timestamp(6) with time zone,
    CONSTRAINT cognitive_episodes_life_query_shape CHECK (
        (exact_life_query_intent_id IS NULL AND life_query_creator_party_id IS NULL AND life_query_proposal_ref IS NULL AND life_query_record_kind IS NULL AND life_query_text IS NULL AND life_query_result_limit IS NULL AND life_query_digest IS NULL AND life_query_work_id IS NULL AND life_query_status IS NULL AND life_query_result_artifact_id IS NULL AND life_query_result_count IS NULL AND life_query_failure_code IS NULL AND life_query_result_opportunity_id IS NULL AND life_query_created_at IS NULL AND life_query_completed_at IS NULL)
        OR (exact_life_query_intent_id IS NOT NULL AND life_query_creator_party_id IS NOT NULL AND life_query_proposal_ref IS NOT NULL AND life_query_record_kind IS NOT NULL AND life_query_result_limit IS NOT NULL AND life_query_digest IS NOT NULL AND life_query_work_id IS NOT NULL AND life_query_status IS NOT NULL AND life_query_created_at IS NOT NULL AND candidate_validation_id IS NOT NULL AND scene_id IS NOT NULL)
    ),
    CONSTRAINT cognitive_episodes_life_query_check CHECK ((((life_query_status = 'pending'::text) AND (life_query_result_artifact_id IS NULL) AND (life_query_result_count IS NULL) AND (life_query_failure_code IS NULL) AND (life_query_result_opportunity_id IS NULL) AND (life_query_completed_at IS NULL)) OR ((life_query_status = ANY (ARRAY['succeeded'::text, 'empty'::text])) AND (life_query_result_artifact_id IS NOT NULL) AND (life_query_result_count IS NOT NULL) AND (life_query_failure_code IS NULL) AND (life_query_result_opportunity_id IS NOT NULL) AND (life_query_completed_at IS NOT NULL)) OR ((life_query_status = ANY (ARRAY['failed'::text, 'denied'::text])) AND (life_query_result_count = 0) AND (life_query_failure_code IS NOT NULL) AND (life_query_completed_at IS NOT NULL) AND (((life_query_result_artifact_id IS NOT NULL) AND (life_query_result_opportunity_id IS NOT NULL)) OR ((life_query_status = 'failed'::text) AND (life_query_result_artifact_id IS NULL) AND (life_query_result_opportunity_id IS NULL)))))),
    CONSTRAINT cognitive_episodes_life_query_check1 CHECK (((life_query_status = 'empty'::text) = ((life_query_result_count = 0) AND (life_query_failure_code IS NULL)))),
    CONSTRAINT cognitive_episodes_life_query_check2 CHECK (((life_query_status = 'succeeded'::text) = (life_query_result_count > 0))),
    CONSTRAINT cognitive_episodes_life_query_id_check CHECK ((uuid_extract_version(exact_life_query_intent_id) = 7)),
    CONSTRAINT cognitive_episodes_life_query_failure_code_check CHECK (((life_query_failure_code IS NULL) OR (life_query_failure_code ~ '^LIFE-QUERY-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_episodes_life_query_proposal_ref_check CHECK ((life_query_proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT cognitive_episodes_life_query_query_digest_check CHECK ((life_query_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_episodes_life_query_query_text_check CHECK (((life_query_text IS NULL) OR ((octet_length(life_query_text) >= 1) AND (octet_length(life_query_text) <= 1024) AND (btrim(life_query_text) <> ''::text)))),
    CONSTRAINT cognitive_episodes_life_query_record_kind_check CHECK ((life_query_record_kind = ANY (ARRAY['activity'::text, 'conversation'::text, 'material'::text, 'memory'::text, 'relationship'::text, 'self_change'::text]))),
    CONSTRAINT cognitive_episodes_life_query_result_count_check CHECK (((life_query_result_count IS NULL) OR ((life_query_result_count >= 0) AND (life_query_result_count <= 20)))),
    CONSTRAINT cognitive_episodes_life_query_result_limit_check CHECK (((life_query_result_limit >= 1) AND (life_query_result_limit <= 20))),
    CONSTRAINT cognitive_episodes_life_query_status_check CHECK ((life_query_status = ANY (ARRAY['pending'::text, 'succeeded'::text, 'empty'::text, 'failed'::text, 'denied'::text]))),
    dialogue_decision_kind text,
    dialogue_reason_class text,
    dialogue_proposal_ref text,
    dialogue_operation_ref uuid,
    dialogue_effect_id uuid,
    CONSTRAINT cognitive_episodes_dialogue_shape_check CHECK (
        (dialogue_decision_kind IS NULL AND dialogue_reason_class IS NULL AND dialogue_proposal_ref IS NULL AND dialogue_operation_ref IS NULL AND dialogue_effect_id IS NULL)
        OR (dialogue_decision_kind IS NOT NULL AND dialogue_operation_ref IS NOT NULL
            AND candidate_validation_id IS NOT NULL
            AND dialogue_decision_kind IN ('reply','decline','silence','no_change','need_information','defer','end_conversation')
            AND uuid_extract_version(dialogue_operation_ref)=7
            AND ((dialogue_decision_kind <> 'end_conversation' AND dialogue_proposal_ref IS NOT NULL AND dialogue_effect_id IS NOT NULL)
                OR (dialogue_decision_kind <> 'reply' AND dialogue_effect_id IS NULL)))
    ),
    maintenance_session_id uuid,
    maintenance_phase_id uuid,
    maintenance_head_version bigint,
    maintenance_phase text,
    maintenance_outcome text,
    maintenance_result_summary text,
    maintenance_creator_visible_problem text,
    maintenance_memory_id uuid,
    maintenance_issue_target text,
    maintenance_completed_at timestamp(6) with time zone,
    CONSTRAINT cognitive_episodes_maintenance_result_shape CHECK (
        (maintenance_session_id IS NULL AND maintenance_phase_id IS NULL AND maintenance_head_version IS NULL AND maintenance_phase IS NULL AND maintenance_outcome IS NULL AND maintenance_result_summary IS NULL AND maintenance_creator_visible_problem IS NULL AND maintenance_memory_id IS NULL AND maintenance_issue_target IS NULL AND maintenance_completed_at IS NULL)
        OR (maintenance_session_id IS NOT NULL AND maintenance_phase_id IS NOT NULL AND maintenance_head_version IS NOT NULL AND maintenance_head_version > 0 AND maintenance_phase IS NOT NULL AND maintenance_outcome IS NOT NULL AND maintenance_result_summary IS NOT NULL AND maintenance_completed_at IS NOT NULL AND candidate_application_id IS NOT NULL AND subject_commit_id IS NOT NULL)),
    CONSTRAINT cognitive_episodes_maintenance_result CHECK (maintenance_outcome IS NULL OR (
        ((maintenance_phase='memory_maintenance' AND maintenance_outcome IN ('memory_changed','memory_unchanged'))
        OR (maintenance_phase='self_check' AND maintenance_outcome IN ('issue_found','no_issue'))
        OR (maintenance_phase IN ('reflect_self','reflect_mind','reflect_mood','reflect_prompt') AND maintenance_outcome IN ('reflection_changed','reflection_unchanged')))
        AND ((maintenance_outcome='memory_changed')=(maintenance_memory_id IS NOT NULL))
        AND ((maintenance_outcome='issue_found')=(maintenance_creator_visible_problem IS NOT NULL))
        AND ((maintenance_outcome='issue_found')=(maintenance_issue_target IS NOT NULL))
        AND (maintenance_issue_target IS NULL OR maintenance_issue_target IN ('self','mind','prompt'))
        AND length(maintenance_result_summary) BETWEEN 1 AND 512
        AND (maintenance_creator_visible_problem IS NULL OR length(maintenance_creator_visible_problem) BETWEEN 1 AND 512))),
    sleep_decision_kind text,
    sleep_cycle_anchor_ref uuid,
    sleep_review_not_before timestamp(6) with time zone,
    CONSTRAINT cognitive_episodes_sleep_decision_check CHECK (
        (sleep_decision_kind IS NULL AND sleep_cycle_anchor_ref IS NULL AND sleep_review_not_before IS NULL)
        OR (sleep_decision_kind IS NOT NULL
            AND sleep_decision_kind IN ('sleep','stay_awake','defer','need_information')
            AND purpose='consider_sleep' AND candidate_application_id IS NOT NULL
            AND sleep_cycle_anchor_ref IS NOT NULL
            AND uuid_extract_version(sleep_cycle_anchor_ref)=7
            AND ((sleep_decision_kind='defer') = (sleep_review_not_before IS NOT NULL)))
    ),
    CONSTRAINT cognitive_episodes_validation_result_check CHECK (
        (validation_status IS NULL AND candidate_validation_id IS NULL AND validated_model_attempt_id IS NULL AND change_set_artifact_id IS NULL)
        OR (validation_status IS NOT NULL AND validation_status='rejected' AND candidate_validation_id IS NULL AND validated_model_attempt_id IS NULL AND change_set_artifact_id IS NULL AND validated_at IS NOT NULL)
        OR (validation_status IS NOT NULL AND validation_status IN ('accepted','partially_accepted') AND candidate_validation_id IS NOT NULL AND validated_model_attempt_id IS NOT NULL AND change_set_artifact_id IS NOT NULL AND final_disposition IS NOT NULL AND validated_at IS NOT NULL)
    ),
    CONSTRAINT cognitive_episodes_application_result_check CHECK (
        (candidate_application_id IS NULL AND successor_opportunity_id IS NULL AND observed_subject_version IS NULL AND (subject_commit_id IS NULL OR status='finalizing'))
        OR (candidate_application_id IS NOT NULL AND candidate_validation_id IS NOT NULL AND observed_subject_version IS NOT NULL AND observed_subject_version >= 0)
    ),
    CONSTRAINT cognitive_episodes_commit_result_check CHECK (
        application_resolution IS NULL OR
        ((application_resolution='applied') = (subject_commit_id IS NOT NULL))
    ),
    CONSTRAINT cognitive_episodes_successor_result_check CHECK (
        successor_opportunity_id IS NULL OR application_resolution IS NULL OR application_resolution='stale'
    ),
    CONSTRAINT cognitive_episodes_validation_identity_check CHECK (candidate_validation_id IS NULL OR uuid_extract_version(candidate_validation_id)=7),
    CONSTRAINT cognitive_episodes_application_identity_check CHECK (candidate_application_id IS NULL OR uuid_extract_version(candidate_application_id)=7),
    CONSTRAINT cognitive_episodes_application_resolution_check CHECK (((application_resolution IS NULL) OR (application_resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'deferred'::text, 'declined'::text, 'no_action'::text, 'need_information'::text, 'stale'::text])))),
    CONSTRAINT cognitive_episodes_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT cognitive_episodes_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_episodes_cognitive_episode_id_check CHECK ((uuid_extract_version(cognitive_episode_id) = 7)),
    CONSTRAINT cognitive_episodes_compiled_context_digest_check CHECK (((compiled_context_digest IS NULL) OR (compiled_context_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT cognitive_episodes_failure_code_check CHECK (((failure_code IS NULL) OR (failure_code ~ '^[A-Z][A-Z0-9-]{2,127}$'::text))),
    CONSTRAINT cognitive_episodes_final_disposition_check CHECK (((final_disposition IS NULL) OR (final_disposition = ANY (ARRAY['change'::text, 'no_change'::text, 'defer'::text, 'decline'::text, 'no_action'::text, 'need_information'::text])))),
    CONSTRAINT cognitive_episodes_mechanism_identity_check CHECK ((mechanism_identity = 'armi.context-compiler.layered-v3'::text)),
    CONSTRAINT cognitive_episodes_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_creator_voice_input'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomy_check'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text, 'consider_visual_observation'::text, 'consider_requested_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text]))),
    CONSTRAINT cognitive_episodes_scene_shape_check CHECK (((purpose IN ('consider_autonomy_check','consider_autonomous_life') AND ((scene_id IS NULL) = (context_party_id IS NULL))) OR ((purpose = ANY (ARRAY['consider_autonomy_check'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text])) AND (scene_id IS NULL) AND (context_party_id IS NULL)) OR ((purpose <> ALL (ARRAY['consider_autonomy_check'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text])) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL)))),
    CONSTRAINT cognitive_episodes_state_check CHECK (
        (status='preparing' AND compiled_context_digest IS NULL AND prepared_at IS NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('prepared','calling_model') AND compiled_context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status='finalizing' AND compiled_context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NOT NULL AND application_resolution IS NULL AND committed_at IS NULL AND failure_code IS NULL AND ((validated_at IS NULL AND final_disposition IS NULL) OR (validated_at IS NOT NULL AND final_disposition IS NOT NULL)))
        OR (status='candidate_rejected' AND validated_at IS NOT NULL AND final_disposition IS NULL AND failure_code ~ '^CANDIDATE-[A-Z0-9-]+$' AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status='completed' AND application_resolution IN ('applied','no_change','declined','no_action','deferred','need_information') AND committed_at IS NOT NULL)
        OR (status='stale' AND application_resolution='stale' AND committed_at IS NOT NULL)
        OR (status IN ('failed','cancelled') AND failure_code IS NOT NULL AND application_resolution IS NULL AND committed_at IS NULL)
    ),
    CONSTRAINT cognitive_episodes_status_check CHECK (status IN ('preparing','prepared','calling_model','finalizing','candidate_rejected','completed','stale','failed','cancelled')),
    CONSTRAINT cognitive_episodes_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);

--
-- Name: context_embedding_coverage; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.context_embedding_coverage (
    model_binding text NOT NULL,
    coverage_state text NOT NULL,
    epoch bigint DEFAULT 1 NOT NULL,
    scanning_epoch bigint,
    scan_found_missing boolean DEFAULT false NOT NULL,
    source_kind text,
    after_source_ref uuid,
    updated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    pending_work_count bigint DEFAULT 0 NOT NULL,
    CONSTRAINT context_embedding_coverage_binding_check CHECK ((model_binding = 'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1'::text)),
    CONSTRAINT context_embedding_coverage_cursor_check CHECK ((((coverage_state = ANY (ARRAY['dirty'::text, 'degraded'::text])) AND (scanning_epoch IS NULL) AND (source_kind IS NULL) AND (after_source_ref IS NULL)) OR ((coverage_state = 'reconciling'::text) AND (scanning_epoch IS NOT NULL) AND (source_kind = ANY (ARRAY['life_material'::text, 'subjective_memory'::text]))) OR ((coverage_state = 'complete'::text) AND (scanning_epoch IS NULL) AND (source_kind IS NULL) AND (after_source_ref IS NULL)))),
    CONSTRAINT context_embedding_coverage_epoch_check CHECK (((epoch > 0) AND ((scanning_epoch IS NULL) OR (scanning_epoch > 0)))),
    CONSTRAINT context_embedding_coverage_pending_check CHECK ((pending_work_count >= 0)),
    CONSTRAINT context_embedding_coverage_state_check CHECK ((coverage_state = ANY (ARRAY['dirty'::text, 'reconciling'::text, 'complete'::text, 'degraded'::text])))
);

--
-- Name: context_embedding_projections; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.context_embedding_projections (
    context_embedding_projection_id uuid CONSTRAINT context_embedding_projectio_context_embedding_projecti_not_null NOT NULL,
    subject_id uuid NOT NULL,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_version bigint NOT NULL,
    chunk_ordinal integer NOT NULL,
    chunk_text text NOT NULL,
    model_binding text NOT NULL,
    embedding armi_extensions.vector(1024) NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    retrieval_text text NOT NULL,
    CONSTRAINT context_embedding_projections_binding_check CHECK ((model_binding = 'armi.embedding.qwen3-0_6b-q8_0-local-1024.v1'::text)),
    CONSTRAINT context_embedding_projections_chunk_ordinal_check CHECK ((chunk_ordinal >= 0)),
    CONSTRAINT context_embedding_projections_chunk_text_check CHECK (((length(chunk_text) >= 1) AND (length(chunk_text) <= 1500))),
    CONSTRAINT context_embedding_projections_id_check CHECK ((uuid_extract_version(context_embedding_projection_id) = 7)),
    CONSTRAINT context_embedding_projections_retrieval_text_check CHECK (((length(retrieval_text) >= 1) AND (length(retrieval_text) <= 2000))),
    CONSTRAINT context_embedding_projections_source_kind_check CHECK ((source_kind = ANY (ARRAY['subjective_memory'::text, 'life_material'::text]))),
    CONSTRAINT context_embedding_projections_source_ref_check CHECK ((uuid_extract_version(source_ref) = 7)),
    CONSTRAINT context_embedding_projections_source_version_check CHECK ((source_version > 0))
);

CREATE TABLE armi.context_embedding_source_sets (
    subject_id uuid NOT NULL,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_version bigint NOT NULL,
    source_digest text NOT NULL,
    model_binding text NOT NULL,
    expected_chunk_count integer NOT NULL,
    state text NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT context_embedding_source_sets_source_check CHECK (source_kind = ANY (ARRAY['subjective_memory'::text, 'life_material'::text])),
    CONSTRAINT context_embedding_source_sets_source_ref_check CHECK (uuid_extract_version(source_ref) = 7),
    CONSTRAINT context_embedding_source_sets_version_check CHECK (source_version > 0),
    CONSTRAINT context_embedding_source_sets_digest_check CHECK (source_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT context_embedding_source_sets_count_check CHECK (expected_chunk_count > 0),
    CONSTRAINT context_embedding_source_sets_state_check CHECK (state = ANY (ARRAY['building'::text, 'complete'::text, 'stale'::text, 'failed'::text])),
    CONSTRAINT context_embedding_source_sets_completion_check CHECK ((state = 'complete') = (completed_at IS NOT NULL)),
    CONSTRAINT context_embedding_source_sets_pkey PRIMARY KEY (source_kind, source_ref, source_version, model_binding)
);

CREATE INDEX context_embedding_source_sets_current_idx
ON armi.context_embedding_source_sets
USING btree (subject_id, source_kind, source_ref, source_version, model_binding, state);

--
-- Name: context_model_cache_hit_ratios; Type: VIEW; Schema: armi; Owner: -
--

CREATE VIEW armi.context_model_cache_hit_ratios AS
 SELECT episode.purpose,
    count(*) FILTER (WHERE (attempt.result_status = 'succeeded'::text)) AS succeeded_attempts,
    count(*) FILTER (WHERE ((attempt.result_status = 'succeeded'::text) AND (attempt.cached_input_tokens > 0))) AS cache_hit_attempts,
    COALESCE(sum(attempt.cached_input_tokens) FILTER (WHERE (attempt.result_status = 'succeeded'::text)), (0)::bigint) AS cached_input_tokens,
    COALESCE(sum(attempt.input_tokens) FILTER (WHERE (attempt.result_status = 'succeeded'::text)), (0)::bigint) AS input_tokens,
        CASE
            WHEN (COALESCE(sum(attempt.input_tokens) FILTER (WHERE (attempt.result_status = 'succeeded'::text)), (0)::bigint) = 0) THEN (0)::numeric
            ELSE ((COALESCE(sum(attempt.cached_input_tokens) FILTER (WHERE (attempt.result_status = 'succeeded'::text)), (0)::bigint))::numeric / (sum(attempt.input_tokens) FILTER (WHERE (attempt.result_status = 'succeeded'::text)))::numeric)
        END AS cached_input_ratio
   FROM (armi.cognitive_episodes episode
     JOIN armi.cognitive_attempts attempt ON ((attempt.cognitive_episode_id = episode.cognitive_episode_id)))
  GROUP BY episode.purpose;


--
--


--
-- Name: external_evidence; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.external_evidence (
    evidence_id uuid NOT NULL,
    interaction_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid,
    context_party_id uuid,
    artifact_id uuid NOT NULL,
    source_kind text NOT NULL,
    privacy_scope text NOT NULL,
    acceptance_status text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    codex_task_source_id uuid,
    codex_verification_id uuid,
    visual_observation_id uuid,
    data_rights_order_id uuid,
    data_rights_hidden_at timestamp(6) with time zone,
    CONSTRAINT external_evidence_acceptance_status_check CHECK ((acceptance_status = ANY (ARRAY['accepted'::text, 'redacted'::text]))),
    CONSTRAINT external_evidence_data_rights_check CHECK ((((acceptance_status='accepted') AND (data_rights_order_id IS NULL) AND (data_rights_hidden_at IS NULL)) OR ((acceptance_status='redacted') AND (data_rights_order_id IS NOT NULL) AND (data_rights_hidden_at IS NOT NULL)))),
    CONSTRAINT external_evidence_evidence_id_check CHECK ((uuid_extract_version(evidence_id) = 7)),
    CONSTRAINT external_evidence_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['creator_visible'::text, 'private'::text]))),
    CONSTRAINT external_evidence_source_identity_check CHECK ((((source_kind = ANY (ARRAY['creator_input'::text, 'other_human_input'::text])) AND (interaction_id IS NOT NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL) AND (visual_observation_id IS NULL)) OR ((source_kind = 'codex_task_source'::text) AND (interaction_id IS NULL) AND (codex_task_source_id IS NOT NULL) AND (codex_verification_id IS NULL) AND (visual_observation_id IS NULL)) OR ((source_kind = 'codex_result'::text) AND (interaction_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NOT NULL) AND (visual_observation_id IS NULL)) OR ((source_kind = 'visual_observation'::text) AND (interaction_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL) AND (visual_observation_id IS NOT NULL) AND (privacy_scope = 'private'::text)))),
    CONSTRAINT external_evidence_source_kind_check CHECK ((source_kind = ANY (ARRAY['creator_input'::text, 'codex_task_source'::text, 'codex_result'::text, 'other_human_input'::text, 'visual_observation'::text])))
);

--
-- Name: mood_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.mood_revisions (
    is_current boolean DEFAULT false NOT NULL,
    mood_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    mood_version bigint NOT NULL,
    previous_revision_id uuid,
    origin_kind text NOT NULL,
    origin_ref uuid NOT NULL,
    subject_commit_id uuid,
    proposal_ref text,
    semantic_payload jsonb NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    admin_change_id uuid,
    mood_appraisal_event_id uuid,
    mood_episode_id uuid,
    previous_appraisal_event_id uuid,
    transition text,
    event_phase text,
    gist text,
    basis_ordinals smallint[],
    appraisal_payload jsonb,
    importance smallint,
    derived_vad jsonb,
    affect_intensity smallint CHECK (affect_intensity BETWEEN 0 AND 100),
    affect_half_life_seconds integer CHECK (affect_half_life_seconds BETWEEN 900 AND 86400),
    derived_components jsonb,
    derivation_version text,
    dynamics_version text,
    occurred_at timestamp(6) with time zone,
    appraisal_mapping_version text,
    derived_appraisal_payload jsonb,
    data_rights_redacted_at timestamp(6) with time zone,
    CONSTRAINT mood_revisions_appraisal_appraisal_payload_check CHECK (((data_rights_redacted_at IS NOT NULL) OR (jsonb_typeof(appraisal_payload) = 'object'::text))),
    CONSTRAINT mood_revisions_appraisal_basis_ordinals_check CHECK (((cardinality(basis_ordinals) >= 1) AND (cardinality(basis_ordinals) <= 8))),
    CONSTRAINT mood_revisions_appraisal_derivation_version_check CHECK ((derivation_version = 'cpm-fuzzy.v4'::text)),
    CONSTRAINT mood_revisions_appraisal_derived_components_check CHECK (((jsonb_typeof(derived_components) = 'array'::text) AND ((jsonb_array_length(derived_components) >= 0) AND (jsonb_array_length(derived_components) <= 3)))),
    CONSTRAINT mood_revisions_appraisal_derived_vad_check CHECK ((jsonb_typeof(derived_vad) = 'object'::text)),
    CONSTRAINT mood_revisions_appraisal_dynamics_version_check CHECK ((dynamics_version = 'recency-reappraisal.v1'::text)),
    CONSTRAINT mood_revisions_appraisal_event_phase_check CHECK ((event_phase = ANY (ARRAY['anticipated'::text, 'ongoing'::text, 'realized'::text, 'averted'::text]))),
    CONSTRAINT mood_revisions_appraisal_gist_check CHECK (((data_rights_redacted_at IS NOT NULL) OR (((char_length(gist) >= 1) AND (char_length(gist) <= 64)) AND (gist = btrim(gist))))),
    CONSTRAINT mood_revisions_appraisal_importance_check CHECK ((((importance >= 5) AND (importance <= 100)) AND (((importance)::integer % 5) = 0))),
    CONSTRAINT mood_revisions_appraisal_mood_appraisal_event_id_check CHECK ((uuid_extract_version(mood_appraisal_event_id) = 7)),
    CONSTRAINT mood_revisions_appraisal_mood_episode_id_check CHECK ((uuid_extract_version(mood_episode_id) = 7)),
    CONSTRAINT mood_revisions_appraisal_semantic_version_check CHECK ((((data_rights_redacted_at IS NOT NULL) OR ((appraisal_payload ->> 'schema_version'::text) = 'armi.mood-appraisal.v3'::text AND appraisal_mapping_version = 'semantic-anchors.v1'::text AND (derived_appraisal_payload ->> 'schema_version'::text) = 'armi.mood-derived-appraisal.v3'::text AND derivation_version = 'cpm-fuzzy.v4'::text)))),
    CONSTRAINT mood_revisions_appraisal_transition_check CHECK ((transition = ANY (ARRAY['new'::text, 'reinforce'::text, 'reappraise'::text, 'resolve'::text]))),
    CONSTRAINT mood_revisions_appraisal_transition_shape_check CHECK ((((transition = 'new'::text) AND (previous_appraisal_event_id IS NULL)) OR ((transition <> 'new'::text) AND (previous_appraisal_event_id IS NOT NULL)))),
    CONSTRAINT mood_revisions_appraisal_shape_check CHECK ((mood_appraisal_event_id IS NULL AND mood_episode_id IS NULL AND previous_appraisal_event_id IS NULL AND transition IS NULL AND event_phase IS NULL AND gist IS NULL AND basis_ordinals IS NULL AND appraisal_payload IS NULL AND importance IS NULL AND derived_vad IS NULL AND affect_intensity IS NULL AND affect_half_life_seconds IS NULL AND derived_components IS NULL AND derivation_version IS NULL AND dynamics_version IS NULL AND occurred_at IS NULL AND appraisal_mapping_version IS NULL AND derived_appraisal_payload IS NULL AND data_rights_redacted_at IS NULL) OR (mood_appraisal_event_id IS NOT NULL AND mood_episode_id IS NOT NULL AND transition IS NOT NULL AND event_phase IS NOT NULL AND basis_ordinals IS NOT NULL AND importance IS NOT NULL AND derived_vad IS NOT NULL AND affect_intensity IS NOT NULL AND affect_half_life_seconds IS NOT NULL AND derived_components IS NOT NULL AND derivation_version IS NOT NULL AND dynamics_version IS NOT NULL AND occurred_at IS NOT NULL AND appraisal_mapping_version IS NOT NULL AND (data_rights_redacted_at IS NOT NULL OR (gist IS NOT NULL AND appraisal_payload IS NOT NULL AND derived_appraisal_payload IS NOT NULL)))),
    CONSTRAINT mood_revisions_id_check CHECK ((uuid_extract_version(mood_revision_id) = 7)),
    CONSTRAINT mood_revisions_mood_version_check CHECK ((mood_version > 0)),
    CONSTRAINT mood_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction'),
    CONSTRAINT mood_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (mood_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (mood_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL)) OR ((origin_kind = 'admin_correction'::text) AND (mood_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)))),
    CONSTRAINT mood_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text]))),
    CONSTRAINT mood_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
    CONSTRAINT mood_revisions_payload_check CHECK ((((semantic_payload ->> 'schema_version'::text) = 'armi.mood.v5'::text AND (semantic_payload ?& ARRAY['dynamics_version'::text, 'derivation_version'::text, 'home_base'::text, 'schema_version'::text]) AND (semantic_payload - ARRAY['dynamics_version'::text, 'derivation_version'::text, 'home_base'::text, 'schema_version'::text]) = '{}'::jsonb AND (semantic_payload ->> 'dynamics_version'::text) = 'recency-reappraisal.v1'::text AND (semantic_payload ->> 'derivation_version'::text) = 'cpm-fuzzy.v4'::text AND jsonb_typeof(semantic_payload -> 'home_base'::text) = 'object'::text AND (semantic_payload -> 'home_base'::text) ?& ARRAY['valence'::text, 'arousal'::text, 'dominance'::text] AND ((semantic_payload -> 'home_base'::text) - ARRAY['valence'::text, 'arousal'::text, 'dominance'::text]) = '{}'::jsonb AND (((semantic_payload -> 'home_base'::text) ->> 'valence'::text)::integer BETWEEN -100 AND 100) AND (((semantic_payload -> 'home_base'::text) ->> 'arousal'::text)::integer BETWEEN -100 AND 100) AND (((semantic_payload -> 'home_base'::text) ->> 'dominance'::text)::integer BETWEEN -100 AND 100)))),
    CONSTRAINT mood_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT mood_revisions_semantic_payload_check CHECK ((jsonb_typeof(semantic_payload) = 'object'::text))
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
    current_disposition text NOT NULL,
    available_after timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    expires_at timestamp(6) with time zone,
    selected_at timestamp(6) with time zone,
    root_opportunity_id uuid NOT NULL,
    predecessor_opportunity_id uuid,
    reconsideration_no smallint DEFAULT 0 NOT NULL,
    resolved_at timestamp(6) with time zone,
    resolution_reason_code text,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_version bigint NOT NULL,
    activity_id uuid,
    consideration_signals jsonb,
    CONSTRAINT opportunities_consideration_signals_check CHECK ((consideration_signals IS NULL) OR (
    jsonb_typeof(consideration_signals)='object'
    AND consideration_signals->>'schema_version'='armi.consideration-signals.v1'
    AND jsonb_typeof(consideration_signals->'signals')='array'
    AND consideration_signals ? 'frozen_at'
)),
    CONSTRAINT opportunities_current_disposition_check CHECK ((current_disposition = ANY (ARRAY['open'::text, 'selected'::text, 'resolved'::text, 'superseded'::text, 'cancelled'::text]))),
    CONSTRAINT opportunities_expiry_check CHECK (((expires_at IS NULL) OR (expires_at > available_after))),
    CONSTRAINT opportunities_lineage_check CHECK ((((reconsideration_no = 0) AND (root_opportunity_id = opportunity_id) AND (predecessor_opportunity_id IS NULL)) OR ((reconsideration_no > 0) AND (root_opportunity_id <> opportunity_id) AND (predecessor_opportunity_id IS NOT NULL)))),
    CONSTRAINT opportunities_opportunity_id_check CHECK ((uuid_extract_version(opportunity_id) = 7)),
    CONSTRAINT opportunities_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_creator_voice_input'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomy_check'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text, 'consider_visual_observation'::text, 'consider_requested_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text]))),
    CONSTRAINT opportunities_reconsideration_check CHECK (((reconsideration_no >= 0) AND ((reconsideration_no <= 1) OR ((purpose = 'consider_autonomous_life'::text) AND (source_kind = 'subject_available'::text))))),
    CONSTRAINT opportunities_resolution_state_check CHECK ((((current_disposition = 'open'::text) AND (selected_at IS NULL) AND (resolved_at IS NULL) AND (resolution_reason_code IS NULL)) OR ((current_disposition = 'selected'::text) AND (selected_at IS NOT NULL) AND (resolved_at IS NULL) AND (resolution_reason_code IS NULL)) OR ((current_disposition = ANY (ARRAY['resolved'::text, 'superseded'::text])) AND (selected_at IS NOT NULL) AND (resolved_at IS NOT NULL) AND (resolution_reason_code IS NOT NULL)) OR ((current_disposition = 'cancelled'::text) AND (resolved_at IS NOT NULL) AND (resolution_reason_code IS NOT NULL)))),
    CONSTRAINT opportunities_resolution_reason_check CHECK (((resolution_reason_code IS NULL) OR (resolution_reason_code ~ '^[A-Z][A-Z0-9-]{0,127}$'::text))),
    CONSTRAINT opportunities_source_kind_check CHECK ((source_kind = ANY (ARRAY['autonomy_plan'::text, 'external_evidence'::text, 'subject_available'::text, 'subject_component_revision'::text, 'activity_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text, 'life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_activity'::text, 'creator_outreach_relationship'::text]))),
    CONSTRAINT opportunities_source_shape_check CHECK (((source_kind = 'autonomy_plan' AND evidence_id IS NULL AND ((scene_id IS NULL) = (context_party_id IS NULL))) OR ((source_kind = 'external_evidence'::text) AND (evidence_id = source_ref) AND (activity_id IS NULL) AND (((purpose = 'consider_visual_observation'::text) AND (scene_id IS NULL) AND (context_party_id IS NULL)) OR ((purpose <> 'consider_visual_observation'::text) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL)))) OR ((source_kind = ANY (ARRAY['subject_available'::text, 'subject_component_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text])) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = 'activity_revision'::text) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NOT NULL)) OR ((source_kind = ANY (ARRAY['life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_relationship'::text])) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NULL)) OR ((source_kind = 'creator_outreach_activity'::text) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NOT NULL)))),
    CONSTRAINT opportunities_source_version_check CHECK ((source_version > 0))
);
