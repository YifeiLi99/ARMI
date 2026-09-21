-- Current Codex, audit and data-rights tables.

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
    CONSTRAINT audit_events_operation_check CHECK ((operation ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
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
-- Name: codex_task_sources; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.codex_task_sources (
    codex_task_source_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    task_manifest_artifact_id uuid NOT NULL,
    task_manifest_digest text NOT NULL,
    deadline_seconds integer NOT NULL,
    trace_id text NOT NULL,
    admitted_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    origin_subject_commit_id uuid,
    codex_verification_id uuid,
    evidence_id uuid,
    opportunity_id uuid,
    effect_id uuid,
    effect_attempt_id uuid,
    execution_status text,
    cleanup_status text,
    final_result_artifact_id uuid,
    execution_error_code text,
    cleanup_error_code text,
    completed_at timestamp(6) with time zone,
    CONSTRAINT codex_task_result_check CHECK ((execution_status <> 'verified'::text OR execution_error_code IS NULL)),
    CONSTRAINT codex_task_result_cleanup_error_code_check CHECK (((cleanup_error_code IS NULL) OR (cleanup_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_task_result_cleanup_status_check CHECK ((cleanup_status = ANY (ARRAY['clean'::text, 'failed'::text]))),
    CONSTRAINT codex_task_result_codex_verification_id_check CHECK ((uuid_extract_version(codex_verification_id) = 7)),
    CONSTRAINT codex_task_result_execution_error_code_check CHECK (((execution_error_code IS NULL) OR (execution_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_task_result_execution_status_check CHECK ((execution_status = ANY (ARRAY['verified'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT codex_task_result_shape_check CHECK (
        (codex_verification_id IS NULL AND evidence_id IS NULL AND opportunity_id IS NULL AND effect_id IS NULL AND effect_attempt_id IS NULL AND execution_status IS NULL AND cleanup_status IS NULL AND final_result_artifact_id IS NULL AND execution_error_code IS NULL AND cleanup_error_code IS NULL AND completed_at IS NULL)
        OR (codex_verification_id IS NOT NULL AND evidence_id IS NOT NULL AND opportunity_id IS NOT NULL AND effect_id IS NOT NULL AND effect_attempt_id IS NOT NULL AND execution_status IS NOT NULL AND cleanup_status IS NOT NULL AND final_result_artifact_id IS NOT NULL AND completed_at IS NOT NULL)
    ),
    CONSTRAINT codex_task_sources_codex_task_source_id_check CHECK ((uuid_extract_version(codex_task_source_id) = 7)),
    CONSTRAINT codex_task_sources_deadline_seconds_check CHECK (((deadline_seconds >= 60) AND (deadline_seconds <= 1800))),
    CONSTRAINT codex_task_sources_task_manifest_digest_check CHECK ((task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_task_sources_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);


--
-- Name: creator_exports; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.creator_exports (
    creator_export_id uuid NOT NULL,
    snapshot_party_scopes jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(snapshot_party_scopes)='object'),
    snapshot_contract_version text,
    snapshot_status text,
    snapshot_removed_at timestamp(6) with time zone,
    CONSTRAINT creator_exports_snapshot_check CHECK (
        (snapshot_contract_version IS NULL AND snapshot_status IS NULL AND snapshot_removed_at IS NULL)
        OR (snapshot_contract_version IS NOT NULL AND snapshot_status IS NOT NULL
            AND status IN ('completed','partial')
            AND ((snapshot_status='active' AND snapshot_removed_at IS NULL)
                OR (snapshot_status='removed' AND snapshot_removed_at IS NOT NULL)))
    ),
    creator_party_id uuid NOT NULL,
    directory_name text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    status text NOT NULL,
    destination_path text NOT NULL,
    segment_count integer DEFAULT 0 NOT NULL,
    record_count bigint DEFAULT 0 NOT NULL,
    artifact_count bigint DEFAULT 0 NOT NULL,
    missing_artifact_count bigint DEFAULT 0 NOT NULL,
    manifest_digest text,
    expected_segment_count integer,
    expected_record_count bigint,
    expected_artifact_count bigint,
    expected_missing_artifact_count bigint,
    error_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT creator_exports_artifact_count_check CHECK ((artifact_count >= 0)),
    CONSTRAINT creator_exports_check CHECK ((((status = ANY (ARRAY['building'::text, 'published_unsettled'::text, 'unknown'::text])) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['completed'::text, 'partial'::text, 'failed'::text])) AND (completed_at IS NOT NULL)))),
    CONSTRAINT creator_exports_creator_export_id_check CHECK ((uuid_extract_version(creator_export_id) = 7)),
    CONSTRAINT creator_exports_directory_name_check CHECK (((directory_name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'::text) AND (directory_name <> ALL (ARRAY['.'::text, '..'::text])))),
    CONSTRAINT creator_exports_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT creator_exports_missing_artifact_count_check CHECK ((missing_artifact_count >= 0)),
    CONSTRAINT creator_exports_manifest_digest_check CHECK (((manifest_digest IS NULL) OR (manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT creator_exports_expected_counts_check CHECK ((((expected_segment_count IS NULL) OR (expected_segment_count >= 0)) AND ((expected_record_count IS NULL) OR (expected_record_count >= 0)) AND ((expected_artifact_count IS NULL) OR (expected_artifact_count >= 0)) AND ((expected_missing_artifact_count IS NULL) OR (expected_missing_artifact_count >= 0)))),
    CONSTRAINT creator_exports_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_exports_record_count_check CHECK ((record_count >= 0)),
    CONSTRAINT creator_exports_status_check CHECK ((status = ANY (ARRAY['building'::text, 'published_unsettled'::text, 'completed'::text, 'partial'::text, 'failed'::text, 'unknown'::text]))),
    CONSTRAINT creator_exports_segment_count_check CHECK ((segment_count >= 0))
);



--
-- Name: data_rights_order_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.data_rights_order_items (
    deletion_item_id uuid NOT NULL,
    deletion_order_id uuid NOT NULL,
    target_kind text NOT NULL,
    target_ref uuid NOT NULL,
    required_action text NOT NULL,
    responsible_owner text NOT NULL,
    result_status text NOT NULL,
    retention_reason text,
    operator_action_required boolean DEFAULT false NOT NULL,
    artifact_object_deletion_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    CONSTRAINT data_rights_order_items_check CHECK ((((result_status = 'pending'::text) AND (completed_at IS NULL)) OR ((result_status <> 'pending'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT data_rights_order_items_deletion_item_id_check CHECK ((uuid_extract_version(deletion_item_id) = 7)),
    CONSTRAINT data_rights_order_items_artifact_deletion_check CHECK (((artifact_object_deletion_id IS NULL) OR ((target_kind = 'artifact'::text) AND (required_action = 'delete'::text)))),
    CONSTRAINT data_rights_order_items_retention_reason_check CHECK (((retention_reason IS NULL) OR (retention_reason = ANY (ARRAY['rights_enforcement'::text, 'shared_reference'::text, 'objective_history'::text, 'subject_continuity'::text, 'operator_managed_snapshot'::text])))),
    CONSTRAINT data_rights_order_items_required_action_check CHECK ((required_action = ANY (ARRAY['block'::text, 'restrict'::text, 'cancel'::text, 'redact'::text, 'tombstone'::text, 'delete'::text, 'retain'::text, 'operator_remove'::text]))),
    CONSTRAINT data_rights_order_items_result_status_check CHECK ((result_status = ANY (ARRAY['pending'::text, 'completed'::text, 'partial'::text, 'too_late'::text, 'unknown'::text]))),
    CONSTRAINT data_rights_order_items_target_kind_check CHECK ((target_kind = ANY (ARRAY['party'::text, 'external_binding'::text, 'scene'::text, 'interaction'::text, 'media_recognition'::text, 'live_voice'::text, 'live_vision'::text, 'evidence'::text, 'experience'::text, 'cognition'::text, 'memory'::text, 'relationship'::text, 'activity'::text, 'material'::text, 'subject_component'::text, 'mood'::text, 'prompt'::text, 'effect'::text, 'codex_task'::text, 'managed_snapshot'::text, 'artifact'::text]))),
    CONSTRAINT data_rights_order_items_target_ref_check CHECK ((uuid_extract_version(target_ref) = 7))
);

--
-- Name: data_rights_orders; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.data_rights_orders (
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
    CONSTRAINT data_rights_orders_check CHECK ((requester_party_id = scope_party_id)),
    CONSTRAINT data_rights_orders_check1 CHECK ((((order_kind = 'stop_contact'::text) AND (scope_kind = 'party_contact'::text)) OR ((order_kind = ANY (ARRAY['stop_use'::text, 'delete_related'::text])) AND (scope_kind = 'party_local_data'::text)))),
    CONSTRAINT data_rights_orders_check3 CHECK ((((execution_status = ANY (ARRAY['pending'::text, 'executing'::text])) AND (completed_at IS NULL)) OR ((execution_status = ANY (ARRAY['completed'::text, 'partial'::text])) AND (completed_at IS NOT NULL)))),
    CONSTRAINT data_rights_orders_deletion_order_id_check CHECK ((uuid_extract_version(deletion_order_id) = 7)),
    CONSTRAINT data_rights_orders_execution_status_check CHECK ((execution_status = ANY (ARRAY['pending'::text, 'executing'::text, 'completed'::text, 'partial'::text]))),
    CONSTRAINT data_rights_orders_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT data_rights_orders_order_kind_check CHECK ((order_kind = ANY (ARRAY['stop_contact'::text, 'stop_use'::text, 'delete_related'::text]))),
    CONSTRAINT data_rights_orders_reason_code_check CHECK ((reason_code = 'requester_exercised_local_right'::text)),
    CONSTRAINT data_rights_orders_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT data_rights_orders_requester_kind_check CHECK ((requester_kind = ANY (ARRAY['creator'::text, 'other_human'::text]))),
    CONSTRAINT data_rights_orders_scope_kind_check CHECK ((scope_kind = ANY (ARRAY['party_contact'::text, 'party_local_data'::text]))),
    CONSTRAINT data_rights_orders_status_check CHECK ((status = 'effective'::text)),
    CONSTRAINT data_rights_orders_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);

-- Append-only explicit retry cycles for blocked local deletion work.
CREATE TABLE armi.data_rights_order_retry_attempts (
    deletion_order_retry_attempt_id uuid NOT NULL,
    deletion_order_id uuid NOT NULL,
    retry_cycle integer NOT NULL,
    idempotency_key text NOT NULL,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT data_rights_order_retry_attempts_id_check CHECK ((uuid_extract_version(deletion_order_retry_attempt_id) = 7)),
    CONSTRAINT data_rights_order_retry_attempts_cycle_check CHECK ((retry_cycle >= 2)),
    CONSTRAINT data_rights_order_retry_attempts_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT data_rights_order_retry_attempts_trace_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);
