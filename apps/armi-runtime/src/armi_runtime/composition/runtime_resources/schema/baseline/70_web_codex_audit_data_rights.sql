--
-- Name: audit_events; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.audit_events (
    audit_event_id uuid NOT NULL,
    actor_kind text NOT NULL,
    actor_ref uuid NOT NULL,
    purpose text NOT NULL,
    operation text NOT NULL,
    target_kind text NOT NULL,
    target_ref uuid NOT NULL,
    result_status text NOT NULL,
    trace_id text NOT NULL,
    sensitivity text NOT NULL,
    subject_id uuid,
    request_kind text,
    request_ref uuid,
    before_version bigint,
    after_version bigint,
    policy_ref uuid,
    grant_ref uuid,
    error_category text,
    occurred_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT audit_events_actor_kind_check CHECK ((actor_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_actor_ref_check CHECK ((uuid_extract_version(actor_ref) = 7)),
    CONSTRAINT audit_events_after_version_check CHECK ((after_version >= 0)),
    CONSTRAINT audit_events_audit_event_id_check CHECK ((uuid_extract_version(audit_event_id) = 7)),
    CONSTRAINT audit_events_before_version_check CHECK ((before_version >= 0)),
    CONSTRAINT audit_events_check CHECK (((request_kind IS NULL) = (request_ref IS NULL))),
    CONSTRAINT audit_events_check1 CHECK (((before_version IS NULL) = (after_version IS NULL))),
    CONSTRAINT audit_events_check2 CHECK (((before_version IS NULL) OR (after_version > before_version))),
    CONSTRAINT audit_events_error_category_check CHECK (((error_category IS NULL) OR (error_category = ANY (ARRAY['input'::text, 'auth'::text, 'scope'::text, 'state'::text, 'conflict'::text, 'idempotency'::text, 'policy'::text, 'capability'::text, 'dependency'::text, 'effect'::text, 'integrity'::text, 'admin'::text, 'internal'::text])))),
    CONSTRAINT audit_events_grant_ref_check CHECK (((grant_ref IS NULL) OR (uuid_extract_version(grant_ref) = 7))),
    CONSTRAINT audit_events_operation_check CHECK ((operation ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_policy_ref_check CHECK (((policy_ref IS NULL) OR (uuid_extract_version(policy_ref) = 7))),
    CONSTRAINT audit_events_purpose_check CHECK ((purpose ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_request_kind_check CHECK (((request_kind IS NULL) OR (request_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text))),
    CONSTRAINT audit_events_request_ref_check CHECK (((request_ref IS NULL) OR (uuid_extract_version(request_ref) = 7))),
    CONSTRAINT audit_events_result_status_check CHECK ((result_status = ANY (ARRAY['accepted'::text, 'applied'::text, 'waiting'::text, 'rejected'::text, 'unavailable'::text, 'failed'::text, 'unknown'::text, 'completed'::text]))),
    CONSTRAINT audit_events_sensitivity_check CHECK ((sensitivity = ANY (ARRAY['internal'::text, 'private'::text, 'restricted'::text]))),
    CONSTRAINT audit_events_subject_id_check CHECK (((subject_id IS NULL) OR (uuid_extract_version(subject_id) = 7))),
    CONSTRAINT audit_events_target_kind_check CHECK ((target_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_target_ref_check CHECK ((uuid_extract_version(target_ref) = 7)),
    CONSTRAINT audit_events_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);

--
-- Name: codex_result_sources; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.codex_result_sources (
    codex_result_source_id uuid NOT NULL,
    codex_verification_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    result_kind text NOT NULL,
    evidence_artifact_id uuid NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT codex_result_sources_codex_result_source_id_check CHECK ((uuid_extract_version(codex_result_source_id) = 7)),
    CONSTRAINT codex_result_sources_result_kind_check CHECK ((result_kind = ANY (ARRAY['verified_completion'::text, 'execution_failure'::text, 'outcome_unknown'::text, 'cancelled'::text])))
);

--
-- Name: codex_task_sources; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.codex_task_sources (
    codex_task_source_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    source_bundle_artifact_id uuid NOT NULL,
    source_bundle_digest text NOT NULL,
    source_tree_digest text NOT NULL,
    task_manifest_artifact_id uuid NOT NULL,
    task_manifest_digest text NOT NULL,
    validator_id text NOT NULL,
    deadline_seconds integer NOT NULL,
    trace_id text NOT NULL,
    admitted_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT codex_task_sources_codex_task_source_id_check CHECK ((uuid_extract_version(codex_task_source_id) = 7)),
    CONSTRAINT codex_task_sources_deadline_seconds_check CHECK (((deadline_seconds >= 60) AND (deadline_seconds <= 1800))),
    CONSTRAINT codex_task_sources_source_bundle_digest_check CHECK ((source_bundle_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_task_sources_source_tree_digest_check CHECK ((source_tree_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_task_sources_task_manifest_digest_check CHECK ((task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_task_sources_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT codex_task_sources_validator_id_check CHECK ((validator_id ~ '^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$'::text))
);

--
-- Name: codex_verification_results; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.codex_verification_results (
    codex_verification_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    effect_attempt_id uuid NOT NULL,
    execution_status text NOT NULL,
    cleanup_status text NOT NULL,
    source_tree_digest text NOT NULL,
    final_tree_digest text,
    patch_digest text,
    event_transcript_artifact_id uuid,
    final_result_artifact_id uuid,
    patch_artifact_id uuid,
    result_bundle_artifact_id uuid,
    diagnostics_artifact_id uuid,
    validation_report_artifact_id uuid,
    changed_path_count integer NOT NULL,
    execution_error_code text,
    cleanup_error_code text,
    completed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT codex_verification_results_changed_path_count_check CHECK (((changed_path_count >= 0) AND (changed_path_count <= 500))),
    CONSTRAINT codex_verification_results_check CHECK ((((execution_status = 'verified'::text) AND (cleanup_status = 'clean'::text) AND (final_tree_digest IS NOT NULL) AND (patch_digest IS NOT NULL) AND (final_result_artifact_id IS NOT NULL) AND (patch_artifact_id IS NOT NULL) AND (result_bundle_artifact_id IS NOT NULL) AND (validation_report_artifact_id IS NOT NULL) AND (execution_error_code IS NULL) AND (cleanup_error_code IS NULL)) OR (execution_status <> 'verified'::text))),
    CONSTRAINT codex_verification_results_cleanup_error_code_check CHECK (((cleanup_error_code IS NULL) OR (cleanup_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_verification_results_cleanup_status_check CHECK ((cleanup_status = ANY (ARRAY['clean'::text, 'failed'::text]))),
    CONSTRAINT codex_verification_results_codex_verification_id_check CHECK ((uuid_extract_version(codex_verification_id) = 7)),
    CONSTRAINT codex_verification_results_execution_error_code_check CHECK (((execution_error_code IS NULL) OR (execution_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_verification_results_execution_status_check CHECK ((execution_status = ANY (ARRAY['verified'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT codex_verification_results_final_tree_digest_check CHECK (((final_tree_digest IS NULL) OR (final_tree_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT codex_verification_results_patch_digest_check CHECK (((patch_digest IS NULL) OR (patch_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT codex_verification_results_source_tree_digest_check CHECK ((source_tree_digest ~ '^sha256:[0-9a-f]{64}$'::text))
);

--
-- Name: creator_exports; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.creator_exports (
    creator_export_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    directory_name text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    status text NOT NULL,
    destination_path text NOT NULL,
    table_count integer DEFAULT 0 NOT NULL,
    row_count bigint DEFAULT 0 NOT NULL,
    artifact_count bigint DEFAULT 0 NOT NULL,
    missing_artifacts jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT creator_exports_artifact_count_check CHECK ((artifact_count >= 0)),
    CONSTRAINT creator_exports_check CHECK ((((status = 'running'::text) AND (completed_at IS NULL)) OR ((status <> 'running'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT creator_exports_creator_export_id_check CHECK ((uuid_extract_version(creator_export_id) = 7)),
    CONSTRAINT creator_exports_directory_name_check CHECK (((directory_name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'::text) AND (directory_name <> ALL (ARRAY['.'::text, '..'::text])))),
    CONSTRAINT creator_exports_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT creator_exports_missing_artifacts_check CHECK ((jsonb_typeof(missing_artifacts) = 'array'::text)),
    CONSTRAINT creator_exports_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_exports_row_count_check CHECK ((row_count >= 0)),
    CONSTRAINT creator_exports_status_check CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'partial'::text, 'failed'::text]))),
    CONSTRAINT creator_exports_table_count_check CHECK ((table_count >= 0))
);

--
-- Name: deletion_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.deletion_items (
    deletion_item_id uuid NOT NULL,
    deletion_order_id uuid NOT NULL,
    target_kind text NOT NULL,
    target_ref uuid NOT NULL,
    required_action text NOT NULL,
    result_status text NOT NULL,
    remaining_location text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT deletion_items_check CHECK ((((result_status = 'pending'::text) AND (completed_at IS NULL)) OR ((result_status <> 'pending'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT deletion_items_deletion_item_id_check CHECK ((uuid_extract_version(deletion_item_id) = 7)),
    CONSTRAINT deletion_items_remaining_location_check CHECK (((remaining_location IS NULL) OR (remaining_location = ANY (ARRAY['shared_local_reference'::text, 'objective_history'::text, 'local_artifact_store'::text])))),
    CONSTRAINT deletion_items_required_action_check CHECK ((required_action = ANY (ARRAY['delete'::text, 'tombstone'::text, 'retain'::text]))),
    CONSTRAINT deletion_items_result_status_check CHECK ((result_status = ANY (ARRAY['pending'::text, 'completed'::text, 'partial'::text, 'too_late'::text, 'unknown'::text]))),
    CONSTRAINT deletion_items_target_kind_check CHECK ((target_kind = ANY (ARRAY['interaction'::text, 'evidence'::text, 'experience'::text, 'memory'::text, 'relationship'::text, 'scene'::text, 'artifact'::text, 'effect'::text]))),
    CONSTRAINT deletion_items_target_ref_check CHECK ((uuid_extract_version(target_ref) = 7))
);

--
-- Name: deletion_orders; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.deletion_orders (
    deletion_order_id uuid NOT NULL,
    requester_party_id uuid NOT NULL,
    requester_kind text NOT NULL,
    order_kind text NOT NULL,
    scope_kind text NOT NULL,
    scope_party_id uuid NOT NULL,
    reason_code text NOT NULL,
    status text NOT NULL,
    execution_status text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    trace_id text NOT NULL,
    effective_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT deletion_orders_check CHECK ((requester_party_id = scope_party_id)),
    CONSTRAINT deletion_orders_check1 CHECK ((((order_kind = 'stop_contact'::text) AND (scope_kind = 'party_contact'::text)) OR ((order_kind = ANY (ARRAY['stop_use'::text, 'delete_related'::text])) AND (scope_kind = 'party_local_data'::text)))),
    CONSTRAINT deletion_orders_check2 CHECK ((((order_kind = 'delete_related'::text) AND (execution_status = ANY (ARRAY['pending'::text, 'executing'::text, 'completed'::text, 'partial'::text]))) OR ((order_kind <> 'delete_related'::text) AND (execution_status = 'not_required'::text)))),
    CONSTRAINT deletion_orders_check3 CHECK ((((execution_status = ANY (ARRAY['not_required'::text, 'pending'::text, 'executing'::text])) AND (completed_at IS NULL)) OR ((execution_status = ANY (ARRAY['completed'::text, 'partial'::text])) AND (completed_at IS NOT NULL)))),
    CONSTRAINT deletion_orders_deletion_order_id_check CHECK ((uuid_extract_version(deletion_order_id) = 7)),
    CONSTRAINT deletion_orders_execution_status_check CHECK ((execution_status = ANY (ARRAY['not_required'::text, 'pending'::text, 'executing'::text, 'completed'::text, 'partial'::text]))),
    CONSTRAINT deletion_orders_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT deletion_orders_order_kind_check CHECK ((order_kind = ANY (ARRAY['stop_contact'::text, 'stop_use'::text, 'delete_related'::text]))),
    CONSTRAINT deletion_orders_reason_code_check CHECK ((reason_code = 'requester_exercised_local_right'::text)),
    CONSTRAINT deletion_orders_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT deletion_orders_requester_kind_check CHECK ((requester_kind = ANY (ARRAY['creator'::text, 'other_human'::text]))),
    CONSTRAINT deletion_orders_scope_kind_check CHECK ((scope_kind = ANY (ARRAY['party_contact'::text, 'party_local_data'::text]))),
    CONSTRAINT deletion_orders_status_check CHECK ((status = 'effective'::text)),
    CONSTRAINT deletion_orders_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);

--
-- Name: observation_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.observation_attempts (
    observation_attempt_id uuid NOT NULL,
    web_observation_request_id uuid NOT NULL,
    work_id uuid NOT NULL,
    work_attempt_id uuid NOT NULL,
    work_lease_token bigint NOT NULL,
    attempt_no smallint NOT NULL,
    binding_id text NOT NULL,
    credential_identity text NOT NULL,
    dispatch_state text NOT NULL,
    provider_model_id text,
    result_artifact_id uuid,
    input_tokens integer,
    output_tokens integer,
    web_search_calls smallint,
    citation_count smallint,
    estimated_cost_microyuan bigint,
    result_status text,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT observation_attempts_attempt_no_check CHECK ((attempt_no >= 1)),
    CONSTRAINT observation_attempts_binding_id_check CHECK ((binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'::text)),
    CONSTRAINT observation_attempts_check CHECK ((((dispatch_state = 'prepared'::text) AND (result_status IS NULL) AND (provider_model_id IS NULL) AND (result_artifact_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (web_search_calls IS NULL) AND (citation_count IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL) AND (dispatched_at IS NULL) AND (settled_at IS NULL)) OR ((dispatch_state = 'dispatched'::text) AND (result_status IS NULL) AND (provider_model_id IS NULL) AND (result_artifact_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (web_search_calls IS NULL) AND (citation_count IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status = 'cancelled'::text) AND (settled_at IS NOT NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'outcome_unknown'::text])) AND (dispatched_at IS NOT NULL) AND (settled_at IS NOT NULL)))),
    CONSTRAINT observation_attempts_check1 CHECK ((((result_status = 'succeeded'::text) AND (provider_model_id IS NOT NULL) AND (result_artifact_id IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (web_search_calls IS NOT NULL) AND (citation_count IS NOT NULL) AND (estimated_cost_microyuan IS NOT NULL) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'outcome_unknown'::text])) AND (error_code IS NOT NULL) AND (result_artifact_id IS NULL)) OR (result_status IS NULL) OR ((result_status = 'cancelled'::text) AND (result_artifact_id IS NULL)))),
    CONSTRAINT observation_attempts_citation_count_check CHECK (((citation_count IS NULL) OR ((citation_count >= 1) AND (citation_count <= 128)))),
    CONSTRAINT observation_attempts_credential_identity_check CHECK ((credential_identity ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT observation_attempts_dispatch_state_check CHECK ((dispatch_state = ANY (ARRAY['prepared'::text, 'dispatched'::text, 'settled'::text]))),
    CONSTRAINT observation_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^WEB-[A-Z0-9-]+$'::text))),
    CONSTRAINT observation_attempts_estimated_cost_microyuan_check CHECK (((estimated_cost_microyuan IS NULL) OR ((estimated_cost_microyuan >= 0) AND (estimated_cost_microyuan <= 1000000)))),
    CONSTRAINT observation_attempts_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens > 0))),
    CONSTRAINT observation_attempts_observation_attempt_id_check CHECK ((uuid_extract_version(observation_attempt_id) = 7)),
    CONSTRAINT observation_attempts_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens > 0))),
    CONSTRAINT observation_attempts_provider_model_id_check CHECK (((provider_model_id IS NULL) OR (provider_model_id ~ '^doubao-seed-evolving[a-z0-9-]*$'::text))),
    CONSTRAINT observation_attempts_result_status_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'outcome_unknown'::text, 'cancelled'::text])))),
    CONSTRAINT observation_attempts_web_search_calls_check CHECK (((web_search_calls IS NULL) OR ((web_search_calls >= 1) AND (web_search_calls <= 8)))),
    CONSTRAINT observation_attempts_work_attempt_id_check CHECK ((uuid_extract_version(work_attempt_id) = 7)),
    CONSTRAINT observation_attempts_work_lease_token_check CHECK ((work_lease_token > 0))
);

--
-- Name: observation_tool_calls; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.observation_tool_calls (
    observation_tool_call_id uuid NOT NULL,
    observation_attempt_id uuid NOT NULL,
    call_no smallint NOT NULL,
    action_type text NOT NULL,
    completion_status text NOT NULL,
    CONSTRAINT observation_tool_calls_action_type_check CHECK ((action_type = ANY (ARRAY['search'::text, 'open_page'::text, 'find_in_page'::text]))),
    CONSTRAINT observation_tool_calls_call_no_check CHECK (((call_no >= 1) AND (call_no <= 8))),
    CONSTRAINT observation_tool_calls_completion_status_check CHECK ((completion_status = 'completed'::text)),
    CONSTRAINT observation_tool_calls_observation_tool_call_id_check CHECK ((uuid_extract_version(observation_tool_call_id) = 7))
);

--
-- Name: web_evidence_sources; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.web_evidence_sources (
    web_evidence_source_id uuid NOT NULL,
    evidence_id uuid NOT NULL,
    observation_attempt_id uuid NOT NULL,
    citation_no smallint NOT NULL,
    source_artifact_id uuid NOT NULL,
    canonical_url_digest text NOT NULL,
    acquisition_kind text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT web_evidence_sources_acquisition_kind_check CHECK ((acquisition_kind = 'provider_synthesis_citation'::text)),
    CONSTRAINT web_evidence_sources_canonical_url_digest_check CHECK ((canonical_url_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_evidence_sources_citation_no_check CHECK (((citation_no >= 1) AND (citation_no <= 128))),
    CONSTRAINT web_evidence_sources_web_evidence_source_id_check CHECK ((uuid_extract_version(web_evidence_source_id) = 7))
);

--
-- Name: web_observation_requests; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.web_observation_requests (
    web_observation_request_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    runtime_instance_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    idempotency_key text NOT NULL,
    purpose text NOT NULL,
    operation_class text NOT NULL,
    request_artifact_id uuid NOT NULL,
    request_digest text NOT NULL,
    binding_id text NOT NULL,
    work_id uuid NOT NULL,
    deadline_at timestamp(6) with time zone NOT NULL,
    max_cost_microyuan bigint DEFAULT 1000000 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    result_artifact_id uuid,
    last_error_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    web_research_intent_id uuid,
    CONSTRAINT web_observation_requests_binding_id_check CHECK ((binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'::text)),
    CONSTRAINT web_observation_requests_check CHECK ((deadline_at > created_at)),
    CONSTRAINT web_observation_requests_check1 CHECK ((((status = ANY (ARRAY['pending'::text, 'running'::text])) AND (result_artifact_id IS NULL) AND (last_error_code IS NULL) AND (completed_at IS NULL)) OR ((status = 'succeeded'::text) AND (result_artifact_id IS NOT NULL) AND (last_error_code IS NULL) AND (completed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (result_artifact_id IS NULL) AND (last_error_code IS NOT NULL) AND (completed_at IS NOT NULL)) OR ((status = 'cancelled'::text) AND (result_artifact_id IS NULL) AND (completed_at IS NOT NULL)))),
    CONSTRAINT web_observation_requests_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT web_observation_requests_idempotency_key_check CHECK (((octet_length(idempotency_key) >= 1) AND (octet_length(idempotency_key) <= 128) AND (idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT web_observation_requests_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^WEB-[A-Z0-9-]+$'::text))),
    CONSTRAINT web_observation_requests_max_cost_microyuan_check CHECK ((max_cost_microyuan = 1000000)),
    CONSTRAINT web_observation_requests_operation_class_check CHECK ((operation_class = 'search_read_public'::text)),
    CONSTRAINT web_observation_requests_purpose_check CHECK ((purpose = 'public_web_research'::text)),
    CONSTRAINT web_observation_requests_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_observation_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT web_observation_requests_web_observation_request_id_check CHECK ((uuid_extract_version(web_observation_request_id) = 7))
);

--
-- Name: web_research_intents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.web_research_intents (
    web_research_intent_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    source_opportunity_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    purpose text NOT NULL,
    operation_class text NOT NULL,
    query_artifact_id uuid NOT NULL,
    query_digest text NOT NULL,
    idempotency_key text NOT NULL,
    admission_work_id uuid NOT NULL,
    web_observation_request_id uuid,
    status text NOT NULL,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT web_research_intents_check CHECK ((((status = 'pending'::text) AND (web_observation_request_id IS NULL) AND (completed_at IS NULL)) OR ((status = 'admitted'::text) AND (web_observation_request_id IS NOT NULL) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'unknown'::text, 'cancelled'::text])) AND (web_observation_request_id IS NOT NULL) AND (completed_at IS NOT NULL)) OR ((status = 'failed'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT web_research_intents_idempotency_key_check CHECK (((octet_length(idempotency_key) >= 1) AND (octet_length(idempotency_key) <= 128) AND (idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT web_research_intents_operation_class_check CHECK ((operation_class = 'search_read_public'::text)),
    CONSTRAINT web_research_intents_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT web_research_intents_purpose_check CHECK ((purpose = 'public_web_research'::text)),
    CONSTRAINT web_research_intents_query_digest_check CHECK ((query_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_research_intents_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'admitted'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT web_research_intents_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT web_research_intents_web_research_intent_id_check CHECK ((uuid_extract_version(web_research_intent_id) = 7))
);
