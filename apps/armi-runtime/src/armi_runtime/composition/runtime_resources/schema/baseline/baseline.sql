--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4 (Debian 18.4-1.pgdg13+1)
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: armi; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA armi;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accepted_experiences; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.accepted_experiences (
    experience_id uuid NOT NULL,
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
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT accepted_experiences_experience_id_check CHECK ((uuid_extract_version(experience_id) = 7)),
    CONSTRAINT accepted_experiences_experience_kind_check CHECK ((experience_kind = ANY (ARRAY['creator_input'::text, 'web_observation'::text, 'codex_observation'::text]))),
    CONSTRAINT accepted_experiences_fact_class_check CHECK ((fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT accepted_experiences_first_person_gist_check CHECK (((length(first_person_gist) >= 1) AND (length(first_person_gist) <= 1024))),
    CONSTRAINT accepted_experiences_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT accepted_experiences_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT accepted_experiences_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT accepted_experiences_source_pair_check CHECK ((((experience_kind = 'creator_input'::text) AND (source_perspective = 'creator_claim'::text)) OR ((experience_kind = 'web_observation'::text) AND (source_perspective = 'web_claim'::text)) OR ((experience_kind = 'codex_observation'::text) AND (source_perspective = 'codex_observation'::text)))),
    CONSTRAINT accepted_experiences_source_perspective_check CHECK ((source_perspective = ANY (ARRAY['creator_claim'::text, 'web_claim'::text, 'codex_observation'::text]))),
    CONSTRAINT accepted_experiences_uncertainty_check CHECK (((uncertainty IS NULL) OR ((length(uncertainty) >= 1) AND (length(uncertainty) <= 512))))
);


--
-- Name: action_intent_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.action_intent_revisions (
    action_intent_revision_id uuid NOT NULL,
    action_intent_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    response_artifact_id uuid,
    response_digest text,
    response_bytes integer,
    media_type text,
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    subject_commit_id uuid NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    codex_task_source_id uuid,
    task_manifest_digest text,
    validator_id text,
    CONSTRAINT action_intent_revisions_action_intent_revision_id_check CHECK ((uuid_extract_version(action_intent_revision_id) = 7)),
    CONSTRAINT action_intent_revisions_kind_check CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (purpose = 'respond_to_creator'::text) AND (response_artifact_id IS NOT NULL) AND (response_digest ~ '^sha256:[0-9a-f]{64}$'::text) AND ((response_bytes >= 1) AND (response_bytes <= 65536)) AND (media_type = 'text/plain'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL) AND (validator_id IS NULL)) OR ((capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (purpose = 'delegate_codex_work'::text) AND (response_artifact_id IS NULL) AND (response_digest IS NULL) AND (response_bytes IS NULL) AND (media_type IS NULL) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (codex_task_source_id IS NOT NULL) AND (task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text) AND (validator_id IS NOT NULL)))),
    CONSTRAINT action_intent_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT action_intent_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT action_intent_revisions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT action_intent_revisions_task_manifest_digest_check CHECK (((task_manifest_digest IS NULL) OR (task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT action_intent_revisions_validator_id_check CHECK (((validator_id IS NULL) OR (validator_id ~ '^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$'::text)))
);


--
-- Name: action_intents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.action_intents (
    action_intent_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    root_opportunity_id uuid NOT NULL,
    purpose text NOT NULL,
    current_revision_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    action_kind text DEFAULT 'creator_response'::text NOT NULL,
    CONSTRAINT action_intents_action_intent_id_check CHECK ((uuid_extract_version(action_intent_id) = 7)),
    CONSTRAINT action_intents_action_kind_check CHECK ((action_kind = ANY (ARRAY['creator_response'::text, 'codex_delegation'::text]))),
    CONSTRAINT action_intents_purpose_check CHECK ((((action_kind = 'creator_response'::text) AND (purpose = 'respond_to_creator'::text)) OR ((action_kind = 'codex_delegation'::text) AND (purpose = 'delegate_codex_work'::text)))),
    CONSTRAINT action_intents_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: activities; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activities (
    activity_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    activity_kind text NOT NULL,
    origin_opportunity_id uuid NOT NULL,
    current_revision_id uuid,
    head_version bigint DEFAULT 0 NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT activities_activity_id_check CHECK ((uuid_extract_version(activity_id) = 7)),
    CONSTRAINT activities_activity_kind_check CHECK ((activity_kind = 'self_directed'::text)),
    CONSTRAINT activities_current_revision_state_check CHECK ((((head_version = 0) AND (current_revision_id IS NULL)) OR ((head_version > 0) AND (current_revision_id IS NOT NULL)))),
    CONSTRAINT activities_head_version_check CHECK ((head_version >= 0)),
    CONSTRAINT activities_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT activities_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: activity_attention_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activity_attention_decisions (
    attention_decision_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    expected_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL,
    resource_snapshot_digest text NOT NULL,
    decision_kind text NOT NULL,
    result_revision_id uuid,
    review_not_before timestamp(6) with time zone,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT activity_attention_decisions_attention_decision_id_check CHECK ((uuid_extract_version(attention_decision_id) = 7)),
    CONSTRAINT activity_attention_decisions_check CHECK ((((decision_kind = ANY (ARRAY['engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text])) AND (result_revision_id IS NOT NULL)) OR ((decision_kind = ANY (ARRAY['no_action'::text, 'defer'::text, 'need_information'::text])) AND (result_revision_id IS NULL)))),
    CONSTRAINT activity_attention_decisions_check1 CHECK (((decision_kind = 'defer'::text) = (review_not_before IS NOT NULL))),
    CONSTRAINT activity_attention_decisions_decision_kind_check CHECK ((decision_kind = ANY (ARRAY['engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text, 'no_action'::text, 'defer'::text, 'need_information'::text]))),
    CONSTRAINT activity_attention_decisions_expected_head_version_check CHECK ((expected_head_version > 0)),
    CONSTRAINT activity_attention_decisions_resource_snapshot_digest_check CHECK ((resource_snapshot_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT activity_attention_decisions_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: activity_internal_work_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activity_internal_work_decisions (
    work_decision_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid CONSTRAINT activity_internal_work_decisio_candidate_validation_id_not_null NOT NULL,
    candidate_application_id uuid CONSTRAINT activity_internal_work_decisi_candidate_application_id_not_null NOT NULL,
    activity_id uuid NOT NULL,
    expected_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL,
    resource_snapshot_digest text CONSTRAINT activity_internal_work_decisi_resource_snapshot_digest_not_null NOT NULL,
    outcome_kind text NOT NULL,
    result_revision_id uuid NOT NULL,
    output_material_id uuid,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT activity_internal_work_decisions_check CHECK (((output_material_id IS NULL) OR (outcome_kind = ANY (ARRAY['progress'::text, 'complete'::text])))),
    CONSTRAINT activity_internal_work_decisions_expected_head_version_check CHECK ((expected_head_version > 0)),
    CONSTRAINT activity_internal_work_decisions_outcome_kind_check CHECK ((outcome_kind = ANY (ARRAY['progress'::text, 'complete'::text, 'need_information'::text, 'abandon'::text, 'no_result'::text]))),
    CONSTRAINT activity_internal_work_decisions_resource_snapshot_digest_check CHECK ((resource_snapshot_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT activity_internal_work_decisions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT activity_internal_work_decisions_work_decision_id_check CHECK ((uuid_extract_version(work_decision_id) = 7))
);


--
-- Name: activity_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activity_revisions (
    activity_revision_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    goal text NOT NULL,
    progress_summary text,
    waiting_condition text,
    resumption_cue text,
    next_safe_step text,
    status text NOT NULL,
    terminal_reason text,
    related_scene_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    transition_kind text NOT NULL,
    waiting_condition_kind text,
    resume_not_before timestamp(6) with time zone,
    CONSTRAINT activity_revisions_activity_revision_id_check CHECK ((uuid_extract_version(activity_revision_id) = 7)),
    CONSTRAINT activity_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT activity_revisions_check1 CHECK (((status = ANY (ARRAY['completed'::text, 'abandoned'::text, 'failed'::text])) = (terminal_reason IS NOT NULL))),
    CONSTRAINT activity_revisions_goal_check CHECK (((octet_length(goal) >= 1) AND (octet_length(goal) <= 8192))),
    CONSTRAINT activity_revisions_next_safe_step_check CHECK (((octet_length(next_safe_step) >= 1) AND (octet_length(next_safe_step) <= 4096))),
    CONSTRAINT activity_revisions_payload_shape_check CHECK ((((status = ANY (ARRAY['completed'::text, 'abandoned'::text, 'failed'::text])) AND (terminal_reason IS NOT NULL) AND (next_safe_step IS NULL) AND (waiting_condition IS NULL) AND (waiting_condition_kind IS NULL) AND (resumption_cue IS NULL) AND (resume_not_before IS NULL)) OR ((status = ANY (ARRAY['ready'::text, 'in_progress'::text, 'resuming'::text])) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NULL) AND (waiting_condition_kind IS NULL) AND (resumption_cue IS NULL) AND (resume_not_before IS NULL)) OR ((status = 'waiting'::text) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NOT NULL) AND (waiting_condition_kind = ANY (ARRAY['time'::text, 'creator_input'::text, 'external_evidence'::text])) AND (resumption_cue IS NOT NULL) AND ((waiting_condition_kind = 'time'::text) = (resume_not_before IS NOT NULL))) OR ((status = 'paused'::text) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NOT NULL) AND (waiting_condition_kind = 'scheduled_review'::text) AND (resumption_cue IS NOT NULL) AND (resume_not_before IS NOT NULL)))),
    CONSTRAINT activity_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT activity_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT activity_revisions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT activity_revisions_status_check CHECK ((status = ANY (ARRAY['considering'::text, 'ready'::text, 'in_progress'::text, 'waiting'::text, 'paused'::text, 'resuming'::text, 'completed'::text, 'abandoned'::text, 'failed'::text]))),
    CONSTRAINT activity_revisions_transition_kind_check CHECK ((transition_kind = ANY (ARRAY['created'::text, 'engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text, 'system_fail'::text]))),
    CONSTRAINT activity_revisions_transition_state_check CHECK ((((transition_kind = 'created'::text) AND (revision_no = 1) AND (status = 'ready'::text)) OR ((transition_kind = 'engage'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'progress'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'wait'::text) AND (status = 'waiting'::text)) OR ((transition_kind = 'pause'::text) AND (status = 'paused'::text)) OR ((transition_kind = 'resume'::text) AND (status = 'resuming'::text)) OR ((transition_kind = 'complete'::text) AND (status = 'completed'::text)) OR ((transition_kind = 'abandon'::text) AND (status = 'abandoned'::text)) OR ((transition_kind = 'system_fail'::text) AND (status = 'failed'::text)))),
    CONSTRAINT activity_revisions_waiting_kind_check CHECK (((waiting_condition_kind IS NULL) OR (waiting_condition_kind = ANY (ARRAY['time'::text, 'creator_input'::text, 'external_evidence'::text, 'scheduled_review'::text]))))
);


--
-- Name: artifacts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.artifacts (
    artifact_id uuid NOT NULL,
    content_digest text NOT NULL,
    media_type text NOT NULL,
    byte_size bigint NOT NULL,
    storage_locator text NOT NULL,
    logical_kind text NOT NULL,
    producer_kind text NOT NULL,
    producer_trace_id text NOT NULL,
    privacy_scope text NOT NULL,
    integrity_status text DEFAULT 'verified'::text NOT NULL,
    retention_status text DEFAULT 'retained'::text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    deleted_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT artifacts_artifact_id_check CHECK ((uuid_extract_version(artifact_id) = 7)),
    CONSTRAINT artifacts_byte_size_check CHECK ((byte_size > 0)),
    CONSTRAINT artifacts_check CHECK ((((retention_status = 'retained'::text) AND (deleted_at IS NULL)) OR ((retention_status = 'deleted'::text) AND (deleted_at IS NOT NULL)))),
    CONSTRAINT artifacts_check1 CHECK ((storage_locator = ((((('objects/sha256/'::text || SUBSTRING(content_digest FROM 8 FOR 2)) || '/'::text) || SUBSTRING(content_digest FROM 10 FOR 2)) || '/'::text) || SUBSTRING(content_digest FROM 8)))),
    CONSTRAINT artifacts_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT artifacts_integrity_status_check CHECK ((integrity_status = ANY (ARRAY['verified'::text, 'missing'::text, 'corrupt'::text]))),
    CONSTRAINT artifacts_logical_kind_check CHECK ((logical_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT artifacts_media_type_check CHECK (((length(media_type) <= 127) AND (media_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$'::text))),
    CONSTRAINT artifacts_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['creator_visible'::text, 'private'::text, 'shared'::text, 'restricted'::text]))),
    CONSTRAINT artifacts_producer_kind_check CHECK ((producer_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT artifacts_producer_trace_id_check CHECK (((producer_trace_id ~ '^[0-9a-f]{32}$'::text) AND (producer_trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT artifacts_retention_status_check CHECK ((retention_status = ANY (ARRAY['retained'::text, 'deleted'::text]))),
    CONSTRAINT artifacts_schema_version_check CHECK ((schema_version = 1))
);


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
    request_digest text,
    response_digest text,
    artifact_digest text,
    details_digest text,
    policy_ref uuid,
    grant_ref uuid,
    bundle_digest text,
    error_category text,
    schema_version smallint DEFAULT 1 NOT NULL,
    occurred_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT audit_events_actor_kind_check CHECK ((actor_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_actor_ref_check CHECK ((uuid_extract_version(actor_ref) = 7)),
    CONSTRAINT audit_events_after_version_check CHECK ((after_version >= 0)),
    CONSTRAINT audit_events_artifact_digest_check CHECK (((artifact_digest IS NULL) OR (artifact_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT audit_events_audit_event_id_check CHECK ((uuid_extract_version(audit_event_id) = 7)),
    CONSTRAINT audit_events_before_version_check CHECK ((before_version >= 0)),
    CONSTRAINT audit_events_bundle_digest_check CHECK (((bundle_digest IS NULL) OR (bundle_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT audit_events_check CHECK (((request_kind IS NULL) = (request_ref IS NULL))),
    CONSTRAINT audit_events_check1 CHECK (((before_version IS NULL) = (after_version IS NULL))),
    CONSTRAINT audit_events_check2 CHECK (((before_version IS NULL) OR (after_version > before_version))),
    CONSTRAINT audit_events_details_digest_check CHECK (((details_digest IS NULL) OR (details_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT audit_events_error_category_check CHECK (((error_category IS NULL) OR (error_category = ANY (ARRAY['input'::text, 'auth'::text, 'scope'::text, 'state'::text, 'conflict'::text, 'idempotency'::text, 'policy'::text, 'capability'::text, 'dependency'::text, 'effect'::text, 'integrity'::text, 'admin'::text, 'internal'::text])))),
    CONSTRAINT audit_events_grant_ref_check CHECK (((grant_ref IS NULL) OR (uuid_extract_version(grant_ref) = 7))),
    CONSTRAINT audit_events_operation_check CHECK ((operation ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_policy_ref_check CHECK (((policy_ref IS NULL) OR (uuid_extract_version(policy_ref) = 7))),
    CONSTRAINT audit_events_purpose_check CHECK ((purpose ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_request_digest_check CHECK (((request_digest IS NULL) OR (request_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT audit_events_request_kind_check CHECK (((request_kind IS NULL) OR (request_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text))),
    CONSTRAINT audit_events_request_ref_check CHECK (((request_ref IS NULL) OR (uuid_extract_version(request_ref) = 7))),
    CONSTRAINT audit_events_response_digest_check CHECK (((response_digest IS NULL) OR (response_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT audit_events_result_status_check CHECK ((result_status = ANY (ARRAY['accepted'::text, 'applied'::text, 'waiting'::text, 'rejected'::text, 'unavailable'::text, 'failed'::text, 'unknown'::text, 'completed'::text]))),
    CONSTRAINT audit_events_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT audit_events_sensitivity_check CHECK ((sensitivity = ANY (ARRAY['internal'::text, 'private'::text, 'restricted'::text]))),
    CONSTRAINT audit_events_subject_id_check CHECK (((subject_id IS NULL) OR (uuid_extract_version(subject_id) = 7))),
    CONSTRAINT audit_events_target_kind_check CHECK ((target_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT audit_events_target_ref_check CHECK ((uuid_extract_version(target_ref) = 7)),
    CONSTRAINT audit_events_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);


--
-- Name: capabilities; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.capabilities (
    capability_id uuid NOT NULL,
    capability_kind text NOT NULL,
    adapter_kind text NOT NULL,
    operation_class text NOT NULL,
    scope_schema text NOT NULL,
    availability_status text NOT NULL,
    verification_capability text NOT NULL,
    configuration_version bigint NOT NULL,
    configuration_digest text NOT NULL,
    CONSTRAINT capabilities_availability_chk CHECK ((availability_status = ANY (ARRAY['available'::text, 'unavailable'::text]))),
    CONSTRAINT capabilities_digest_chk CHECK ((configuration_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT capabilities_id_v7_chk CHECK (("substring"((capability_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capabilities_kind_chk CHECK ((capability_kind = ANY (ARRAY['creator.scene.reply'::text, 'codex.delegated-work'::text]))),
    CONSTRAINT capabilities_operation_chk CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text)) OR ((capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text)))),
    CONSTRAINT capabilities_version_chk CHECK ((configuration_version > 0))
);


--
-- Name: capability_request_basis_links; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.capability_request_basis_links (
    capability_request_id uuid NOT NULL,
    context_item_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    CONSTRAINT capability_request_basis_ordinal_chk CHECK (((ordinal >= 1) AND (ordinal <= 8)))
);


--
-- Name: capability_request_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.capability_request_decisions (
    capability_decision_id uuid NOT NULL,
    capability_request_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    expected_request_version bigint NOT NULL,
    resulting_request_version bigint NOT NULL,
    decision_kind text NOT NULL,
    command_digest text NOT NULL,
    scope_digest text,
    reason_code text,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT capability_decisions_digest_chk CHECK ((command_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT capability_decisions_id_v7_chk CHECK (("substring"((capability_decision_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capability_decisions_kind_chk CHECK ((decision_kind = ANY (ARRAY['grant'::text, 'limit'::text, 'deny'::text, 'revoke'::text, 'expire'::text]))),
    CONSTRAINT capability_decisions_schema_chk CHECK ((schema_version = 1)),
    CONSTRAINT capability_decisions_scope_chk CHECK (((scope_digest IS NULL) OR (scope_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT capability_decisions_version_chk CHECK (((expected_request_version > 0) AND (resulting_request_version = (expected_request_version + 1))))
);


--
-- Name: capability_requests; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.capability_requests (
    capability_request_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    subject_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    workspace_scope text,
    artifact_scope text,
    network_access boolean,
    requested_valid_for_seconds integer NOT NULL,
    requested_max_uses integer NOT NULL,
    requested_max_payload_bytes integer,
    request_digest text NOT NULL,
    current_status text DEFAULT 'pending'::text NOT NULL,
    request_version bigint DEFAULT 1 NOT NULL,
    resolved_by_party_id uuid,
    resolution_reason_class text,
    resolved_at timestamp(6) with time zone,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT capability_requests_digest_chk CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT capability_requests_id_v7_chk CHECK (("substring"((capability_request_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capability_requests_kind_chk CHECK ((capability_kind = ANY (ARRAY['creator.scene.reply'::text, 'codex.delegated-work'::text]))),
    CONSTRAINT capability_requests_operation_chk CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text)) OR ((capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text)))),
    CONSTRAINT capability_requests_proposal_chk CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT capability_requests_resolution_chk CHECK ((((current_status = 'pending'::text) AND (request_version = 1) AND (resolved_by_party_id IS NULL) AND (resolution_reason_class IS NULL) AND (resolved_at IS NULL)) OR ((current_status <> 'pending'::text) AND (request_version > 1) AND (resolved_by_party_id IS NOT NULL) AND (resolved_at IS NOT NULL)))),
    CONSTRAINT capability_requests_schema_chk CHECK ((schema_version = 1)),
    CONSTRAINT capability_requests_scope_chk CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (workspace_scope IS NULL) AND (artifact_scope IS NULL) AND (network_access IS NULL) AND ((requested_valid_for_seconds >= 60) AND (requested_valid_for_seconds <= 604800)) AND ((requested_max_uses >= 1) AND (requested_max_uses <= 16)) AND ((requested_max_payload_bytes >= 1) AND (requested_max_payload_bytes <= 65536))) OR ((capability_kind = 'codex.delegated-work'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (workspace_scope = 'isolated_ephemeral'::text) AND (artifact_scope = 'explicit_only'::text) AND (network_access = false) AND ((requested_valid_for_seconds >= 60) AND (requested_valid_for_seconds <= 3600)) AND (requested_max_uses = 1) AND (requested_max_payload_bytes IS NULL)))),
    CONSTRAINT capability_requests_status_chk CHECK ((current_status = ANY (ARRAY['pending'::text, 'granted'::text, 'limited'::text, 'denied'::text, 'revoked'::text, 'expired'::text]))),
    CONSTRAINT capability_requests_version_chk CHECK ((request_version > 0))
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
    evidence_digest text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT codex_result_sources_codex_result_source_id_check CHECK ((uuid_extract_version(codex_result_source_id) = 7)),
    CONSTRAINT codex_result_sources_evidence_digest_check CHECK ((evidence_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_result_sources_result_kind_check CHECK ((result_kind = ANY (ARRAY['verified_completion'::text, 'execution_failure'::text, 'outcome_unknown'::text, 'cancelled'::text]))),
    CONSTRAINT codex_result_sources_schema_version_check CHECK ((schema_version = 1))
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
    path_scope_digest text NOT NULL,
    validator_id text NOT NULL,
    deadline_seconds integer NOT NULL,
    trace_id text NOT NULL,
    admitted_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT codex_task_sources_codex_task_source_id_check CHECK ((uuid_extract_version(codex_task_source_id) = 7)),
    CONSTRAINT codex_task_sources_deadline_seconds_check CHECK (((deadline_seconds >= 60) AND (deadline_seconds <= 1800))),
    CONSTRAINT codex_task_sources_path_scope_digest_check CHECK ((path_scope_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_task_sources_schema_version_check CHECK ((schema_version = 1)),
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
    validation_digest text NOT NULL,
    changed_path_count integer NOT NULL,
    execution_error_code text,
    cleanup_error_code text,
    completed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT codex_verification_results_changed_path_count_check CHECK (((changed_path_count >= 0) AND (changed_path_count <= 500))),
    CONSTRAINT codex_verification_results_check CHECK ((((execution_status = 'verified'::text) AND (cleanup_status = 'clean'::text) AND (final_tree_digest IS NOT NULL) AND (patch_digest IS NOT NULL) AND (final_result_artifact_id IS NOT NULL) AND (patch_artifact_id IS NOT NULL) AND (result_bundle_artifact_id IS NOT NULL) AND (validation_report_artifact_id IS NOT NULL) AND (execution_error_code IS NULL) AND (cleanup_error_code IS NULL)) OR (execution_status <> 'verified'::text))),
    CONSTRAINT codex_verification_results_cleanup_error_code_check CHECK (((cleanup_error_code IS NULL) OR (cleanup_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_verification_results_cleanup_status_check CHECK ((cleanup_status = ANY (ARRAY['clean'::text, 'failed'::text]))),
    CONSTRAINT codex_verification_results_codex_verification_id_check CHECK ((uuid_extract_version(codex_verification_id) = 7)),
    CONSTRAINT codex_verification_results_execution_error_code_check CHECK (((execution_error_code IS NULL) OR (execution_error_code ~ '^CODEX-[A-Z0-9-]+$'::text))),
    CONSTRAINT codex_verification_results_execution_status_check CHECK ((execution_status = ANY (ARRAY['verified'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT codex_verification_results_final_tree_digest_check CHECK (((final_tree_digest IS NULL) OR (final_tree_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT codex_verification_results_patch_digest_check CHECK (((patch_digest IS NULL) OR (patch_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT codex_verification_results_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT codex_verification_results_source_tree_digest_check CHECK ((source_tree_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT codex_verification_results_validation_digest_check CHECK ((validation_digest ~ '^sha256:[0-9a-f]{64}$'::text))
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
    binding_digest text NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    version_policy text NOT NULL,
    profile text NOT NULL,
    request_schema_version text NOT NULL,
    candidate_schema_version text NOT NULL,
    pricing_snapshot_id text NOT NULL,
    credential_identity text NOT NULL,
    request_artifact_id uuid NOT NULL,
    request_digest text NOT NULL,
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
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT cognitive_attempts_attempt_no_check CHECK (((attempt_no >= 1) AND (attempt_no <= 2))),
    CONSTRAINT cognitive_attempts_binding_digest_check CHECK ((binding_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
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
    CONSTRAINT cognitive_attempts_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_attempts_request_schema_version_check CHECK ((request_schema_version = 'armi.model-request.v1'::text)),
    CONSTRAINT cognitive_attempts_result_status_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'rejected'::text, 'timed_out'::text, 'provider_failed'::text, 'cancelled'::text, 'outcome_unknown'::text])))),
    CONSTRAINT cognitive_attempts_schema_version_check CHECK ((schema_version = 1)),
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
    completion_digest text NOT NULL,
    runtime_instance_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    resolved_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT cognitive_candidate_applications_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_applications_candidate_application_id_check CHECK ((uuid_extract_version(candidate_application_id) = 7)),
    CONSTRAINT cognitive_candidate_applications_check CHECK (((resolution = 'applied'::text) = (subject_commit_id IS NOT NULL))),
    CONSTRAINT cognitive_candidate_applications_check1 CHECK (((successor_opportunity_id IS NULL) OR (resolution = 'stale'::text))),
    CONSTRAINT cognitive_candidate_applications_completion_digest_check CHECK ((completion_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_candidate_applications_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT cognitive_candidate_applications_observed_subject_version_check CHECK ((observed_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_applications_resolution_check CHECK ((resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'deferred'::text, 'declined'::text, 'no_action'::text, 'need_information'::text, 'stale'::text]))),
    CONSTRAINT cognitive_candidate_applications_schema_version_check CHECK ((schema_version = 1))
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
    semantic_digest text NOT NULL,
    ordinal smallint NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT cognitive_candidate_validation_items_atomic_group_ref_check CHECK ((atomic_group_ref ~ '^group:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT cognitive_candidate_validation_items_check CHECK ((((validation_status = 'accepted'::text) AND (reason_code IS NULL)) OR ((validation_status = 'rejected'::text) AND (reason_code IS NOT NULL)))),
    CONSTRAINT cognitive_candidate_validation_items_fact_class_check CHECK ((fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT cognitive_candidate_validation_items_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 16))),
    CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['experience'::text, 'self'::text, 'mind'::text, 'life_mode'::text, 'memory'::text, 'relationship'::text, 'activity'::text, 'capability'::text, 'action'::text, 'web_research'::text, 'codex_delegation'::text, 'sleep'::text, 'material'::text, 'prompt'::text, 'exact_life_query'::text, 'maintenance'::text]))),
    CONSTRAINT cognitive_candidate_validation_items_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT cognitive_candidate_validation_items_reason_code_check CHECK (((reason_code IS NULL) OR (reason_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_candidate_validation_items_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT cognitive_candidate_validation_items_semantic_digest_check CHECK ((semantic_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
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
    candidate_digest text NOT NULL,
    validator_identity text NOT NULL,
    policy_digest text NOT NULL,
    validation_status text NOT NULL,
    final_disposition text,
    change_set_artifact_id uuid,
    change_set_digest text,
    accepted_count smallint NOT NULL,
    rejected_count smallint NOT NULL,
    error_code text,
    validated_by_runtime_instance_id uuid CONSTRAINT cognitive_candidate_validat_validated_by_runtime_insta_not_null NOT NULL,
    validation_fence_token bigint NOT NULL,
    validated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK ((candidate_contract_version = ANY (ARRAY['armi.cognition-candidate.v1'::text, 'armi.cognition-candidate.v2'::text, 'armi.cognition-candidate.v3'::text, 'armi.cognition-candidate.v4'::text, 'armi.cognition-candidate.v5'::text, 'armi.cognition-candidate.v6'::text, 'armi.cognition-candidate.v7'::text, 'armi.creator-dialogue-candidate.v5'::text, 'armi.creator-dialogue-candidate.v6'::text, 'armi.creator-dialogue-candidate.v7'::text, 'armi.creator-dialogue-candidate.v8'::text, 'armi.creator-dialogue-candidate.v9'::text, 'armi.creator-dialogue-candidate.v10'::text, 'armi.creator-dialogue-candidate.v11'::text, 'armi.creator-dialogue-candidate.v12'::text, 'armi.creator-dialogue-candidate.v13'::text, 'armi.creator-dialogue-candidate.v14'::text, 'armi.creator-dialogue-candidate.v15'::text, 'armi.creator-dialogue-candidate.v16'::text, 'armi.creator-dialogue-candidate.v17'::text, 'armi.creator-dialogue-candidate.v18'::text, 'armi.autonomous-activity-candidate.v1'::text, 'armi.activity-attention-candidate.v1'::text, 'armi.activity-attention-candidate.v2'::text, 'armi.activity-internal-work-candidate.v1'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v2'::text]))),
    CONSTRAINT cognitive_candidate_validations_accepted_count_check CHECK (((accepted_count >= 0) AND (accepted_count <= 16))),
    CONSTRAINT cognitive_candidate_validations_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT cognitive_candidate_validations_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_candidate_validations_candidate_digest_check CHECK ((candidate_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_candidate_validations_candidate_validation_id_check CHECK ((uuid_extract_version(candidate_validation_id) = 7)),
    CONSTRAINT cognitive_candidate_validations_change_set_digest_check CHECK (((change_set_digest IS NULL) OR (change_set_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT cognitive_candidate_validations_check CHECK ((((validation_status = ANY (ARRAY['accepted'::text, 'partially_accepted'::text])) AND (final_disposition IS NOT NULL) AND (change_set_artifact_id IS NOT NULL) AND (change_set_digest IS NOT NULL) AND (error_code IS NULL)) OR ((validation_status = 'rejected'::text) AND (final_disposition IS NULL) AND (change_set_artifact_id IS NULL) AND (change_set_digest IS NULL) AND (accepted_count = 0) AND (error_code IS NOT NULL)))),
    CONSTRAINT cognitive_candidate_validations_context_digest_check CHECK ((context_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_candidate_validations_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_candidate_validations_final_disposition_check CHECK (((final_disposition IS NULL) OR (final_disposition = ANY (ARRAY['change'::text, 'no_change'::text, 'defer'::text, 'decline'::text, 'no_action'::text, 'need_information'::text])))),
    CONSTRAINT cognitive_candidate_validations_policy_digest_check CHECK ((policy_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_candidate_validations_rejected_count_check CHECK (((rejected_count >= 0) AND (rejected_count <= 16))),
    CONSTRAINT cognitive_candidate_validations_schema_version_check CHECK ((schema_version = 1)),
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
    source_digest text,
    trust_class text NOT NULL,
    privacy_scope text NOT NULL,
    disposition text NOT NULL,
    reason_code text,
    content_bytes integer NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT cognitive_context_items_check CHECK ((((source_ref IS NULL) AND (source_version IS NULL) AND (source_digest IS NULL)) OR ((source_ref IS NOT NULL) AND (source_version IS NOT NULL) AND (source_digest IS NOT NULL)))),
    CONSTRAINT cognitive_context_items_check1 CHECK ((((disposition = ANY (ARRAY['included'::text, 'excluded_policy'::text])) AND (reason_code IS NULL)) OR ((disposition = ANY (ARRAY['excluded_budget'::text, 'unavailable'::text, 'read_failed'::text])) AND (reason_code IS NOT NULL)))),
    CONSTRAINT cognitive_context_items_content_bytes_check CHECK ((content_bytes >= 0)),
    CONSTRAINT cognitive_context_items_context_item_id_check CHECK ((uuid_extract_version(context_item_id) = 7)),
    CONSTRAINT cognitive_context_items_disposition_check CHECK ((disposition = ANY (ARRAY['included'::text, 'excluded_policy'::text, 'excluded_budget'::text, 'unavailable'::text, 'read_failed'::text]))),
    CONSTRAINT cognitive_context_items_item_kind_check CHECK ((item_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT cognitive_context_items_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT cognitive_context_items_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['internal'::text, 'private'::text, 'restricted'::text]))),
    CONSTRAINT cognitive_context_items_reason_code_check CHECK (((reason_code IS NULL) OR (reason_code ~ '^CTX-[A-Z0-9-]+$'::text))),
    CONSTRAINT cognitive_context_items_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT cognitive_context_items_section_check CHECK ((section = ANY (ARRAY['runtime_truth'::text, 'purpose'::text, 'self'::text, 'mind'::text, 'life_mode'::text, 'scene'::text, 'relationship'::text, 'memory'::text, 'activity'::text, 'material'::text, 'evidence'::text, 'capability'::text, 'prompt'::text]))),
    CONSTRAINT cognitive_context_items_source_digest_check CHECK (((source_digest IS NULL) OR (source_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
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
    creator_party_id uuid,
    purpose text NOT NULL,
    status text NOT NULL,
    base_subject_version bigint NOT NULL,
    base_state_epoch bigint NOT NULL,
    bundle_activation_id uuid NOT NULL,
    policy_digest text NOT NULL,
    mechanism_identity text NOT NULL,
    mechanism_config_digest text NOT NULL,
    context_manifest_artifact_id uuid,
    compiled_context_artifact_id uuid,
    context_digest text,
    failure_code text,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    prepared_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    model_returned_at timestamp(6) with time zone,
    final_disposition text,
    validated_at timestamp(6) with time zone,
    application_resolution text,
    committed_at timestamp(6) with time zone,
    other_party_id uuid,
    CONSTRAINT cognitive_episodes_application_resolution_check CHECK (((application_resolution IS NULL) OR (application_resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'deferred'::text, 'declined'::text, 'no_action'::text, 'need_information'::text, 'stale'::text])))),
    CONSTRAINT cognitive_episodes_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT cognitive_episodes_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT cognitive_episodes_cognitive_episode_id_check CHECK ((uuid_extract_version(cognitive_episode_id) = 7)),
    CONSTRAINT cognitive_episodes_context_digest_check CHECK (((context_digest IS NULL) OR (context_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT cognitive_episodes_failure_code_check CHECK (((failure_code IS NULL) OR (failure_code ~ '^[A-Z][A-Z0-9-]{2,127}$'::text))),
    CONSTRAINT cognitive_episodes_final_disposition_check CHECK (((final_disposition IS NULL) OR (final_disposition = ANY (ARRAY['change'::text, 'no_change'::text, 'defer'::text, 'decline'::text, 'no_action'::text, 'need_information'::text])))),
    CONSTRAINT cognitive_episodes_mechanism_config_digest_check CHECK ((mechanism_config_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_episodes_mechanism_identity_check CHECK ((mechanism_identity = 'armi.context-compiler.deterministic-v1'::text)),
    CONSTRAINT cognitive_episodes_policy_digest_check CHECK ((policy_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT cognitive_episodes_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_web_evidence'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text]))),
    CONSTRAINT cognitive_episodes_scene_shape_check CHECK ((((purpose = ANY (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text])) AND (scene_id IS NULL) AND (creator_party_id IS NULL) AND (other_party_id IS NULL)) OR ((purpose = 'consider_other_human_input'::text) AND (scene_id IS NOT NULL) AND (creator_party_id IS NULL) AND (other_party_id IS NOT NULL)) OR ((purpose <> ALL (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_other_human_input'::text])) AND (scene_id IS NOT NULL) AND (creator_party_id IS NOT NULL) AND (other_party_id IS NULL)))),
    CONSTRAINT cognitive_episodes_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT cognitive_episodes_state_check CHECK ((((status = 'preparing'::text) AND (context_digest IS NULL) AND (prepared_at IS NULL) AND (model_returned_at IS NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['prepared'::text, 'calling_model'::text])) AND (context_digest IS NOT NULL) AND (prepared_at IS NOT NULL) AND (model_returned_at IS NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['model_returned'::text, 'validating'::text])) AND (context_digest IS NOT NULL) AND (prepared_at IS NOT NULL) AND (model_returned_at IS NOT NULL) AND (validated_at IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = ANY (ARRAY['candidate_validated'::text, 'committing'::text])) AND (context_digest IS NOT NULL) AND (model_returned_at IS NOT NULL) AND (validated_at IS NOT NULL) AND (final_disposition IS NOT NULL) AND (failure_code IS NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = 'candidate_rejected'::text) AND (validated_at IS NOT NULL) AND (final_disposition IS NULL) AND (failure_code ~ '^CANDIDATE-[A-Z0-9-]+$'::text) AND (application_resolution IS NULL) AND (committed_at IS NULL)) OR ((status = 'completed'::text) AND (application_resolution = ANY (ARRAY['applied'::text, 'no_change'::text, 'declined'::text, 'no_action'::text, 'deferred'::text, 'need_information'::text])) AND (committed_at IS NOT NULL)) OR ((status = 'stale'::text) AND (application_resolution = 'stale'::text) AND (committed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'cancelled'::text])) AND (failure_code IS NOT NULL) AND (application_resolution IS NULL) AND (committed_at IS NULL)))),
    CONSTRAINT cognitive_episodes_status_check CHECK ((status = ANY (ARRAY['preparing'::text, 'prepared'::text, 'calling_model'::text, 'model_returned'::text, 'validating'::text, 'candidate_validated'::text, 'candidate_rejected'::text, 'committing'::text, 'completed'::text, 'stale'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT cognitive_episodes_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
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
    manifest_digest text,
    table_count integer DEFAULT 0 NOT NULL,
    row_count bigint DEFAULT 0 NOT NULL,
    artifact_count bigint DEFAULT 0 NOT NULL,
    missing_artifacts jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT creator_exports_artifact_count_check CHECK ((artifact_count >= 0)),
    CONSTRAINT creator_exports_check CHECK ((((status = 'running'::text) AND (completed_at IS NULL)) OR ((status <> 'running'::text) AND (completed_at IS NOT NULL)))),
    CONSTRAINT creator_exports_creator_export_id_check CHECK ((uuid_extract_version(creator_export_id) = 7)),
    CONSTRAINT creator_exports_directory_name_check CHECK (((directory_name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'::text) AND (directory_name <> ALL (ARRAY['.'::text, '..'::text])))),
    CONSTRAINT creator_exports_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT creator_exports_manifest_digest_check CHECK (((manifest_digest IS NULL) OR (manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT creator_exports_missing_artifacts_check CHECK ((jsonb_typeof(missing_artifacts) = 'array'::text)),
    CONSTRAINT creator_exports_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_exports_row_count_check CHECK ((row_count >= 0)),
    CONSTRAINT creator_exports_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT creator_exports_status_check CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'partial'::text, 'failed'::text]))),
    CONSTRAINT creator_exports_table_count_check CHECK ((table_count >= 0))
);


--
-- Name: creator_input_interactions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.creator_input_interactions (
    creator_interaction_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    purpose text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    content_digest text NOT NULL,
    trace_id text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT creator_input_interactions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_input_interactions_creator_interaction_id_check CHECK ((uuid_extract_version(creator_interaction_id) = 7)),
    CONSTRAINT creator_input_interactions_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT creator_input_interactions_purpose_check CHECK ((purpose = ANY (ARRAY['creator_message'::text, 'codex_task_request'::text]))),
    CONSTRAINT creator_input_interactions_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_input_interactions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT creator_input_interactions_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);


--
-- Name: creator_response_deliveries; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.creator_response_deliveries (
    creator_response_delivery_id uuid CONSTRAINT creator_response_deliveries_creator_response_delivery__not_null NOT NULL,
    effect_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    receipt_digest text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT creator_response_deliveries_creator_response_delivery_id_check CHECK ((uuid_extract_version(creator_response_delivery_id) = 7)),
    CONSTRAINT creator_response_deliveries_payload_bytes_check CHECK (((payload_bytes >= 1) AND (payload_bytes <= 65536))),
    CONSTRAINT creator_response_deliveries_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_response_deliveries_receipt_digest_check CHECK ((receipt_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT creator_response_deliveries_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: creator_response_operations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.creator_response_operations (
    creator_response_operation_id uuid CONSTRAINT creator_response_operations_creator_response_operation_not_null NOT NULL,
    root_opportunity_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    action_intent_id uuid,
    formal_no_action_id uuid,
    admission_work_id uuid,
    current_status text NOT NULL,
    matched_grant_id uuid,
    completion_digest text,
    reason_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    registration_work_id uuid,
    current_policy_decision_id uuid,
    effect_id uuid,
    effect_registration_digest text,
    effect_registered_at timestamp(6) with time zone,
    operation_kind text DEFAULT 'creator_response'::text NOT NULL,
    CONSTRAINT creator_response_operations_check CHECK ((((formal_no_action_id IS NOT NULL) AND (operation_kind = 'creator_response'::text) AND (action_intent_id IS NULL) AND (current_status = 'no_action'::text)) OR ((formal_no_action_id IS NULL) AND (action_intent_id IS NOT NULL)))),
    CONSTRAINT creator_response_operations_completion_digest_check CHECK (((completion_digest IS NULL) OR (completion_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT creator_response_operations_creator_response_operation_id_check CHECK ((uuid_extract_version(creator_response_operation_id) = 7)),
    CONSTRAINT creator_response_operations_current_status_check CHECK ((current_status = ANY (ARRAY['pending'::text, 'accepted'::text, 'effect_registered'::text, 'effect_dispatching'::text, 'effect_completed'::text, 'effect_failed'::text, 'effect_unknown'::text, 'effect_cancelled'::text, 'codex_waiting_grant'::text, 'codex_dispatching'::text, 'codex_verifying'::text, 'codex_completed'::text, 'codex_failed'::text, 'codex_unknown'::text, 'codex_cancelled'::text, 'codex_result_pending'::text, 'codex_result_accepted'::text, 'codex_result_rejected'::text, 'no_action'::text, 'unauthorized'::text, 'unavailable'::text, 'failed'::text]))),
    CONSTRAINT creator_response_operations_effect_registration_digest_check CHECK (((effect_registration_digest IS NULL) OR (effect_registration_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT creator_response_operations_effect_state_check CHECK ((((effect_id IS NULL) AND (current_policy_decision_id IS NULL) AND (effect_registration_digest IS NULL) AND (effect_registered_at IS NULL)) OR ((effect_id IS NOT NULL) AND (current_policy_decision_id IS NOT NULL) AND (effect_registration_digest IS NOT NULL) AND (effect_registered_at IS NOT NULL)))),
    CONSTRAINT creator_response_operations_operation_kind_check CHECK ((operation_kind = ANY (ARRAY['creator_response'::text, 'codex_delegation'::text]))),
    CONSTRAINT creator_response_operations_reason_code_check CHECK (((reason_code IS NULL) OR (reason_code ~ '^(?:RESPONSE|POLICY|ACTION|CODEX)-[A-Z0-9-]+$'::text))),
    CONSTRAINT creator_response_operations_schema_version_check CHECK ((schema_version = 1))
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
    execution_digest text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT deletion_items_check CHECK ((((result_status = 'pending'::text) AND (completed_at IS NULL) AND (execution_digest IS NULL)) OR ((result_status <> 'pending'::text) AND (completed_at IS NOT NULL) AND (execution_digest IS NOT NULL)))),
    CONSTRAINT deletion_items_deletion_item_id_check CHECK ((uuid_extract_version(deletion_item_id) = 7)),
    CONSTRAINT deletion_items_execution_digest_check CHECK (((execution_digest IS NULL) OR (execution_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT deletion_items_remaining_location_check CHECK (((remaining_location IS NULL) OR (remaining_location = ANY (ARRAY['shared_local_reference'::text, 'objective_history'::text, 'local_artifact_store'::text])))),
    CONSTRAINT deletion_items_required_action_check CHECK ((required_action = ANY (ARRAY['delete'::text, 'tombstone'::text, 'retain'::text]))),
    CONSTRAINT deletion_items_result_status_check CHECK ((result_status = ANY (ARRAY['pending'::text, 'completed'::text, 'partial'::text, 'too_late'::text, 'unknown'::text]))),
    CONSTRAINT deletion_items_schema_version_check CHECK ((schema_version = 1)),
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
    schema_version smallint DEFAULT 1 NOT NULL,
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
    CONSTRAINT deletion_orders_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT deletion_orders_scope_kind_check CHECK ((scope_kind = ANY (ARRAY['party_contact'::text, 'party_local_data'::text]))),
    CONSTRAINT deletion_orders_status_check CHECK ((status = 'effective'::text)),
    CONSTRAINT deletion_orders_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);


--
-- Name: deployment_environments; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.deployment_environments (
    singleton_key boolean DEFAULT true NOT NULL,
    environment_id uuid NOT NULL,
    environment_kind text NOT NULL,
    incarnation bigint NOT NULL,
    resettable boolean NOT NULL,
    test_controls_enabled boolean NOT NULL,
    bundle_digest text NOT NULL,
    config_digest text NOT NULL,
    template_digest text NOT NULL,
    data_root_identity_digest text NOT NULL,
    database_identity_digest text NOT NULL,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT deployment_environments_bundle_digest_check CHECK ((bundle_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT deployment_environments_check CHECK (((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text])) OR ((NOT resettable) AND (NOT test_controls_enabled)))),
    CONSTRAINT deployment_environments_check1 CHECK (((NOT test_controls_enabled) OR (environment_kind = ANY (ARRAY['system_test'::text, 'acceptance'::text])))),
    CONSTRAINT deployment_environments_config_digest_check CHECK ((config_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT deployment_environments_data_root_identity_digest_check CHECK ((data_root_identity_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT deployment_environments_database_identity_digest_check CHECK ((database_identity_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT deployment_environments_environment_id_check CHECK ((uuid_extract_version(environment_id) = 7)),
    CONSTRAINT deployment_environments_environment_kind_check CHECK ((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text, 'active'::text, 'restore_quarantine'::text]))),
    CONSTRAINT deployment_environments_incarnation_check CHECK ((incarnation > 0)),
    CONSTRAINT deployment_environments_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT deployment_environments_singleton_key_check CHECK (singleton_key),
    CONSTRAINT deployment_environments_template_digest_check CHECK ((template_digest ~ '^sha256:[0-9a-f]{64}$'::text))
);


--
-- Name: durable_work; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.durable_work (
    work_id uuid NOT NULL,
    work_kind text NOT NULL,
    owner_kind text NOT NULL,
    owner_ref uuid NOT NULL,
    subject_id uuid,
    idempotency_key text NOT NULL,
    payload_kind text,
    payload_ref uuid,
    payload_digest text NOT NULL,
    priority smallint DEFAULT 0 NOT NULL,
    not_before timestamp(6) with time zone NOT NULL,
    deadline_at timestamp(6) with time zone NOT NULL,
    status text DEFAULT 'ready'::text NOT NULL,
    max_attempts smallint NOT NULL,
    attempt_count smallint DEFAULT 0 NOT NULL,
    current_attempt_id uuid,
    lease_owner uuid,
    lease_expires_at timestamp(6) with time zone,
    lease_token bigint DEFAULT 0 NOT NULL,
    result_kind text,
    result_ref uuid,
    last_error_code text,
    trace_id text NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT durable_work_check CHECK (((attempt_count >= 0) AND (attempt_count <= max_attempts))),
    CONSTRAINT durable_work_check1 CHECK (((payload_kind IS NULL) = (payload_ref IS NULL))),
    CONSTRAINT durable_work_check2 CHECK (((result_kind IS NULL) = (result_ref IS NULL))),
    CONSTRAINT durable_work_check3 CHECK ((deadline_at > not_before)),
    CONSTRAINT durable_work_check4 CHECK ((((status = 'leased'::text) AND (current_attempt_id IS NOT NULL) AND (lease_owner IS NOT NULL) AND (lease_expires_at IS NOT NULL) AND (lease_token > 0) AND (attempt_count > 0)) OR ((status <> 'leased'::text) AND (current_attempt_id IS NULL) AND (lease_owner IS NULL) AND (lease_expires_at IS NULL)))),
    CONSTRAINT durable_work_check5 CHECK ((((status = 'completed'::text) AND (result_ref IS NOT NULL)) OR ((status <> 'completed'::text) AND (result_ref IS NULL)))),
    CONSTRAINT durable_work_current_attempt_id_check CHECK (((current_attempt_id IS NULL) OR (uuid_extract_version(current_attempt_id) = 7))),
    CONSTRAINT durable_work_idempotency_key_check CHECK (((length(idempotency_key) >= 1) AND (length(idempotency_key) <= 128) AND (idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT durable_work_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^[A-Z][A-Z0-9-]{0,127}$'::text))),
    CONSTRAINT durable_work_lease_owner_check CHECK (((lease_owner IS NULL) OR (uuid_extract_version(lease_owner) = 7))),
    CONSTRAINT durable_work_lease_token_check CHECK ((lease_token >= 0)),
    CONSTRAINT durable_work_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 100))),
    CONSTRAINT durable_work_owner_kind_check CHECK ((owner_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT durable_work_owner_ref_check CHECK ((uuid_extract_version(owner_ref) = 7)),
    CONSTRAINT durable_work_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT durable_work_payload_kind_check CHECK (((payload_kind IS NULL) OR (payload_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text))),
    CONSTRAINT durable_work_payload_ref_check CHECK (((payload_ref IS NULL) OR (uuid_extract_version(payload_ref) = 7))),
    CONSTRAINT durable_work_priority_check CHECK (((priority >= 0) AND (priority <= 100))),
    CONSTRAINT durable_work_result_kind_check CHECK (((result_kind IS NULL) OR (result_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text))),
    CONSTRAINT durable_work_result_ref_check CHECK (((result_ref IS NULL) OR (uuid_extract_version(result_ref) = 7))),
    CONSTRAINT durable_work_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT durable_work_status_check CHECK ((status = ANY (ARRAY['ready'::text, 'leased'::text, 'completed'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT durable_work_subject_id_check CHECK (((subject_id IS NULL) OR (uuid_extract_version(subject_id) = 7))),
    CONSTRAINT durable_work_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT durable_work_work_id_check CHECK ((uuid_extract_version(work_id) = 7)),
    CONSTRAINT durable_work_work_kind_check CHECK ((work_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text))
);


--
-- Name: effect_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effect_attempts (
    effect_attempt_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    attempt_no smallint NOT NULL,
    adapter_binding text NOT NULL,
    request_digest text NOT NULL,
    claim_token bigint NOT NULL,
    dispatch_state text NOT NULL,
    result_status text,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT effect_attempts_adapter_binding_check CHECK ((adapter_binding = ANY (ARRAY['armi.creator-response-adapter.postgresql-inbox-v1'::text, 'armi.codex-runner.openai-python-sdk-v1'::text]))),
    CONSTRAINT effect_attempts_attempt_no_check CHECK (((attempt_no >= 1) AND (attempt_no <= 2))),
    CONSTRAINT effect_attempts_check CHECK ((((dispatch_state = 'prepared'::text) AND (result_status IS NULL) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'dispatching'::text) AND (result_status IS NULL) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status IS NOT NULL) AND (settled_at IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = ANY (ARRAY['failed'::text, 'cancelled'::text])) AND (dispatched_at IS NULL)))))),
    CONSTRAINT effect_attempts_check1 CHECK (((result_status = ANY (ARRAY['failed'::text, 'unknown'::text])) = (error_code IS NOT NULL))),
    CONSTRAINT effect_attempts_claim_token_check CHECK ((claim_token > 0)),
    CONSTRAINT effect_attempts_dispatch_state_check CHECK ((dispatch_state = ANY (ARRAY['prepared'::text, 'dispatching'::text, 'settled'::text]))),
    CONSTRAINT effect_attempts_effect_attempt_id_check CHECK ((uuid_extract_version(effect_attempt_id) = 7)),
    CONSTRAINT effect_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'::text))),
    CONSTRAINT effect_attempts_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effect_attempts_result_status_check CHECK ((result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT effect_attempts_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: effect_observations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effect_observations (
    effect_observation_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    effect_attempt_id uuid NOT NULL,
    observation_kind text NOT NULL,
    reliability text NOT NULL,
    receiver_ref uuid,
    observation_digest text NOT NULL,
    observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT effect_observations_check CHECK (((observation_kind = 'receipt'::text) = (receiver_ref IS NOT NULL))),
    CONSTRAINT effect_observations_check1 CHECK (((observation_kind = 'ambiguous'::text) = (reliability = 'inconclusive'::text))),
    CONSTRAINT effect_observations_effect_observation_id_check CHECK ((uuid_extract_version(effect_observation_id) = 7)),
    CONSTRAINT effect_observations_observation_digest_check CHECK ((observation_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effect_observations_observation_kind_check CHECK ((observation_kind = ANY (ARRAY['receipt'::text, 'query'::text, 'rejection'::text, 'ambiguous'::text, 'runner_verified'::text, 'runner_failed'::text, 'runner_unknown'::text, 'runner_cancelled'::text]))),
    CONSTRAINT effect_observations_receiver_ref_check CHECK (((receiver_ref IS NULL) OR (uuid_extract_version(receiver_ref) = 7))),
    CONSTRAINT effect_observations_reliability_check CHECK ((reliability = ANY (ARRAY['reliable'::text, 'inconclusive'::text]))),
    CONSTRAINT effect_observations_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: effect_outbox_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effect_outbox_items (
    effect_outbox_item_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    message_kind text NOT NULL,
    payload_digest text NOT NULL,
    status text NOT NULL,
    available_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    cancelled_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    claim_owner uuid,
    claim_expires_at timestamp(6) with time zone,
    claim_token bigint DEFAULT 0 NOT NULL,
    attempt_count smallint DEFAULT 0 NOT NULL,
    max_attempts smallint DEFAULT 2 NOT NULL,
    dispatch_deadline timestamp(6) with time zone NOT NULL,
    delivered_at timestamp(6) with time zone,
    last_error_code text,
    CONSTRAINT effect_outbox_items_attempt_count_check CHECK (((attempt_count >= 0) AND (attempt_count <= 2))),
    CONSTRAINT effect_outbox_items_check CHECK ((((status = 'ready'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (cancelled_at IS NULL) AND (delivered_at IS NULL)) OR ((status = 'claimed'::text) AND (claim_owner IS NOT NULL) AND (claim_expires_at IS NOT NULL) AND (claim_token > 0) AND (cancelled_at IS NULL) AND (delivered_at IS NULL)) OR ((status = 'delivered'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (cancelled_at IS NULL) AND (delivered_at IS NOT NULL)) OR ((status = ANY (ARRAY['dead'::text, 'unknown'::text])) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (cancelled_at IS NULL) AND (delivered_at IS NULL) AND (last_error_code IS NOT NULL)) OR ((status = 'cancelled'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (cancelled_at IS NOT NULL) AND (delivered_at IS NULL)))),
    CONSTRAINT effect_outbox_items_claim_token_check CHECK ((claim_token >= 0)),
    CONSTRAINT effect_outbox_items_deadline_check CHECK ((dispatch_deadline > available_at)),
    CONSTRAINT effect_outbox_items_effect_outbox_item_id_check CHECK ((uuid_extract_version(effect_outbox_item_id) = 7)),
    CONSTRAINT effect_outbox_items_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'::text))),
    CONSTRAINT effect_outbox_items_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 2))),
    CONSTRAINT effect_outbox_items_message_kind_check CHECK ((message_kind = 'effect.dispatch'::text)),
    CONSTRAINT effect_outbox_items_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effect_outbox_items_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT effect_outbox_items_status_check CHECK ((status = ANY (ARRAY['ready'::text, 'claimed'::text, 'delivered'::text, 'dead'::text, 'unknown'::text, 'cancelled'::text])))
);


--
-- Name: effects; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effects (
    effect_id uuid NOT NULL,
    action_intent_revision_id uuid NOT NULL,
    creator_response_operation_id uuid NOT NULL,
    policy_decision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    effect_kind text NOT NULL,
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    registration_digest text NOT NULL,
    status text NOT NULL,
    verification_status text NOT NULL,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    cancelled_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    trace_id text NOT NULL,
    current_attempt_id uuid,
    current_observation_id uuid,
    settlement_digest text,
    settled_at timestamp(6) with time zone,
    CONSTRAINT effects_check CHECK ((((status = 'registered'::text) AND (verification_status = 'not_started'::text) AND (current_attempt_id IS NULL) AND (current_observation_id IS NULL) AND (settlement_digest IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = 'dispatching'::text) AND (verification_status = 'pending'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NULL) AND (settlement_digest IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = ANY (ARRAY['completed'::text, 'failed'::text])) AND (verification_status = 'verified'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settlement_digest IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'unknown'::text) AND (verification_status = 'inconclusive'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settlement_digest IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'cancelled'::text) AND (((verification_status = 'not_started'::text) AND (current_attempt_id IS NULL) AND (current_observation_id IS NULL) AND (settlement_digest IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NOT NULL)) OR ((verification_status = 'verified'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settlement_digest IS NOT NULL) AND (settled_at IS NOT NULL)))))),
    CONSTRAINT effects_effect_id_check CHECK ((uuid_extract_version(effect_id) = 7)),
    CONSTRAINT effects_effect_kind_check CHECK ((effect_kind = ANY (ARRAY['creator_response'::text, 'codex_delegation'::text]))),
    CONSTRAINT effects_kind_scope_check CHECK ((((effect_kind = 'creator_response'::text) AND (capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text)) OR ((effect_kind = 'codex_delegation'::text) AND (capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text)))),
    CONSTRAINT effects_payload_bytes_check CHECK (((payload_bytes >= 1) AND (payload_bytes <= 65536))),
    CONSTRAINT effects_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effects_registration_digest_check CHECK ((registration_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effects_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT effects_settlement_digest_check CHECK (((settlement_digest IS NULL) OR (settlement_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT effects_status_check CHECK ((status = ANY (ARRAY['registered'::text, 'dispatching'::text, 'completed'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT effects_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT effects_verification_status_check CHECK ((verification_status = ANY (ARRAY['not_started'::text, 'pending'::text, 'verified'::text, 'inconclusive'::text])))
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
    result_digest text,
    result_count smallint,
    failure_code text,
    result_opportunity_id uuid,
    trace_id text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT exact_life_query_intents_check CHECK ((((status = 'pending'::text) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (result_count IS NULL) AND (failure_code IS NULL) AND (result_opportunity_id IS NULL) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'empty'::text])) AND (result_artifact_id IS NOT NULL) AND (result_digest IS NOT NULL) AND (result_count IS NOT NULL) AND (failure_code IS NULL) AND (result_opportunity_id IS NOT NULL) AND (completed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'denied'::text])) AND (result_artifact_id IS NOT NULL) AND (result_digest IS NOT NULL) AND (result_count = 0) AND (failure_code IS NOT NULL) AND (result_opportunity_id IS NOT NULL) AND (completed_at IS NOT NULL)))),
    CONSTRAINT exact_life_query_intents_check1 CHECK (((status = 'empty'::text) = ((result_count = 0) AND (failure_code IS NULL)))),
    CONSTRAINT exact_life_query_intents_check2 CHECK (((status = 'succeeded'::text) = (result_count > 0))),
    CONSTRAINT exact_life_query_intents_exact_life_query_intent_id_check CHECK ((uuid_extract_version(exact_life_query_intent_id) = 7)),
    CONSTRAINT exact_life_query_intents_failure_code_check CHECK (((failure_code IS NULL) OR (failure_code ~ '^LIFE-QUERY-[A-Z0-9-]+$'::text))),
    CONSTRAINT exact_life_query_intents_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT exact_life_query_intents_query_digest_check CHECK ((query_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT exact_life_query_intents_query_text_check CHECK (((query_text IS NULL) OR ((octet_length(query_text) >= 1) AND (octet_length(query_text) <= 1024) AND (btrim(query_text) <> ''::text)))),
    CONSTRAINT exact_life_query_intents_record_kind_check CHECK ((record_kind = ANY (ARRAY['activity'::text, 'conversation'::text, 'material'::text, 'memory'::text, 'relationship'::text, 'self_change'::text]))),
    CONSTRAINT exact_life_query_intents_result_count_check CHECK (((result_count IS NULL) OR ((result_count >= 0) AND (result_count <= 20)))),
    CONSTRAINT exact_life_query_intents_result_digest_check CHECK (((result_digest IS NULL) OR (result_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT exact_life_query_intents_result_limit_check CHECK (((result_limit >= 1) AND (result_limit <= 20))),
    CONSTRAINT exact_life_query_intents_schema_version_check CHECK ((schema_version = 1)),
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
    creator_interaction_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid,
    artifact_id uuid NOT NULL,
    source_kind text NOT NULL,
    trust_status text NOT NULL,
    privacy_scope text NOT NULL,
    acceptance_status text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    web_observation_request_id uuid,
    observation_attempt_id uuid,
    codex_task_source_id uuid,
    codex_verification_id uuid,
    other_human_interaction_id uuid,
    other_party_id uuid,
    CONSTRAINT external_evidence_acceptance_status_check CHECK ((acceptance_status = 'accepted'::text)),
    CONSTRAINT external_evidence_evidence_id_check CHECK ((uuid_extract_version(evidence_id) = 7)),
    CONSTRAINT external_evidence_privacy_scope_check CHECK ((privacy_scope = ANY (ARRAY['creator_visible'::text, 'private'::text]))),
    CONSTRAINT external_evidence_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT external_evidence_source_identity_check CHECK ((((source_kind = 'creator_input'::text) AND (creator_interaction_id IS NOT NULL) AND (other_human_interaction_id IS NULL) AND (other_party_id IS NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL) AND (creator_party_id IS NOT NULL) AND (privacy_scope = 'creator_visible'::text)) OR ((source_kind = 'other_human_input'::text) AND (creator_interaction_id IS NULL) AND (other_human_interaction_id IS NOT NULL) AND (other_party_id IS NOT NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL) AND (creator_party_id IS NULL) AND (privacy_scope = 'private'::text)) OR ((source_kind = 'web_search'::text) AND (creator_interaction_id IS NULL) AND (other_human_interaction_id IS NULL) AND (other_party_id IS NULL) AND (web_observation_request_id IS NOT NULL) AND (observation_attempt_id IS NOT NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NULL) AND (creator_party_id IS NOT NULL) AND (privacy_scope = 'private'::text)) OR ((source_kind = 'codex_task_source'::text) AND (other_human_interaction_id IS NULL) AND (other_party_id IS NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NOT NULL) AND (codex_verification_id IS NULL) AND (creator_party_id IS NOT NULL) AND (privacy_scope = 'private'::text)) OR ((source_kind = 'codex_result'::text) AND (creator_interaction_id IS NULL) AND (other_human_interaction_id IS NULL) AND (other_party_id IS NULL) AND (web_observation_request_id IS NULL) AND (observation_attempt_id IS NULL) AND (codex_task_source_id IS NULL) AND (codex_verification_id IS NOT NULL) AND (creator_party_id IS NOT NULL) AND (privacy_scope = 'private'::text)))),
    CONSTRAINT external_evidence_source_kind_check CHECK ((source_kind = ANY (ARRAY['creator_input'::text, 'web_search'::text, 'codex_task_source'::text, 'codex_result'::text, 'other_human_input'::text]))),
    CONSTRAINT external_evidence_trust_status_check CHECK ((trust_status = 'external_claim'::text))
);


--
-- Name: formal_no_action_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.formal_no_action_decisions (
    formal_no_action_id uuid NOT NULL,
    candidate_application_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    root_opportunity_id uuid NOT NULL,
    decision_kind text NOT NULL,
    reason_class text NOT NULL,
    basis_digest text NOT NULL,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT formal_no_action_decisions_basis_digest_check CHECK ((basis_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT formal_no_action_decisions_check CHECK ((((decision_kind = 'decline'::text) AND (reason_class = 'subjective_refusal'::text)) OR ((decision_kind = 'no_action'::text) AND (reason_class = 'subjective_silence'::text)))),
    CONSTRAINT formal_no_action_decisions_decision_kind_check CHECK ((decision_kind = ANY (ARRAY['decline'::text, 'no_action'::text]))),
    CONSTRAINT formal_no_action_decisions_formal_no_action_id_check CHECK ((uuid_extract_version(formal_no_action_id) = 7)),
    CONSTRAINT formal_no_action_decisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT formal_no_action_decisions_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: interaction_scenes; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.interaction_scenes (
    scene_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_key text NOT NULL,
    scene_kind text NOT NULL,
    primary_party_id uuid NOT NULL,
    audience_scope text NOT NULL,
    current_status text NOT NULL,
    opened_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    closed_at timestamp(6) with time zone,
    recent_context_boundary uuid,
    schema_version smallint DEFAULT 1 NOT NULL,
    primary_party_kind text DEFAULT 'creator'::text NOT NULL,
    CONSTRAINT interaction_scenes_audience_scope_check CHECK ((audience_scope = ANY (ARRAY['creator'::text, 'other_human'::text]))),
    CONSTRAINT interaction_scenes_check CHECK ((((current_status = 'open'::text) AND (closed_at IS NULL)) OR ((current_status = 'closed'::text) AND (closed_at IS NOT NULL) AND (closed_at >= opened_at)))),
    CONSTRAINT interaction_scenes_current_status_check CHECK ((current_status = ANY (ARRAY['open'::text, 'closed'::text]))),
    CONSTRAINT interaction_scenes_recent_context_boundary_check CHECK (((recent_context_boundary IS NULL) OR (uuid_extract_version(recent_context_boundary) = 7))),
    CONSTRAINT interaction_scenes_role_shape_check CHECK ((((scene_kind = 'creator_dialogue'::text) AND (audience_scope = 'creator'::text) AND (primary_party_kind = 'creator'::text)) OR ((scene_kind = 'other_human_dialogue'::text) AND (audience_scope = 'other_human'::text) AND (primary_party_kind = 'other_human'::text)))),
    CONSTRAINT interaction_scenes_scene_id_check CHECK ((uuid_extract_version(scene_id) = 7)),
    CONSTRAINT interaction_scenes_scene_key_check CHECK ((scene_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT interaction_scenes_scene_kind_check CHECK ((scene_kind = ANY (ARRAY['creator_dialogue'::text, 'other_human_dialogue'::text]))),
    CONSTRAINT interaction_scenes_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: life_generations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.life_generations (
    life_generation_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    generation_no bigint NOT NULL,
    status text NOT NULL,
    opened_subject_version bigint NOT NULL,
    closed_subject_version bigint,
    activation_reason text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT life_generations_activation_reason_check CHECK ((activation_reason = 'birth'::text)),
    CONSTRAINT life_generations_closed_subject_version_check CHECK ((closed_subject_version IS NULL)),
    CONSTRAINT life_generations_generation_no_check CHECK ((generation_no = 1)),
    CONSTRAINT life_generations_life_generation_id_check CHECK ((uuid_extract_version(life_generation_id) = 7)),
    CONSTRAINT life_generations_opened_subject_version_check CHECK ((opened_subject_version = 0)),
    CONSTRAINT life_generations_status_check CHECK ((status = ANY (ARRAY['active'::text, 'fenced'::text, 'preparing'::text])))
);


--
-- Name: life_material_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.life_material_revisions (
    life_material_revision_id uuid NOT NULL,
    life_material_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    artifact_id uuid NOT NULL,
    body_digest text NOT NULL,
    title text NOT NULL,
    metadata jsonb NOT NULL,
    revision_kind text NOT NULL,
    privacy_status text NOT NULL,
    material_status text NOT NULL,
    source_kind text NOT NULL,
    semantic_digest text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT life_material_revisions_body_digest_check CHECK ((body_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT life_material_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (revision_kind = 'created'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL) AND (revision_kind = ANY (ARRAY['updated'::text, 'privacy_changed'::text, 'deleted'::text]))))),
    CONSTRAINT life_material_revisions_check1 CHECK ((((revision_kind = 'created'::text) AND (privacy_status = 'creator_visible'::text)) OR ((revision_kind = 'updated'::text) AND (privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text]))) OR ((revision_kind = 'privacy_changed'::text) AND (privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text]))) OR ((revision_kind = 'deleted'::text) AND (privacy_status = 'restricted'::text)))),
    CONSTRAINT life_material_revisions_life_material_revision_id_check CHECK ((uuid_extract_version(life_material_revision_id) = 7)),
    CONSTRAINT life_material_revisions_material_status_check CHECK ((material_status = ANY (ARRAY['active'::text, 'archived'::text]))),
    CONSTRAINT life_material_revisions_metadata_check CHECK (((jsonb_typeof(metadata) = 'object'::text) AND (jsonb_array_length(jsonb_path_query_array(metadata, '$.keyvalue()'::jsonpath)) <= 32))),
    CONSTRAINT life_material_revisions_privacy_status_check CHECK ((privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text, 'shared'::text, 'restricted'::text]))),
    CONSTRAINT life_material_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT life_material_revisions_revision_kind_check CHECK ((revision_kind = ANY (ARRAY['created'::text, 'updated'::text, 'privacy_changed'::text, 'deleted'::text]))),
    CONSTRAINT life_material_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT life_material_revisions_semantic_digest_check CHECK ((semantic_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT life_material_revisions_source_kind_check CHECK ((source_kind = 'subject_cognition'::text)),
    CONSTRAINT life_material_revisions_title_check CHECK (((length(title) >= 1) AND (length(title) <= 256)))
);


--
-- Name: life_materials; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.life_materials (
    life_material_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    material_kind text NOT NULL,
    owner_party_id uuid NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    deleted_at timestamp(6) with time zone,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    updated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT life_materials_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT life_materials_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT life_materials_life_material_id_check CHECK ((uuid_extract_version(life_material_id) = 7)),
    CONSTRAINT life_materials_material_kind_check CHECK ((material_kind = ANY (ARRAY['diary'::text, 'work'::text, 'collection'::text, 'draft'::text]))),
    CONSTRAINT life_materials_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: maintenance_phase_results; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.maintenance_phase_results (
    maintenance_phase_result_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid NOT NULL,
    subject_commit_id uuid NOT NULL,
    maintenance_session_id uuid NOT NULL,
    maintenance_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL,
    phase text NOT NULL,
    outcome text NOT NULL,
    result_summary text NOT NULL,
    creator_visible_problem text,
    memory_id uuid,
    completed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT maintenance_phase_results_check CHECK ((((phase = 'memory_maintenance'::text) AND (outcome = ANY (ARRAY['memory_changed'::text, 'memory_unchanged'::text]))) OR ((phase = 'self_check'::text) AND (outcome = ANY (ARRAY['issue_found'::text, 'no_issue'::text]))))),
    CONSTRAINT maintenance_phase_results_check1 CHECK (((outcome = 'memory_changed'::text) = (memory_id IS NOT NULL))),
    CONSTRAINT maintenance_phase_results_check2 CHECK (((outcome = 'issue_found'::text) = (creator_visible_problem IS NOT NULL))),
    CONSTRAINT maintenance_phase_results_creator_visible_problem_check CHECK (((creator_visible_problem IS NULL) OR ((length(creator_visible_problem) >= 1) AND (length(creator_visible_problem) <= 512)))),
    CONSTRAINT maintenance_phase_results_expected_head_version_check CHECK ((expected_head_version > 0)),
    CONSTRAINT maintenance_phase_results_maintenance_phase_result_id_check CHECK ((uuid_extract_version(maintenance_phase_result_id) = 7)),
    CONSTRAINT maintenance_phase_results_outcome_check CHECK ((outcome = ANY (ARRAY['memory_changed'::text, 'memory_unchanged'::text, 'issue_found'::text, 'no_issue'::text]))),
    CONSTRAINT maintenance_phase_results_phase_check CHECK ((phase = ANY (ARRAY['memory_maintenance'::text, 'self_check'::text]))),
    CONSTRAINT maintenance_phase_results_result_summary_check CHECK (((length(result_summary) >= 1) AND (length(result_summary) <= 512))),
    CONSTRAINT maintenance_phase_results_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: maintenance_session_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.maintenance_session_revisions (
    maintenance_revision_id uuid NOT NULL,
    maintenance_session_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    phase text NOT NULL,
    result_status text NOT NULL,
    transition_kind text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT maintenance_session_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (phase = 'preparing'::text) AND (result_status = 'running'::text) AND (transition_kind = 'started'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT maintenance_session_revisions_check1 CHECK (((phase = 'completed'::text) = (result_status = 'completed'::text))),
    CONSTRAINT maintenance_session_revisions_maintenance_revision_id_check CHECK ((uuid_extract_version(maintenance_revision_id) = 7)),
    CONSTRAINT maintenance_session_revisions_phase_check CHECK ((phase = ANY (ARRAY['preparing'::text, 'memory_maintenance'::text, 'self_check'::text, 'life_quiet'::text, 'resume_check'::text, 'completed'::text]))),
    CONSTRAINT maintenance_session_revisions_result_status_check CHECK ((result_status = ANY (ARRAY['running'::text, 'completed'::text, 'interrupted'::text, 'failed'::text]))),
    CONSTRAINT maintenance_session_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT maintenance_session_revisions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT maintenance_session_revisions_transition_kind_check CHECK ((transition_kind = ANY (ARRAY['started'::text, 'advanced'::text, 'completed'::text, 'interrupted'::text, 'system_failed'::text])))
);


--
-- Name: maintenance_sessions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.maintenance_sessions (
    maintenance_session_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    origin_opportunity_id uuid,
    cycle_anchor_kind text NOT NULL,
    cycle_anchor_ref uuid NOT NULL,
    consideration_at timestamp(6) with time zone NOT NULL,
    deadline_at timestamp(6) with time zone NOT NULL,
    schedule_digest text NOT NULL,
    trigger_kind text NOT NULL,
    sleep_decision_id uuid,
    started_subject_version bigint NOT NULL,
    started_state_epoch bigint NOT NULL,
    current_revision_id uuid,
    head_version bigint DEFAULT 1 NOT NULL,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    finished_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    wake_request_id uuid,
    wake_requested_at timestamp(6) with time zone,
    quiet_until timestamp(6) with time zone,
    CONSTRAINT maintenance_sessions_check CHECK ((consideration_at < deadline_at)),
    CONSTRAINT maintenance_sessions_check1 CHECK (((trigger_kind = 'subject_choice'::text) = (sleep_decision_id IS NOT NULL))),
    CONSTRAINT maintenance_sessions_current_revision_required CHECK ((current_revision_id IS NOT NULL)),
    CONSTRAINT maintenance_sessions_cycle_anchor_kind_check CHECK ((cycle_anchor_kind = ANY (ARRAY['life_generation'::text, 'maintenance_session'::text]))),
    CONSTRAINT maintenance_sessions_cycle_anchor_ref_check CHECK ((uuid_extract_version(cycle_anchor_ref) = 7)),
    CONSTRAINT maintenance_sessions_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT maintenance_sessions_maintenance_session_id_check CHECK ((uuid_extract_version(maintenance_session_id) = 7)),
    CONSTRAINT maintenance_sessions_quiet_window CHECK (((quiet_until IS NULL) OR (quiet_until >= started_at))),
    CONSTRAINT maintenance_sessions_schedule_digest_check CHECK ((schedule_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT maintenance_sessions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT maintenance_sessions_started_state_epoch_check CHECK ((started_state_epoch >= 0)),
    CONSTRAINT maintenance_sessions_started_subject_version_check CHECK ((started_subject_version >= 0)),
    CONSTRAINT maintenance_sessions_trigger_kind_check CHECK ((trigger_kind = ANY (ARRAY['subject_choice'::text, 'system_deadline'::text]))),
    CONSTRAINT maintenance_sessions_wake_request_id_check CHECK (((wake_request_id IS NULL) OR (uuid_extract_version(wake_request_id) = 7))),
    CONSTRAINT maintenance_sessions_wake_request_shape CHECK (((wake_request_id IS NULL) = (wake_requested_at IS NULL)))
);


--
-- Name: memory_relations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.memory_relations (
    memory_relation_id uuid NOT NULL,
    from_memory_id uuid NOT NULL,
    from_memory_revision_id uuid NOT NULL,
    to_memory_id uuid NOT NULL,
    relation_kind text NOT NULL,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT memory_relations_check CHECK ((from_memory_id <> to_memory_id)),
    CONSTRAINT memory_relations_memory_relation_id_check CHECK ((uuid_extract_version(memory_relation_id) = 7)),
    CONSTRAINT memory_relations_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT memory_relations_relation_kind_check CHECK ((relation_kind = ANY (ARRAY['supports'::text, 'contradicts'::text, 'reinterprets'::text])))
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
    provider_request_digest text,
    provider_model_id text,
    result_artifact_id uuid,
    result_digest text,
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
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT observation_attempts_attempt_no_check CHECK (((attempt_no >= 1) AND (attempt_no <= 2))),
    CONSTRAINT observation_attempts_binding_id_check CHECK ((binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'::text)),
    CONSTRAINT observation_attempts_check CHECK ((((dispatch_state = 'prepared'::text) AND (result_status IS NULL) AND (provider_request_digest IS NULL) AND (provider_model_id IS NULL) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (web_search_calls IS NULL) AND (citation_count IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL) AND (dispatched_at IS NULL) AND (settled_at IS NULL)) OR ((dispatch_state = 'dispatched'::text) AND (result_status IS NULL) AND (provider_request_digest IS NULL) AND (provider_model_id IS NULL) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (web_search_calls IS NULL) AND (citation_count IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status = 'cancelled'::text) AND (settled_at IS NOT NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'outcome_unknown'::text])) AND (dispatched_at IS NOT NULL) AND (settled_at IS NOT NULL)))),
    CONSTRAINT observation_attempts_check1 CHECK ((((result_status = 'succeeded'::text) AND (provider_request_digest IS NOT NULL) AND (provider_model_id IS NOT NULL) AND (result_artifact_id IS NOT NULL) AND (result_digest IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (web_search_calls IS NOT NULL) AND (citation_count IS NOT NULL) AND (estimated_cost_microyuan IS NOT NULL) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'outcome_unknown'::text])) AND (error_code IS NOT NULL) AND (result_artifact_id IS NULL) AND (result_digest IS NULL)) OR (result_status IS NULL) OR ((result_status = 'cancelled'::text) AND (result_artifact_id IS NULL) AND (result_digest IS NULL)))),
    CONSTRAINT observation_attempts_citation_count_check CHECK (((citation_count IS NULL) OR ((citation_count >= 1) AND (citation_count <= 128)))),
    CONSTRAINT observation_attempts_credential_identity_check CHECK ((credential_identity ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT observation_attempts_dispatch_state_check CHECK ((dispatch_state = ANY (ARRAY['prepared'::text, 'dispatched'::text, 'settled'::text]))),
    CONSTRAINT observation_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^WEB-[A-Z0-9-]+$'::text))),
    CONSTRAINT observation_attempts_estimated_cost_microyuan_check CHECK (((estimated_cost_microyuan IS NULL) OR ((estimated_cost_microyuan >= 0) AND (estimated_cost_microyuan <= 1000000)))),
    CONSTRAINT observation_attempts_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens > 0))),
    CONSTRAINT observation_attempts_observation_attempt_id_check CHECK ((uuid_extract_version(observation_attempt_id) = 7)),
    CONSTRAINT observation_attempts_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens > 0))),
    CONSTRAINT observation_attempts_provider_model_id_check CHECK (((provider_model_id IS NULL) OR (provider_model_id ~ '^doubao-seed-evolving[a-z0-9-]*$'::text))),
    CONSTRAINT observation_attempts_provider_request_digest_check CHECK (((provider_request_digest IS NULL) OR (provider_request_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT observation_attempts_result_digest_check CHECK (((result_digest IS NULL) OR (result_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT observation_attempts_result_status_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'outcome_unknown'::text, 'cancelled'::text])))),
    CONSTRAINT observation_attempts_schema_version_check CHECK ((schema_version = 1)),
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
    provider_identity_digest text NOT NULL,
    action_digest text NOT NULL,
    completion_status text NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT observation_tool_calls_action_digest_check CHECK ((action_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT observation_tool_calls_action_type_check CHECK ((action_type = ANY (ARRAY['search'::text, 'open_page'::text, 'find_in_page'::text]))),
    CONSTRAINT observation_tool_calls_call_no_check CHECK (((call_no >= 1) AND (call_no <= 8))),
    CONSTRAINT observation_tool_calls_completion_status_check CHECK ((completion_status = 'completed'::text)),
    CONSTRAINT observation_tool_calls_observation_tool_call_id_check CHECK ((uuid_extract_version(observation_tool_call_id) = 7)),
    CONSTRAINT observation_tool_calls_provider_identity_digest_check CHECK ((provider_identity_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT observation_tool_calls_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: opportunities; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.opportunities (
    opportunity_id uuid NOT NULL,
    evidence_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid,
    creator_party_id uuid,
    purpose text NOT NULL,
    eligibility_status text NOT NULL,
    current_disposition text NOT NULL,
    available_after timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    expires_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    selected_at timestamp(6) with time zone,
    root_opportunity_id uuid NOT NULL,
    predecessor_opportunity_id uuid,
    reconsideration_no smallint DEFAULT 0 NOT NULL,
    resolved_at timestamp(6) with time zone,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_version bigint NOT NULL,
    source_digest text NOT NULL,
    activity_id uuid,
    other_party_id uuid,
    CONSTRAINT opportunities_current_disposition_check CHECK ((current_disposition = ANY (ARRAY['open'::text, 'selected'::text, 'resolved'::text, 'superseded'::text, 'cancelled'::text]))),
    CONSTRAINT opportunities_eligibility_status_check CHECK ((eligibility_status = 'eligible'::text)),
    CONSTRAINT opportunities_expiry_check CHECK (((expires_at IS NULL) OR (expires_at > available_after))),
    CONSTRAINT opportunities_lineage_check CHECK ((((reconsideration_no = 0) AND (root_opportunity_id = opportunity_id) AND (predecessor_opportunity_id IS NULL)) OR ((reconsideration_no = 1) AND (root_opportunity_id <> opportunity_id) AND (predecessor_opportunity_id IS NOT NULL)))),
    CONSTRAINT opportunities_opportunity_id_check CHECK ((uuid_extract_version(opportunity_id) = 7)),
    CONSTRAINT opportunities_purpose_check CHECK ((purpose = ANY (ARRAY['consider_creator_input'::text, 'consider_web_evidence'::text, 'consider_codex_task'::text, 'consider_codex_result'::text, 'consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'consider_life_query_result'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_creator_outreach'::text, 'consider_other_human_input'::text]))),
    CONSTRAINT opportunities_reconsideration_check CHECK (((reconsideration_no >= 0) AND (reconsideration_no <= 1))),
    CONSTRAINT opportunities_resolution_state_check CHECK ((((current_disposition = 'open'::text) AND (selected_at IS NULL) AND (resolved_at IS NULL)) OR ((current_disposition = 'selected'::text) AND (selected_at IS NOT NULL) AND (resolved_at IS NULL)) OR ((current_disposition = ANY (ARRAY['resolved'::text, 'superseded'::text])) AND (selected_at IS NOT NULL) AND (resolved_at IS NOT NULL)) OR ((current_disposition = 'cancelled'::text) AND (resolved_at IS NOT NULL)))),
    CONSTRAINT opportunities_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT opportunities_source_digest_check CHECK ((source_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT opportunities_source_kind_check CHECK ((source_kind = ANY (ARRAY['external_evidence'::text, 'life_generation_available'::text, 'subject_component_revision'::text, 'activity_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text, 'life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_activity'::text, 'creator_outreach_relationship'::text]))),
    CONSTRAINT opportunities_source_shape_check CHECK ((((source_kind = 'external_evidence'::text) AND (evidence_id = source_ref) AND (scene_id IS NOT NULL) AND (activity_id IS NULL) AND (((creator_party_id IS NOT NULL) AND (other_party_id IS NULL)) OR ((creator_party_id IS NULL) AND (other_party_id IS NOT NULL)))) OR ((source_kind = ANY (ARRAY['life_generation_available'::text, 'subject_component_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text])) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (creator_party_id IS NULL) AND (other_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = 'activity_revision'::text) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (creator_party_id IS NULL) AND (other_party_id IS NULL) AND (activity_id IS NOT NULL)) OR ((source_kind = 'life_query_result'::text) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (creator_party_id IS NOT NULL) AND (other_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = ANY (ARRAY['creator_outreach_absence'::text, 'creator_outreach_relationship'::text])) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (creator_party_id IS NOT NULL) AND (other_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = 'creator_outreach_activity'::text) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (creator_party_id IS NOT NULL) AND (other_party_id IS NULL) AND (activity_id IS NOT NULL)))),
    CONSTRAINT opportunities_source_version_check CHECK ((source_version > 0))
);


--
-- Name: other_human_action_intent_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_action_intent_revisions (
    other_human_action_intent_revision_id uuid CONSTRAINT other_human_action_intent_r_other_human_action_intent__not_null NOT NULL,
    other_human_action_intent_id uuid CONSTRAINT other_human_action_intent__other_human_action_intent__not_null1 NOT NULL,
    revision_no bigint NOT NULL,
    response_artifact_id uuid CONSTRAINT other_human_action_intent_revisio_response_artifact_id_not_null NOT NULL,
    response_digest text NOT NULL,
    response_bytes integer NOT NULL,
    media_type text NOT NULL,
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text NOT NULL,
    data_scope text NOT NULL,
    purpose text NOT NULL,
    candidate_validation_id uuid CONSTRAINT other_human_action_intent_revi_candidate_validation_id_not_null NOT NULL,
    proposal_ref text NOT NULL,
    subject_commit_id uuid NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_action_intent_re_other_human_action_intent_re_check CHECK ((uuid_extract_version(other_human_action_intent_revision_id) = 7)),
    CONSTRAINT other_human_action_intent_revisions_audience_scope_check CHECK ((audience_scope = 'other_human'::text)),
    CONSTRAINT other_human_action_intent_revisions_capability_kind_check CHECK ((capability_kind = 'local.other-human-inbox.deliver'::text)),
    CONSTRAINT other_human_action_intent_revisions_data_scope_check CHECK ((data_scope = 'declared_party_response'::text)),
    CONSTRAINT other_human_action_intent_revisions_media_type_check CHECK ((media_type = 'text/plain'::text)),
    CONSTRAINT other_human_action_intent_revisions_operation_class_check CHECK ((operation_class = 'deliver_local'::text)),
    CONSTRAINT other_human_action_intent_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT other_human_action_intent_revisions_purpose_check CHECK ((purpose = 'respond_to_other_human'::text)),
    CONSTRAINT other_human_action_intent_revisions_response_bytes_check CHECK (((response_bytes >= 1) AND (response_bytes <= 65536))),
    CONSTRAINT other_human_action_intent_revisions_response_digest_check CHECK ((response_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_action_intent_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT other_human_action_intent_revisions_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: other_human_action_intents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_action_intents (
    other_human_action_intent_id uuid CONSTRAINT other_human_action_intents_other_human_action_intent_i_not_null NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    root_opportunity_id uuid NOT NULL,
    purpose text NOT NULL,
    current_revision_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_action_intents_other_human_action_intent_id_check CHECK ((uuid_extract_version(other_human_action_intent_id) = 7)),
    CONSTRAINT other_human_action_intents_purpose_check CHECK ((purpose = 'respond_to_other_human'::text)),
    CONSTRAINT other_human_action_intents_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: other_human_dialogue_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_dialogue_decisions (
    other_human_dialogue_decision_id uuid CONSTRAINT other_human_dialogue_decisi_other_human_dialogue_decis_not_null NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid,
    subject_commit_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    decision_kind text NOT NULL,
    action_intent_id uuid,
    effect_id uuid,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_dialogue_decisio_other_human_dialogue_decisio_check CHECK ((uuid_extract_version(other_human_dialogue_decision_id) = 7)),
    CONSTRAINT other_human_dialogue_decisions_check CHECK ((((decision_kind = 'reply'::text) AND (subject_commit_id IS NOT NULL) AND (candidate_application_id IS NULL) AND (action_intent_id IS NOT NULL) AND (effect_id IS NOT NULL)) OR ((decision_kind = 'end_conversation'::text) AND (subject_commit_id IS NOT NULL) AND (candidate_application_id IS NULL) AND (action_intent_id IS NULL) AND (effect_id IS NULL)) OR ((decision_kind = ANY (ARRAY['silence'::text, 'defer'::text])) AND (action_intent_id IS NULL) AND (effect_id IS NULL) AND (((subject_commit_id IS NULL) AND (candidate_application_id IS NOT NULL)) OR ((subject_commit_id IS NOT NULL) AND (candidate_application_id IS NULL)))))),
    CONSTRAINT other_human_dialogue_decisions_decision_kind_check CHECK ((decision_kind = ANY (ARRAY['reply'::text, 'silence'::text, 'defer'::text, 'end_conversation'::text]))),
    CONSTRAINT other_human_dialogue_decisions_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: other_human_effects; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_effects (
    other_human_effect_id uuid NOT NULL,
    action_intent_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    status text NOT NULL,
    registration_digest text NOT NULL,
    settlement_digest text,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    settled_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_effects_check CHECK ((((status = 'registered'::text) AND (settlement_digest IS NULL) AND (settled_at IS NULL)) OR ((status <> 'registered'::text) AND (settlement_digest IS NOT NULL) AND (settled_at IS NOT NULL)))),
    CONSTRAINT other_human_effects_other_human_effect_id_check CHECK ((uuid_extract_version(other_human_effect_id) = 7)),
    CONSTRAINT other_human_effects_payload_bytes_check CHECK (((payload_bytes >= 1) AND (payload_bytes <= 65536))),
    CONSTRAINT other_human_effects_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_effects_registration_digest_check CHECK ((registration_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_effects_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT other_human_effects_settlement_digest_check CHECK (((settlement_digest IS NULL) OR (settlement_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT other_human_effects_status_check CHECK ((status = ANY (ARRAY['registered'::text, 'completed'::text, 'failed'::text, 'unknown'::text])))
);


--
-- Name: other_human_input_interactions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_input_interactions (
    other_human_interaction_id uuid CONSTRAINT other_human_input_interacti_other_human_interaction_id_not_null NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    purpose text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    content_digest text NOT NULL,
    trace_id text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_input_interactions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_input_interactions_idempotency_key_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT other_human_input_interactions_other_human_interaction_id_check CHECK ((uuid_extract_version(other_human_interaction_id) = 7)),
    CONSTRAINT other_human_input_interactions_purpose_check CHECK ((purpose = 'other_human_message'::text)),
    CONSTRAINT other_human_input_interactions_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_input_interactions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT other_human_input_interactions_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);


--
-- Name: other_human_local_inbox_deliveries; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.other_human_local_inbox_deliveries (
    other_human_local_inbox_delivery_id uuid CONSTRAINT other_human_local_inbox_del_other_human_local_inbox_de_not_null NOT NULL,
    other_human_effect_id uuid CONSTRAINT other_human_local_inbox_deliveri_other_human_effect_id_not_null NOT NULL,
    scene_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    receipt_digest text NOT NULL,
    delivered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT other_human_local_inbox_deli_other_human_local_inbox_deli_check CHECK ((uuid_extract_version(other_human_local_inbox_delivery_id) = 7)),
    CONSTRAINT other_human_local_inbox_deliveries_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_local_inbox_deliveries_receipt_digest_check CHECK ((receipt_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT other_human_local_inbox_deliveries_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: outbox_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.outbox_items (
    outbox_item_id uuid NOT NULL,
    work_id uuid NOT NULL,
    message_kind text NOT NULL,
    payload_digest text NOT NULL,
    status text DEFAULT 'ready'::text NOT NULL,
    available_at timestamp(6) with time zone NOT NULL,
    claimed_by uuid,
    claim_expires_at timestamp(6) with time zone,
    claim_token bigint DEFAULT 0 NOT NULL,
    attempt_count smallint DEFAULT 0 NOT NULL,
    max_attempts smallint NOT NULL,
    last_error_code text,
    delivered_at timestamp(6) with time zone,
    trace_id text NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT outbox_items_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT outbox_items_check CHECK ((attempt_count <= max_attempts)),
    CONSTRAINT outbox_items_check1 CHECK ((((status = 'claimed'::text) AND (claimed_by IS NOT NULL) AND (claim_expires_at IS NOT NULL) AND (claim_token > 0) AND (attempt_count > 0)) OR ((status <> 'claimed'::text) AND (claimed_by IS NULL) AND (claim_expires_at IS NULL)))),
    CONSTRAINT outbox_items_check2 CHECK ((((status = 'delivered'::text) AND (delivered_at IS NOT NULL)) OR ((status <> 'delivered'::text) AND (delivered_at IS NULL)))),
    CONSTRAINT outbox_items_claim_token_check CHECK ((claim_token >= 0)),
    CONSTRAINT outbox_items_claimed_by_check CHECK (((claimed_by IS NULL) OR (uuid_extract_version(claimed_by) = 7))),
    CONSTRAINT outbox_items_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^[A-Z][A-Z0-9-]{0,127}$'::text))),
    CONSTRAINT outbox_items_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 100))),
    CONSTRAINT outbox_items_message_kind_check CHECK ((message_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT outbox_items_outbox_item_id_check CHECK ((uuid_extract_version(outbox_item_id) = 7)),
    CONSTRAINT outbox_items_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT outbox_items_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT outbox_items_status_check CHECK ((status = ANY (ARRAY['ready'::text, 'claimed'::text, 'delivered'::text, 'dead'::text]))),
    CONSTRAINT outbox_items_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);


--
-- Name: parties; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.parties (
    party_id uuid NOT NULL,
    party_kind text NOT NULL,
    represented_subject_id uuid,
    display_label text,
    creator_role text,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    declared_identity_key text,
    CONSTRAINT parties_display_label_check CHECK ((((party_kind = ANY (ARRAY['subject'::text, 'creator'::text])) AND (display_label IS NULL)) OR ((party_kind = 'other_human'::text) AND ((length(btrim(display_label)) >= 1) AND (length(btrim(display_label)) <= 256))))),
    CONSTRAINT parties_party_id_check CHECK ((uuid_extract_version(party_id) = 7)),
    CONSTRAINT parties_party_kind_check CHECK ((party_kind = ANY (ARRAY['subject'::text, 'creator'::text, 'other_human'::text]))),
    CONSTRAINT parties_role_shape_check CHECK ((((party_kind = 'subject'::text) AND (represented_subject_id IS NOT NULL) AND (creator_role IS NULL) AND (declared_identity_key IS NULL)) OR ((party_kind = 'creator'::text) AND (represented_subject_id IS NULL) AND (creator_role = 'unique_primary_creator'::text) AND (declared_identity_key IS NULL)) OR ((party_kind = 'other_human'::text) AND (represented_subject_id IS NULL) AND (creator_role IS NULL) AND (declared_identity_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)))),
    CONSTRAINT parties_status_check CHECK ((status = 'active'::text))
);


--
-- Name: permission_grants; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.permission_grants (
    grant_id uuid NOT NULL,
    capability_request_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    interaction_scene_id uuid NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    valid_from timestamp(6) with time zone NOT NULL,
    valid_until timestamp(6) with time zone NOT NULL,
    max_uses integer NOT NULL,
    consumed_uses integer DEFAULT 0 NOT NULL,
    max_payload_bytes integer,
    scope_digest text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revoked_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    workspace_scope text,
    artifact_scope text,
    network_access boolean,
    CONSTRAINT permission_grants_digest_chk CHECK ((scope_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT permission_grants_id_v7_chk CHECK (("substring"((grant_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT permission_grants_revoked_chk CHECK ((((status = 'active'::text) AND (revoked_at IS NULL)) OR ((status = ANY (ARRAY['revoked'::text, 'expired'::text])) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT permission_grants_schema_chk CHECK ((schema_version = 1)),
    CONSTRAINT permission_grants_scope_chk CHECK ((((operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (workspace_scope IS NULL) AND (artifact_scope IS NULL) AND (network_access IS NULL) AND (valid_until > valid_from) AND (valid_until <= (valid_from + '7 days'::interval)) AND ((max_uses >= 1) AND (max_uses <= 16)) AND ((consumed_uses >= 0) AND (consumed_uses <= max_uses)) AND ((max_payload_bytes >= 1) AND (max_payload_bytes <= 65536))) OR ((operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (workspace_scope = 'isolated_ephemeral'::text) AND (artifact_scope = 'explicit_only'::text) AND (network_access = false) AND (valid_until > valid_from) AND (valid_until <= (valid_from + '01:00:00'::interval)) AND (max_uses = 1) AND ((consumed_uses >= 0) AND (consumed_uses <= 1)) AND (max_payload_bytes IS NULL)))),
    CONSTRAINT permission_grants_status_chk CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text, 'expired'::text])))
);


--
-- Name: policy_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.policy_decisions (
    policy_decision_id uuid NOT NULL,
    action_intent_revision_id uuid NOT NULL,
    creator_response_operation_id uuid NOT NULL,
    matched_grant_id uuid,
    decision_outcome text NOT NULL,
    policy_identity text NOT NULL,
    decision_digest text NOT NULL,
    reason_code text NOT NULL,
    supersedes_policy_decision_id uuid,
    is_current boolean DEFAULT true NOT NULL,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    valid_until timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT policy_decisions_check CHECK (((decision_outcome = 'allowed'::text) = (matched_grant_id IS NOT NULL))),
    CONSTRAINT policy_decisions_check1 CHECK (((valid_until IS NULL) OR (valid_until > decided_at))),
    CONSTRAINT policy_decisions_check2 CHECK (((supersedes_policy_decision_id IS NULL) OR (supersedes_policy_decision_id <> policy_decision_id))),
    CONSTRAINT policy_decisions_decision_digest_check CHECK ((decision_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT policy_decisions_decision_outcome_check CHECK ((decision_outcome = ANY (ARRAY['allowed'::text, 'denied'::text, 'confirmation_required'::text, 'unavailable'::text]))),
    CONSTRAINT policy_decisions_policy_decision_id_check CHECK ((uuid_extract_version(policy_decision_id) = 7)),
    CONSTRAINT policy_decisions_policy_identity_check CHECK ((policy_identity = 'armi.policy-engine.deterministic-v1'::text)),
    CONSTRAINT policy_decisions_reason_code_check CHECK ((reason_code ~ '^POLICY-[A-Z0-9-]+$'::text)),
    CONSTRAINT policy_decisions_schema_version_check CHECK ((schema_version = 1))
);


--
-- Name: prompt_documents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.prompt_documents (
    prompt_document_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    prompt_kind text NOT NULL,
    write_authority text NOT NULL,
    current_revision_id uuid,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT prompt_documents_check CHECK ((((prompt_kind = 'personality_anchor'::text) AND (write_authority = 'fixed'::text)) OR ((prompt_kind = 'creator_guidance'::text) AND (write_authority = 'creator'::text)) OR ((prompt_kind = 'subject_guidance'::text) AND (write_authority = 'subject'::text)))),
    CONSTRAINT prompt_documents_check1 CHECK ((((prompt_kind = 'personality_anchor'::text) AND (status = 'active'::text) AND (current_revision_id IS NOT NULL)) OR (prompt_kind <> 'personality_anchor'::text))),
    CONSTRAINT prompt_documents_check2 CHECK (((status = 'active'::text) OR (current_revision_id IS NOT NULL))),
    CONSTRAINT prompt_documents_prompt_document_id_check CHECK ((uuid_extract_version(prompt_document_id) = 7)),
    CONSTRAINT prompt_documents_prompt_kind_check CHECK ((prompt_kind = ANY (ARRAY['personality_anchor'::text, 'creator_guidance'::text, 'subject_guidance'::text]))),
    CONSTRAINT prompt_documents_status_check CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text]))),
    CONSTRAINT prompt_documents_write_authority_check CHECK ((write_authority = ANY (ARRAY['fixed'::text, 'creator'::text, 'subject'::text])))
);


--
-- Name: prompt_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.prompt_revisions (
    prompt_revision_id uuid NOT NULL,
    prompt_document_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    content_artifact_id uuid NOT NULL,
    content_digest text NOT NULL,
    author_party_id uuid NOT NULL,
    subject_commit_id uuid,
    change_reason text NOT NULL,
    activated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT prompt_revisions_change_reason_check CHECK ((change_reason = ANY (ARRAY['birth'::text, 'created'::text, 'revised'::text, 'deactivated'::text, 'subject_created'::text, 'subject_revised'::text]))),
    CONSTRAINT prompt_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT prompt_revisions_check1 CHECK ((((change_reason = 'birth'::text) AND (revision_no = 1)) OR (change_reason <> 'birth'::text))),
    CONSTRAINT prompt_revisions_check2 CHECK ((((change_reason = ANY (ARRAY['subject_created'::text, 'subject_revised'::text])) AND (subject_commit_id IS NOT NULL)) OR ((change_reason <> ALL (ARRAY['subject_created'::text, 'subject_revised'::text])) AND (subject_commit_id IS NULL)))),
    CONSTRAINT prompt_revisions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT prompt_revisions_prompt_revision_id_check CHECK ((uuid_extract_version(prompt_revision_id) = 7)),
    CONSTRAINT prompt_revisions_revision_no_check CHECK ((revision_no >= 1))
);


--
-- Name: relationship_experience_links; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationship_experience_links (
    relationship_revision_id uuid NOT NULL,
    experience_id uuid NOT NULL,
    link_kind text NOT NULL,
    ordinal smallint NOT NULL,
    CONSTRAINT relationship_experience_links_link_kind_check CHECK ((link_kind = ANY (ARRAY['supports_relationship_change'::text, 'supports_commitment_event'::text]))),
    CONSTRAINT relationship_experience_links_ordinal_check CHECK ((ordinal > 0))
);


--
-- Name: relationship_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationship_revisions (
    relationship_revision_id uuid NOT NULL,
    relationship_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    facts jsonb NOT NULL,
    interpretation text NOT NULL,
    boundaries jsonb NOT NULL,
    commitments jsonb NOT NULL,
    open_issues jsonb NOT NULL,
    commitment_event jsonb,
    relationship_status text NOT NULL,
    semantic_digest text NOT NULL,
    mechanism_identity text NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT relationship_revisions_boundaries_check CHECK (((jsonb_typeof(boundaries) = 'array'::text) AND (jsonb_array_length(boundaries) <= 16))),
    CONSTRAINT relationship_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT relationship_revisions_commitment_event_check CHECK (((commitment_event IS NULL) OR (jsonb_typeof(commitment_event) = 'object'::text))),
    CONSTRAINT relationship_revisions_commitments_check CHECK (((jsonb_typeof(commitments) = 'array'::text) AND (jsonb_array_length(commitments) <= 16))),
    CONSTRAINT relationship_revisions_facts_check CHECK (((jsonb_typeof(facts) = 'array'::text) AND ((jsonb_array_length(facts) >= 1) AND (jsonb_array_length(facts) <= 64)))),
    CONSTRAINT relationship_revisions_interpretation_check CHECK (((length(interpretation) >= 1) AND (length(interpretation) <= 1024))),
    CONSTRAINT relationship_revisions_mechanism_identity_check CHECK ((mechanism_identity = 'armi.relationship.contextual-v1'::text)),
    CONSTRAINT relationship_revisions_open_issues_check CHECK (((jsonb_typeof(open_issues) = 'array'::text) AND (jsonb_array_length(open_issues) <= 32))),
    CONSTRAINT relationship_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT relationship_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT relationship_revisions_relationship_revision_id_check CHECK ((uuid_extract_version(relationship_revision_id) = 7)),
    CONSTRAINT relationship_revisions_relationship_status_check CHECK ((relationship_status = ANY (ARRAY['active'::text, 'ended'::text]))),
    CONSTRAINT relationship_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT relationship_revisions_semantic_digest_check CHECK ((semantic_digest ~ '^sha256:[0-9a-f]{64}$'::text))
);


--
-- Name: relationships; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationships (
    relationship_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    scope text NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT relationships_check CHECK ((subject_party_id <> other_party_id)),
    CONSTRAINT relationships_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT relationships_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT relationships_relationship_id_check CHECK ((uuid_extract_version(relationship_id) = 7)),
    CONSTRAINT relationships_scope_check CHECK ((scope = ANY (ARRAY['creator_social'::text, 'other_human_social'::text])))
);


--
-- Name: runtime_bundle_activations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_bundle_activations (
    bundle_activation_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    bundle_version text NOT NULL,
    bundle_digest text NOT NULL,
    manifest_artifact_id uuid NOT NULL,
    fixed_policy_digest text NOT NULL,
    fixed_prompt_set_digest text NOT NULL,
    creator_asset_digest text NOT NULL,
    model_binding text,
    status text NOT NULL,
    activated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    deactivated_at timestamp(6) with time zone,
    activated_by_party_id uuid NOT NULL,
    CONSTRAINT runtime_bundle_activations_bundle_activation_id_check CHECK ((uuid_extract_version(bundle_activation_id) = 7)),
    CONSTRAINT runtime_bundle_activations_bundle_digest_check CHECK ((bundle_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT runtime_bundle_activations_bundle_version_check CHECK ((bundle_version = '0.0.0'::text)),
    CONSTRAINT runtime_bundle_activations_check CHECK ((((status = 'current'::text) AND (deactivated_at IS NULL)) OR ((status = 'superseded'::text) AND (deactivated_at IS NOT NULL)))),
    CONSTRAINT runtime_bundle_activations_creator_asset_digest_check CHECK ((creator_asset_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT runtime_bundle_activations_fixed_policy_digest_check CHECK ((fixed_policy_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT runtime_bundle_activations_fixed_prompt_set_digest_check CHECK ((fixed_prompt_set_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT runtime_bundle_activations_model_binding_check CHECK ((model_binding IS NULL)),
    CONSTRAINT runtime_bundle_activations_status_check CHECK ((status = ANY (ARRAY['current'::text, 'superseded'::text])))
);


--
-- Name: runtime_instances; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_instances (
    runtime_instance_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    bundle_activation_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    status text NOT NULL,
    started_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    last_heartbeat_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    lease_expires_at timestamp(6) with time zone NOT NULL,
    stopped_at timestamp(6) with time zone,
    schema_version integer DEFAULT 1 NOT NULL,
    CONSTRAINT runtime_instances_check CHECK ((lease_expires_at > last_heartbeat_at)),
    CONSTRAINT runtime_instances_check1 CHECK ((((status = 'active'::text) AND (stopped_at IS NULL)) OR ((status = ANY (ARRAY['fenced'::text, 'stopped'::text])) AND (stopped_at IS NOT NULL)))),
    CONSTRAINT runtime_instances_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT runtime_instances_runtime_instance_id_check CHECK ((uuid_extract_version(runtime_instance_id) = 7)),
    CONSTRAINT runtime_instances_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT runtime_instances_status_check CHECK ((status = ANY (ARRAY['active'::text, 'fenced'::text, 'stopped'::text])))
);


--
-- Name: runtime_recovery_runs; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_recovery_runs (
    recovery_run_id uuid NOT NULL,
    runtime_instance_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    bundle_activation_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    status text NOT NULL,
    started_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    requeued_work_count integer DEFAULT 0 NOT NULL,
    terminal_work_count integer DEFAULT 0 NOT NULL,
    requeued_outbox_count integer DEFAULT 0 NOT NULL,
    dead_outbox_count integer DEFAULT 0 NOT NULL,
    resumable_work_count integer DEFAULT 0 NOT NULL,
    resumable_outbox_count integer DEFAULT 0 NOT NULL,
    critical_artifact_count integer DEFAULT 0 NOT NULL,
    blocker_count integer DEFAULT 0 NOT NULL,
    summary_digest text,
    schema_version smallint DEFAULT 1 NOT NULL,
    resumable_opportunity_count integer DEFAULT 0 NOT NULL,
    resumable_cognitive_episode_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_cognitive_episode_coun_not_null NOT NULL,
    resumable_model_attempt_count integer DEFAULT 0 NOT NULL,
    resumable_candidate_validation_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_candidate_validation_c_not_null NOT NULL,
    resumable_subject_commit_count integer DEFAULT 0 NOT NULL,
    resumable_capability_request_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_capability_request_cou_not_null NOT NULL,
    resumable_response_operation_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_response_operation_cou_not_null NOT NULL,
    resumable_effect_count integer DEFAULT 0 NOT NULL,
    resumable_effect_outbox_count integer DEFAULT 0 NOT NULL,
    resumable_effect_attempt_count integer DEFAULT 0 NOT NULL,
    reliable_effect_observation_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_reliable_effect_observation_coun_not_null NOT NULL,
    creator_response_delivery_count integer DEFAULT 0 NOT NULL,
    resumable_web_observation_count integer DEFAULT 0 NOT NULL,
    unknown_web_observation_attempt_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_unknown_web_observation_attempt__not_null NOT NULL,
    resumable_web_research_intent_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_web_research_intent_co_not_null NOT NULL,
    pending_web_evidence_acceptance_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_pending_web_evidence_acceptance__not_null NOT NULL,
    resumable_web_cognition_count integer DEFAULT 0 NOT NULL,
    resumable_admin_correction_work_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_resumable_admin_correction_work__not_null NOT NULL,
    resumable_codex_task_count integer DEFAULT 0 NOT NULL,
    resumable_codex_effect_count integer DEFAULT 0 NOT NULL,
    pending_codex_result_acceptance_count integer DEFAULT 0 CONSTRAINT runtime_recovery_runs_pending_codex_result_acceptance__not_null NOT NULL,
    CONSTRAINT runtime_recovery_runs_blocker_count_check CHECK ((blocker_count >= 0)),
    CONSTRAINT runtime_recovery_runs_check CHECK ((((status = 'running'::text) AND (completed_at IS NULL) AND (summary_digest IS NULL)) OR ((status = ANY (ARRAY['safe'::text, 'blocked'::text, 'abandoned'::text])) AND (completed_at IS NOT NULL) AND (summary_digest IS NOT NULL)))),
    CONSTRAINT runtime_recovery_runs_check1 CHECK (((status <> 'safe'::text) OR (blocker_count = 0))),
    CONSTRAINT runtime_recovery_runs_check2 CHECK (((status <> 'blocked'::text) OR (blocker_count > 0))),
    CONSTRAINT runtime_recovery_runs_creator_response_delivery_count_check CHECK ((creator_response_delivery_count >= 0)),
    CONSTRAINT runtime_recovery_runs_critical_artifact_count_check CHECK ((critical_artifact_count >= 0)),
    CONSTRAINT runtime_recovery_runs_dead_outbox_count_check CHECK ((dead_outbox_count >= 0)),
    CONSTRAINT runtime_recovery_runs_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT runtime_recovery_runs_pending_codex_result_acceptance_cou_check CHECK ((pending_codex_result_acceptance_count >= 0)),
    CONSTRAINT runtime_recovery_runs_pending_web_evidence_acceptance_cou_check CHECK ((pending_web_evidence_acceptance_count >= 0)),
    CONSTRAINT runtime_recovery_runs_recovery_run_id_check CHECK ((uuid_extract_version(recovery_run_id) = 7)),
    CONSTRAINT runtime_recovery_runs_reliable_effect_observation_count_check CHECK ((reliable_effect_observation_count >= 0)),
    CONSTRAINT runtime_recovery_runs_requeued_outbox_count_check CHECK ((requeued_outbox_count >= 0)),
    CONSTRAINT runtime_recovery_runs_requeued_work_count_check CHECK ((requeued_work_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_admin_correction_work_cou_check CHECK ((resumable_admin_correction_work_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_candidate_validation_coun_check CHECK ((resumable_candidate_validation_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_capability_request_count_check CHECK ((resumable_capability_request_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_codex_effect_count_check CHECK ((resumable_codex_effect_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_codex_task_count_check CHECK ((resumable_codex_task_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_cognitive_episode_count_check CHECK ((resumable_cognitive_episode_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_effect_attempt_count_check CHECK ((resumable_effect_attempt_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_effect_count_check CHECK ((resumable_effect_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_effect_outbox_count_check CHECK ((resumable_effect_outbox_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_model_attempt_count_check CHECK ((resumable_model_attempt_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_opportunity_count_check CHECK ((resumable_opportunity_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_outbox_count_check CHECK ((resumable_outbox_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_response_operation_count_check CHECK ((resumable_response_operation_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_subject_commit_count_check CHECK ((resumable_subject_commit_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_web_cognition_count_check CHECK ((resumable_web_cognition_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_web_observation_count_check CHECK ((resumable_web_observation_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_web_research_intent_count_check CHECK ((resumable_web_research_intent_count >= 0)),
    CONSTRAINT runtime_recovery_runs_resumable_work_count_check CHECK ((resumable_work_count >= 0)),
    CONSTRAINT runtime_recovery_runs_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT runtime_recovery_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'safe'::text, 'blocked'::text, 'abandoned'::text]))),
    CONSTRAINT runtime_recovery_runs_summary_digest_check CHECK (((summary_digest IS NULL) OR (summary_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT runtime_recovery_runs_terminal_work_count_check CHECK ((terminal_work_count >= 0)),
    CONSTRAINT runtime_recovery_runs_unknown_web_observation_attempt_cou_check CHECK ((unknown_web_observation_attempt_count >= 0))
);


--
-- Name: scene_timeline_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.scene_timeline_items (
    timeline_item_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    source_kind text NOT NULL,
    source_ref uuid NOT NULL,
    source_event_no bigint NOT NULL,
    result_status text NOT NULL,
    occurred_at timestamp(6) with time zone NOT NULL,
    recorded_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT scene_timeline_items_result_status_check CHECK ((result_status = ANY (ARRAY['accepted'::text, 'applied'::text, 'waiting'::text, 'rejected'::text, 'unavailable'::text, 'failed'::text, 'unknown'::text, 'completed'::text]))),
    CONSTRAINT scene_timeline_items_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT scene_timeline_items_source_event_no_check CHECK ((source_event_no > 0)),
    CONSTRAINT scene_timeline_items_source_kind_check CHECK ((source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT scene_timeline_items_source_ref_check CHECK ((uuid_extract_version(source_ref) = 7)),
    CONSTRAINT scene_timeline_items_timeline_item_id_check CHECK ((uuid_extract_version(timeline_item_id) = 7))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.schema_migrations (
    sequence_no bigint NOT NULL,
    migration_id text NOT NULL,
    migration_kind text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT schema_migrations_check CHECK ((((migration_kind = 'baseline'::text) AND (migration_id = 'baseline'::text)) OR ((migration_kind = 'migration'::text) AND (migration_id ~ '^[0-9]{4}_[a-z0-9_]+$'::text)))),
    CONSTRAINT schema_migrations_checksum_check CHECK ((checksum ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT schema_migrations_migration_id_check CHECK (((migration_id = 'baseline'::text) OR (migration_id ~ '^[0-9]{4}_[a-z0-9_]+$'::text))),
    CONSTRAINT schema_migrations_migration_kind_check CHECK ((migration_kind = ANY (ARRAY['baseline'::text, 'migration'::text])))
);


--
-- Name: schema_migrations_sequence_no_seq; Type: SEQUENCE; Schema: armi; Owner: -
--

ALTER TABLE armi.schema_migrations ALTER COLUMN sequence_no ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME armi.schema_migrations_sequence_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sleep_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.sleep_decisions (
    sleep_decision_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    cycle_anchor_ref uuid NOT NULL,
    source_digest text NOT NULL,
    decision_kind text NOT NULL,
    review_not_before timestamp(6) with time zone,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT sleep_decisions_check CHECK (((decision_kind = 'defer'::text) = (review_not_before IS NOT NULL))),
    CONSTRAINT sleep_decisions_cycle_anchor_ref_check CHECK ((uuid_extract_version(cycle_anchor_ref) = 7)),
    CONSTRAINT sleep_decisions_decision_kind_check CHECK ((decision_kind = ANY (ARRAY['sleep'::text, 'stay_awake'::text, 'defer'::text, 'need_information'::text]))),
    CONSTRAINT sleep_decisions_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT sleep_decisions_sleep_decision_id_check CHECK ((uuid_extract_version(sleep_decision_id) = 7)),
    CONSTRAINT sleep_decisions_source_digest_check CHECK ((source_digest ~ '^sha256:[0-9a-f]{64}$'::text))
);


--
-- Name: subject_commits; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subject_commits (
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    bundle_activation_id uuid NOT NULL,
    base_subject_version bigint NOT NULL,
    new_subject_version bigint NOT NULL,
    base_state_epoch bigint NOT NULL,
    change_set_digest text NOT NULL,
    commit_digest text NOT NULL,
    runtime_instance_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    trace_id text NOT NULL,
    committed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT subject_commits_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT subject_commits_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT subject_commits_change_set_digest_check CHECK ((change_set_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT subject_commits_check CHECK ((new_subject_version = (base_subject_version + 1))),
    CONSTRAINT subject_commits_commit_digest_check CHECK ((commit_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT subject_commits_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT subject_commits_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT subject_commits_subject_commit_id_check CHECK ((uuid_extract_version(subject_commit_id) = 7)),
    CONSTRAINT subject_commits_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32))))
);


--
-- Name: subject_component_heads; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subject_component_heads (
    subject_id uuid NOT NULL,
    component_kind text NOT NULL,
    current_revision_id uuid NOT NULL,
    component_version bigint NOT NULL,
    CONSTRAINT subject_component_heads_component_kind_check CHECK ((component_kind = ANY (ARRAY['self'::text, 'mind'::text, 'life_mode'::text]))),
    CONSTRAINT subject_component_heads_component_version_check CHECK ((component_version > 0))
);


--
-- Name: subject_component_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subject_component_revisions (
    component_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    component_kind text NOT NULL,
    component_version bigint NOT NULL,
    previous_revision_id uuid,
    origin_kind text NOT NULL,
    origin_ref uuid NOT NULL,
    subject_commit_id uuid,
    semantic_payload jsonb NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    proposal_ref text,
    semantic_digest text,
    CONSTRAINT subject_component_revisions_component_kind_check CHECK ((component_kind = ANY (ARRAY['self'::text, 'mind'::text, 'life_mode'::text]))),
    CONSTRAINT subject_component_revisions_component_revision_id_check CHECK ((uuid_extract_version(component_revision_id) = 7)),
    CONSTRAINT subject_component_revisions_component_version_check CHECK ((component_version > 0)),
    CONSTRAINT subject_component_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (component_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL) AND (semantic_digest IS NOT NULL)) OR ((origin_kind = 'admin_correction'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL) AND (semantic_digest IS NOT NULL)))),
    CONSTRAINT subject_component_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text]))),
    CONSTRAINT subject_component_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
    CONSTRAINT subject_component_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT subject_component_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT subject_component_revisions_semantic_digest_check CHECK (((semantic_digest IS NULL) OR (semantic_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT subject_component_revisions_semantic_payload_check CHECK ((jsonb_typeof(semantic_payload) = 'object'::text))
);


--
-- Name: subjective_memories; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subjective_memories (
    memory_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT subjective_memories_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT subjective_memories_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT subjective_memories_memory_id_check CHECK ((uuid_extract_version(memory_id) = 7))
);


--
-- Name: subjective_memory_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subjective_memory_revisions (
    memory_revision_id uuid NOT NULL,
    memory_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    source_experience_id uuid NOT NULL,
    source_kind text NOT NULL,
    source_fact_class text NOT NULL,
    summary text NOT NULL,
    uncertainty text,
    revision_kind text NOT NULL,
    accessibility text NOT NULL,
    mechanism_identity text NOT NULL,
    mechanism_config_identity text NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT subjective_memory_revisions_accessibility_check CHECK ((accessibility = ANY (ARRAY['available'::text, 'faded'::text, 'forgotten'::text]))),
    CONSTRAINT subjective_memory_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (revision_kind = 'formed'::text) AND (accessibility = 'available'::text) AND (mechanism_identity = 'armi.memory-formation.contextual-v1'::text) AND (mechanism_config_identity = 'formation-v1'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL) AND (revision_kind <> 'formed'::text) AND (mechanism_identity = 'armi.memory-revision.contextual-v1'::text) AND (mechanism_config_identity = ANY (ARRAY['natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text]))))),
    CONSTRAINT subjective_memory_revisions_check1 CHECK ((((revision_kind = ANY (ARRAY['formed'::text, 'recalled'::text])) AND (accessibility = 'available'::text)) OR ((revision_kind = 'faded'::text) AND (accessibility = 'faded'::text)) OR ((revision_kind = 'forgotten'::text) AND (accessibility = 'forgotten'::text)) OR ((revision_kind = 'reinterpreted'::text) AND (accessibility = ANY (ARRAY['available'::text, 'faded'::text]))))),
    CONSTRAINT subjective_memory_revisions_check2 CHECK ((((source_kind = 'reported'::text) AND (source_fact_class = 'external_claim'::text)) OR ((source_kind = 'inferred'::text) AND (source_fact_class = 'inference'::text)) OR ((source_kind = 'queried'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text]))) OR ((source_kind = 'unknown'::text) AND (source_fact_class = 'unknown'::text)) OR ((source_kind = 'experienced'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'subjective_understanding'::text]))))),
    CONSTRAINT subjective_memory_revisions_mechanism_config_identity_check CHECK ((mechanism_config_identity = ANY (ARRAY['formation-v1'::text, 'natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text]))),
    CONSTRAINT subjective_memory_revisions_mechanism_identity_check CHECK ((mechanism_identity = ANY (ARRAY['armi.memory-formation.contextual-v1'::text, 'armi.memory-revision.contextual-v1'::text]))),
    CONSTRAINT subjective_memory_revisions_memory_revision_id_check CHECK ((uuid_extract_version(memory_revision_id) = 7)),
    CONSTRAINT subjective_memory_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT subjective_memory_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT subjective_memory_revisions_revision_kind_check CHECK ((revision_kind = ANY (ARRAY['formed'::text, 'recalled'::text, 'faded'::text, 'forgotten'::text, 'reinterpreted'::text]))),
    CONSTRAINT subjective_memory_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT subjective_memory_revisions_source_fact_class_check CHECK ((source_fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT subjective_memory_revisions_source_kind_check CHECK ((source_kind = ANY (ARRAY['experienced'::text, 'reported'::text, 'inferred'::text, 'queried'::text, 'unknown'::text]))),
    CONSTRAINT subjective_memory_revisions_summary_check CHECK (((length(summary) >= 1) AND (length(summary) <= 512))),
    CONSTRAINT subjective_memory_revisions_uncertainty_check CHECK (((uncertainty IS NULL) OR ((length(uncertainty) >= 1) AND (length(uncertainty) <= 512))))
);


--
-- Name: subjects; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subjects (
    subject_id uuid NOT NULL,
    singleton_key smallint NOT NULL,
    birth_request_id uuid NOT NULL,
    birth_idempotency_key text NOT NULL,
    birth_manifest_digest text NOT NULL,
    current_generation_id uuid NOT NULL,
    current_bundle_activation_id uuid NOT NULL,
    subject_version bigint DEFAULT 0 NOT NULL,
    state_epoch bigint DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    born_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT subjects_birth_idempotency_key_check CHECK (((length(birth_idempotency_key) >= 1) AND (length(birth_idempotency_key) <= 128) AND (birth_idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT subjects_birth_manifest_digest_check CHECK ((birth_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT subjects_birth_request_id_check CHECK ((uuid_extract_version(birth_request_id) = 7)),
    CONSTRAINT subjects_current_bundle_activation_id_check CHECK ((uuid_extract_version(current_bundle_activation_id) = 7)),
    CONSTRAINT subjects_current_generation_id_check CHECK ((uuid_extract_version(current_generation_id) = 7)),
    CONSTRAINT subjects_singleton_key_check CHECK ((singleton_key = 1)),
    CONSTRAINT subjects_state_epoch_check CHECK ((state_epoch >= 0)),
    CONSTRAINT subjects_status_check CHECK ((status = ANY (ARRAY['active'::text, 'blocked'::text, 'deceased'::text]))),
    CONSTRAINT subjects_subject_id_check CHECK ((uuid_extract_version(subject_id) = 7)),
    CONSTRAINT subjects_subject_version_check CHECK ((subject_version >= 0))
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
    title_digest text NOT NULL,
    citation_digest text NOT NULL,
    acquisition_kind text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT web_evidence_sources_acquisition_kind_check CHECK ((acquisition_kind = 'provider_synthesis_citation'::text)),
    CONSTRAINT web_evidence_sources_canonical_url_digest_check CHECK ((canonical_url_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_evidence_sources_citation_digest_check CHECK ((citation_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_evidence_sources_citation_no_check CHECK (((citation_no >= 1) AND (citation_no <= 128))),
    CONSTRAINT web_evidence_sources_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT web_evidence_sources_title_digest_check CHECK ((title_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
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
    max_attempts smallint DEFAULT 2 NOT NULL,
    max_cost_microyuan bigint DEFAULT 1000000 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    result_artifact_id uuid,
    result_digest text,
    last_error_code text,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    completed_at timestamp(6) with time zone,
    schema_version smallint DEFAULT 1 NOT NULL,
    web_research_intent_id uuid,
    CONSTRAINT web_observation_requests_binding_id_check CHECK ((binding_id = 'armi.model-tool.volcengine-ark-web-search-v1'::text)),
    CONSTRAINT web_observation_requests_check CHECK ((deadline_at > created_at)),
    CONSTRAINT web_observation_requests_check1 CHECK ((((status = ANY (ARRAY['pending'::text, 'running'::text])) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (last_error_code IS NULL) AND (completed_at IS NULL)) OR ((status = 'succeeded'::text) AND (result_artifact_id IS NOT NULL) AND (result_digest IS NOT NULL) AND (last_error_code IS NULL) AND (completed_at IS NOT NULL)) OR ((status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (last_error_code IS NOT NULL) AND (completed_at IS NOT NULL)) OR ((status = 'cancelled'::text) AND (result_artifact_id IS NULL) AND (result_digest IS NULL) AND (completed_at IS NOT NULL)))),
    CONSTRAINT web_observation_requests_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT web_observation_requests_idempotency_key_check CHECK (((octet_length(idempotency_key) >= 1) AND (octet_length(idempotency_key) <= 128) AND (idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT web_observation_requests_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^WEB-[A-Z0-9-]+$'::text))),
    CONSTRAINT web_observation_requests_max_attempts_check CHECK ((max_attempts = 2)),
    CONSTRAINT web_observation_requests_max_cost_microyuan_check CHECK ((max_cost_microyuan = 1000000)),
    CONSTRAINT web_observation_requests_operation_class_check CHECK ((operation_class = 'search_read_public'::text)),
    CONSTRAINT web_observation_requests_purpose_check CHECK ((purpose = 'public_web_research'::text)),
    CONSTRAINT web_observation_requests_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_observation_requests_result_digest_check CHECK (((result_digest IS NULL) OR (result_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT web_observation_requests_schema_version_check CHECK ((schema_version = 1)),
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
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT web_research_intents_check CHECK ((((status = 'pending'::text) AND (web_observation_request_id IS NULL) AND (completed_at IS NULL)) OR ((status = 'admitted'::text) AND (web_observation_request_id IS NOT NULL) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text])) AND (web_observation_request_id IS NOT NULL) AND (completed_at IS NOT NULL)))),
    CONSTRAINT web_research_intents_idempotency_key_check CHECK (((octet_length(idempotency_key) >= 1) AND (octet_length(idempotency_key) <= 128) AND (idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT web_research_intents_operation_class_check CHECK ((operation_class = 'search_read_public'::text)),
    CONSTRAINT web_research_intents_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT web_research_intents_purpose_check CHECK ((purpose = 'public_web_research'::text)),
    CONSTRAINT web_research_intents_query_digest_check CHECK ((query_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT web_research_intents_schema_version_check CHECK ((schema_version = 1)),
    CONSTRAINT web_research_intents_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'admitted'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT web_research_intents_trace_id_check CHECK (((trace_id ~ '^[0-9a-f]{32}$'::text) AND (trace_id <> repeat('0'::text, 32)))),
    CONSTRAINT web_research_intents_web_research_intent_id_check CHECK ((uuid_extract_version(web_research_intent_id) = 7))
);


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
-- Name: action_intent_revisions action_intent_revisions_action_intent_id_revision_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_action_intent_id_revision_no_key UNIQUE (action_intent_id, revision_no);


--
-- Name: action_intent_revisions action_intent_revisions_candidate_validation_id_proposal_re_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_candidate_validation_id_proposal_re_key UNIQUE (candidate_validation_id, proposal_ref);


--
-- Name: action_intent_revisions action_intent_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_pkey PRIMARY KEY (action_intent_revision_id);


--
-- Name: action_intent_revisions action_intent_revisions_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_subject_commit_id_key UNIQUE (subject_commit_id);


--
-- Name: action_intents action_intents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_pkey PRIMARY KEY (action_intent_id);


--
-- Name: action_intents action_intents_root_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_root_opportunity_id_key UNIQUE (root_opportunity_id);


--
-- Name: activities activities_activity_id_current_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activities
    ADD CONSTRAINT activities_activity_id_current_revision_id_key UNIQUE (activity_id, current_revision_id);


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
-- Name: activity_attention_decisions activity_attention_decisions_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_candidate_application_id_key UNIQUE (candidate_application_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_candidate_validation_id_key UNIQUE (candidate_validation_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_cognitive_episode_id_key UNIQUE (cognitive_episode_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_opportunity_id_key UNIQUE (opportunity_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_pkey PRIMARY KEY (attention_decision_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_candidate_application_id_key UNIQUE (candidate_application_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_candidate_validation_id_key UNIQUE (candidate_validation_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_cognitive_episode_id_key UNIQUE (cognitive_episode_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_opportunity_id_key UNIQUE (opportunity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_pkey PRIMARY KEY (work_decision_id);


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
-- Name: cognitive_attempts cognitive_attempts_cognitive_episode_id_attempt_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_cognitive_episode_id_attempt_no_key UNIQUE (cognitive_episode_id, attempt_no);


--
-- Name: cognitive_attempts cognitive_attempts_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_pkey PRIMARY KEY (model_attempt_id);


--
-- Name: cognitive_attempts cognitive_attempts_work_id_work_attempt_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_work_id_work_attempt_id_key UNIQUE (work_id, work_attempt_id);


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
-- Name: cognitive_episodes cognitive_episodes_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_id_key UNIQUE (opportunity_id);


--
-- Name: cognitive_episodes cognitive_episodes_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_pkey PRIMARY KEY (cognitive_episode_id);


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
-- Name: creator_input_interactions creator_input_interactions_creator_interaction_id_subject_i_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_input_interactions
    ADD CONSTRAINT creator_input_interactions_creator_interaction_id_subject_i_key UNIQUE (creator_interaction_id, subject_id, scene_id, creator_party_id);


--
-- Name: creator_input_interactions creator_input_interactions_creator_party_id_scene_id_purpos_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_input_interactions
    ADD CONSTRAINT creator_input_interactions_creator_party_id_scene_id_purpos_key UNIQUE (creator_party_id, scene_id, purpose, idempotency_key);


--
-- Name: creator_input_interactions creator_input_interactions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_input_interactions
    ADD CONSTRAINT creator_input_interactions_pkey PRIMARY KEY (creator_interaction_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_effect_id_key UNIQUE (effect_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_pkey PRIMARY KEY (creator_response_delivery_id);


--
-- Name: creator_response_operations creator_response_operations_action_intent_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_action_intent_id_key UNIQUE (action_intent_id);


--
-- Name: creator_response_operations creator_response_operations_admission_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_admission_work_id_key UNIQUE (admission_work_id);


--
-- Name: creator_response_operations creator_response_operations_current_policy_decision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_current_policy_decision_id_key UNIQUE (current_policy_decision_id);


--
-- Name: creator_response_operations creator_response_operations_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_effect_id_key UNIQUE (effect_id);


--
-- Name: creator_response_operations creator_response_operations_formal_no_action_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_formal_no_action_id_key UNIQUE (formal_no_action_id);


--
-- Name: creator_response_operations creator_response_operations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_pkey PRIMARY KEY (creator_response_operation_id);


--
-- Name: creator_response_operations creator_response_operations_registration_work_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_registration_work_id_key UNIQUE (registration_work_id);


--
-- Name: creator_response_operations creator_response_operations_root_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_root_opportunity_id_key UNIQUE (root_opportunity_id);


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
-- Name: effects effects_action_intent_revision_id_effect_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_action_intent_revision_id_effect_kind_key UNIQUE (action_intent_revision_id, effect_kind);


--
-- Name: effects effects_creator_response_operation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_creator_response_operation_id_key UNIQUE (creator_response_operation_id);


--
-- Name: effects effects_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_pkey PRIMARY KEY (effect_id);


--
-- Name: effects effects_policy_decision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_policy_decision_id_key UNIQUE (policy_decision_id);


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
-- Name: external_evidence external_evidence_codex_task_source_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_task_source_id_key UNIQUE (codex_task_source_id);


--
-- Name: external_evidence external_evidence_codex_verification_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_verification_id_key UNIQUE (codex_verification_id);


--
-- Name: external_evidence external_evidence_creator_interaction_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_creator_interaction_id_key UNIQUE (creator_interaction_id);


--
-- Name: external_evidence external_evidence_evidence_id_subject_id_scene_id_creator_p_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_evidence_id_subject_id_scene_id_creator_p_key UNIQUE (evidence_id, subject_id, scene_id, creator_party_id);


--
-- Name: external_evidence external_evidence_observation_attempt_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_observation_attempt_id_key UNIQUE (observation_attempt_id);


--
-- Name: external_evidence external_evidence_other_human_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_other_human_identity_unique UNIQUE (evidence_id, subject_id, scene_id, other_party_id);


--
-- Name: external_evidence external_evidence_other_human_interaction_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_other_human_interaction_id_key UNIQUE (other_human_interaction_id);


--
-- Name: external_evidence external_evidence_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_pkey PRIMARY KEY (evidence_id);


--
-- Name: external_evidence external_evidence_web_observation_request_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_web_observation_request_id_key UNIQUE (web_observation_request_id);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_candidate_application_id_key UNIQUE (candidate_application_id);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_candidate_validation_id_proposal_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_candidate_validation_id_proposal_key UNIQUE (candidate_validation_id, proposal_ref);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_pkey PRIMARY KEY (formal_no_action_id);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_root_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_root_opportunity_id_key UNIQUE (root_opportunity_id);


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
-- Name: life_materials life_materials_life_material_id_current_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_life_material_id_current_revision_id_key UNIQUE (life_material_id, current_revision_id);


--
-- Name: life_materials life_materials_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.life_materials
    ADD CONSTRAINT life_materials_pkey PRIMARY KEY (life_material_id);


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
-- Name: observation_tool_calls observation_tool_calls_observation_attempt_id_provider_iden_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_observation_attempt_id_provider_iden_key UNIQUE (observation_attempt_id, provider_identity_digest);


--
-- Name: observation_tool_calls observation_tool_calls_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.observation_tool_calls
    ADD CONSTRAINT observation_tool_calls_pkey PRIMARY KEY (observation_tool_call_id);


--
-- Name: opportunities opportunities_context_identity_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_context_identity_unique UNIQUE (opportunity_id, subject_id, scene_id, creator_party_id);


--
-- Name: opportunities opportunities_evidence_reconsideration_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_evidence_reconsideration_unique UNIQUE (evidence_id, reconsideration_no);


--
-- Name: opportunities opportunities_other_human_episode_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_other_human_episode_unique UNIQUE (opportunity_id, subject_id, scene_id, other_party_id);


--
-- Name: opportunities opportunities_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_pkey PRIMARY KEY (opportunity_id);


--
-- Name: opportunities opportunities_predecessor_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_predecessor_unique UNIQUE (predecessor_opportunity_id);


--
-- Name: opportunities opportunities_source_reconsideration_unique; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_source_reconsideration_unique UNIQUE (subject_id, source_kind, source_ref, source_version, purpose, reconsideration_no);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_rev_candidate_validation_id_propo_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_rev_candidate_validation_id_propo_key UNIQUE (candidate_validation_id, proposal_ref);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_rev_other_human_action_intent_id__key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_rev_other_human_action_intent_id__key UNIQUE (other_human_action_intent_id, revision_no);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_revisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_revisions_pkey PRIMARY KEY (other_human_action_intent_revision_id);


--
-- Name: other_human_action_intents other_human_action_intents_current_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_current_revision_id_key UNIQUE (current_revision_id);


--
-- Name: other_human_action_intents other_human_action_intents_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_pkey PRIMARY KEY (other_human_action_intent_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_action_intent_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_action_intent_id_key UNIQUE (action_intent_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_candidate_application_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_candidate_application_id_key UNIQUE (candidate_application_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_candidate_validation_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_candidate_validation_id_key UNIQUE (candidate_validation_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_cognitive_episode_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_cognitive_episode_id_key UNIQUE (cognitive_episode_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_effect_id_key UNIQUE (effect_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_opportunity_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_opportunity_id_key UNIQUE (opportunity_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_pkey PRIMARY KEY (other_human_dialogue_decision_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_subject_commit_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_subject_commit_id_key UNIQUE (subject_commit_id);


--
-- Name: other_human_effects other_human_effects_action_intent_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_action_intent_revision_id_key UNIQUE (action_intent_revision_id);


--
-- Name: other_human_effects other_human_effects_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_pkey PRIMARY KEY (other_human_effect_id);


--
-- Name: other_human_input_interactions other_human_input_interaction_other_human_interaction_id_su_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interaction_other_human_interaction_id_su_key UNIQUE (other_human_interaction_id, subject_id, scene_id, other_party_id);


--
-- Name: other_human_input_interactions other_human_input_interaction_other_party_id_scene_id_purpo_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interaction_other_party_id_scene_id_purpo_key UNIQUE (other_party_id, scene_id, purpose, idempotency_key);


--
-- Name: other_human_input_interactions other_human_input_interactions_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interactions_pkey PRIMARY KEY (other_human_interaction_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_other_human_effect_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_other_human_effect_id_key UNIQUE (other_human_effect_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_pkey PRIMARY KEY (other_human_local_inbox_delivery_id);


--
-- Name: outbox_items outbox_items_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_pkey PRIMARY KEY (outbox_item_id);


--
-- Name: outbox_items outbox_items_work_id_message_kind_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_work_id_message_kind_key UNIQUE (work_id, message_kind);


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
-- Name: relationships relationships_relationship_id_current_revision_id_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.relationships
    ADD CONSTRAINT relationships_relationship_id_current_revision_id_key UNIQUE (relationship_id, current_revision_id);


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
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (migration_id);


--
-- Name: schema_migrations schema_migrations_sequence_no_key; Type: CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.schema_migrations
    ADD CONSTRAINT schema_migrations_sequence_no_key UNIQUE (sequence_no);


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
-- Name: accepted_experiences_subject_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX accepted_experiences_subject_idx ON armi.accepted_experiences USING btree (subject_commit_id, experience_id);


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
-- Name: cognitive_attempts_episode_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_attempts_episode_status_idx ON armi.cognitive_attempts USING btree (cognitive_episode_id, dispatch_status, attempt_no);


--
-- Name: cognitive_candidate_validations_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_candidate_validations_status_idx ON armi.cognitive_candidate_validations USING btree (validation_status, validated_at, candidate_validation_id);


--
-- Name: cognitive_episodes_status_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX cognitive_episodes_status_idx ON armi.cognitive_episodes USING btree (status, created_at, cognitive_episode_id);


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
-- Name: life_generations_one_active_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX life_generations_one_active_idx ON armi.life_generations USING btree (subject_id) WHERE (status = 'active'::text);


--
-- Name: life_material_revisions_material_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX life_material_revisions_material_idx ON armi.life_material_revisions USING btree (life_material_id, revision_no DESC);


--
-- Name: life_materials_subject_current_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX life_materials_subject_current_idx ON armi.life_materials USING btree (subject_id, updated_at DESC, life_material_id) WHERE (deleted_at IS NULL);


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
-- Name: opportunities_recovery_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX opportunities_recovery_idx ON armi.opportunities USING btree (current_disposition, eligibility_status, available_after, opportunity_id);


--
-- Name: outbox_items_claim_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX outbox_items_claim_idx ON armi.outbox_items USING btree (status, available_at, outbox_item_id) WHERE (status = ANY (ARRAY['ready'::text, 'claimed'::text]));


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
-- Name: policy_decisions_one_current; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX policy_decisions_one_current ON armi.policy_decisions USING btree (action_intent_revision_id) WHERE is_current;


--
-- Name: relationship_revisions_relationship_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE INDEX relationship_revisions_relationship_idx ON armi.relationship_revisions USING btree (relationship_id, revision_no DESC);


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
-- Name: schema_migrations_one_baseline_idx; Type: INDEX; Schema: armi; Owner: -
--

CREATE UNIQUE INDEX schema_migrations_one_baseline_idx ON armi.schema_migrations USING btree (migration_kind) WHERE (migration_kind = 'baseline'::text);


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
-- Name: action_intent_revisions action_intent_revisions_action_intent_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_action_intent_id_fkey FOREIGN KEY (action_intent_id) REFERENCES armi.action_intents(action_intent_id);


--
-- Name: action_intent_revisions action_intent_revisions_codex_task_source_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_codex_task_source_id_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);


--
-- Name: action_intent_revisions action_intent_revisions_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: action_intent_revisions action_intent_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);


--
-- Name: action_intent_revisions action_intent_revisions_validation_item_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_validation_item_fk FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);


--
-- Name: action_intents action_intents_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);


--
-- Name: action_intents action_intents_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_current_revision_fk FOREIGN KEY (current_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);


--
-- Name: action_intents action_intents_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: action_intents action_intents_root_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_root_opportunity_id_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: action_intents action_intents_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


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
-- Name: activity_attention_decisions activity_attention_decisions_activity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_expected_revision_id_activity_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_expected_revision_id_activity_fkey FOREIGN KEY (expected_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: activity_attention_decisions activity_attention_decisions_result_revision_id_activity_i_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_attention_decisions
    ADD CONSTRAINT activity_attention_decisions_result_revision_id_activity_i_fkey FOREIGN KEY (result_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisi_expected_revision_id_activit_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisi_expected_revision_id_activit_fkey FOREIGN KEY (expected_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisi_result_revision_id_activity__fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisi_result_revision_id_activity__fkey FOREIGN KEY (result_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_activity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES armi.activities(activity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: activity_internal_work_decisions activity_internal_work_decisions_output_material_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.activity_internal_work_decisions
    ADD CONSTRAINT activity_internal_work_decisions_output_material_id_fkey FOREIGN KEY (output_material_id) REFERENCES armi.life_materials(life_material_id);


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
-- Name: cognitive_attempts cognitive_attempts_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_attempts
    ADD CONSTRAINT cognitive_attempts_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);


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
-- Name: cognitive_episodes cognitive_episodes_bundle_activation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_bundle_activation_id_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id);


--
-- Name: cognitive_episodes cognitive_episodes_compiled_context_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_compiled_context_artifact_id_fkey FOREIGN KEY (compiled_context_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: cognitive_episodes cognitive_episodes_context_manifest_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_context_manifest_artifact_id_fkey FOREIGN KEY (context_manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: cognitive_episodes cognitive_episodes_opportunity_id_subject_id_scene_id_crea_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_id_subject_id_scene_id_crea_fkey FOREIGN KEY (opportunity_id, subject_id, scene_id, creator_party_id) REFERENCES armi.opportunities(opportunity_id, subject_id, scene_id, creator_party_id);


--
-- Name: cognitive_episodes cognitive_episodes_other_human_opportunity_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_other_human_opportunity_fk FOREIGN KEY (opportunity_id, subject_id, scene_id, other_party_id) REFERENCES armi.opportunities(opportunity_id, subject_id, scene_id, other_party_id);


--
-- Name: cognitive_episodes cognitive_episodes_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: creator_exports creator_exports_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_exports
    ADD CONSTRAINT creator_exports_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);


--
-- Name: creator_input_interactions creator_input_interactions_scene_id_subject_id_creator_par_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_input_interactions
    ADD CONSTRAINT creator_input_interactions_scene_id_subject_id_creator_par_fkey FOREIGN KEY (scene_id, subject_id, creator_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: creator_response_deliveries creator_response_deliveries_payload_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_deliveries
    ADD CONSTRAINT creator_response_deliveries_payload_artifact_id_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: creator_response_operations creator_response_operations_action_intent_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_action_intent_id_fkey FOREIGN KEY (action_intent_id) REFERENCES armi.action_intents(action_intent_id);


--
-- Name: creator_response_operations creator_response_operations_admission_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_admission_work_id_fkey FOREIGN KEY (admission_work_id) REFERENCES armi.durable_work(work_id);


--
-- Name: creator_response_operations creator_response_operations_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);


--
-- Name: creator_response_operations creator_response_operations_current_policy_decision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_current_policy_decision_id_fkey FOREIGN KEY (current_policy_decision_id) REFERENCES armi.policy_decisions(policy_decision_id);


--
-- Name: creator_response_operations creator_response_operations_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);


--
-- Name: creator_response_operations creator_response_operations_formal_no_action_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_formal_no_action_id_fkey FOREIGN KEY (formal_no_action_id) REFERENCES armi.formal_no_action_decisions(formal_no_action_id);


--
-- Name: creator_response_operations creator_response_operations_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: creator_response_operations creator_response_operations_matched_grant_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_matched_grant_id_fkey FOREIGN KEY (matched_grant_id) REFERENCES armi.permission_grants(grant_id);


--
-- Name: creator_response_operations creator_response_operations_registration_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_registration_work_id_fkey FOREIGN KEY (registration_work_id) REFERENCES armi.durable_work(work_id);


--
-- Name: creator_response_operations creator_response_operations_root_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_root_opportunity_id_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: creator_response_operations creator_response_operations_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.creator_response_operations
    ADD CONSTRAINT creator_response_operations_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


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
-- Name: effect_observations effect_observations_effect_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effect_observations
    ADD CONSTRAINT effect_observations_effect_attempt_id_fkey FOREIGN KEY (effect_attempt_id) REFERENCES armi.effect_attempts(effect_attempt_id);


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
-- Name: effects effects_action_intent_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_action_intent_revision_id_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id);


--
-- Name: effects effects_creator_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_creator_party_id_fkey FOREIGN KEY (creator_party_id) REFERENCES armi.parties(party_id);


--
-- Name: effects effects_creator_response_operation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_creator_response_operation_id_fkey FOREIGN KEY (creator_response_operation_id) REFERENCES armi.creator_response_operations(creator_response_operation_id);


--
-- Name: effects effects_current_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_current_attempt_id_fkey FOREIGN KEY (current_attempt_id) REFERENCES armi.effect_attempts(effect_attempt_id);


--
-- Name: effects effects_current_observation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_current_observation_id_fkey FOREIGN KEY (current_observation_id) REFERENCES armi.effect_observations(effect_observation_id);


--
-- Name: effects effects_interaction_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_interaction_scene_id_fkey FOREIGN KEY (interaction_scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: effects effects_payload_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_payload_artifact_id_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: effects effects_policy_decision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_policy_decision_id_fkey FOREIGN KEY (policy_decision_id) REFERENCES armi.policy_decisions(policy_decision_id);


--
-- Name: effects effects_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


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
-- Name: external_evidence external_evidence_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: external_evidence external_evidence_codex_task_source_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_task_source_id_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);


--
-- Name: external_evidence external_evidence_codex_verification_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_codex_verification_fk FOREIGN KEY (codex_verification_id) REFERENCES armi.codex_verification_results(codex_verification_id);


--
-- Name: external_evidence external_evidence_creator_interaction_id_subject_id_scene__fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_creator_interaction_id_subject_id_scene__fkey FOREIGN KEY (creator_interaction_id, subject_id, scene_id, creator_party_id) REFERENCES armi.creator_input_interactions(creator_interaction_id, subject_id, scene_id, creator_party_id);


--
-- Name: external_evidence external_evidence_observation_attempt_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_observation_attempt_id_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id);


--
-- Name: external_evidence external_evidence_other_human_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_other_human_fk FOREIGN KEY (other_human_interaction_id, subject_id, scene_id, other_party_id) REFERENCES armi.other_human_input_interactions(other_human_interaction_id, subject_id, scene_id, other_party_id);


--
-- Name: external_evidence external_evidence_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: external_evidence external_evidence_web_observation_request_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.external_evidence
    ADD CONSTRAINT external_evidence_web_observation_request_id_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_candidate_validation_id_proposa_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_candidate_validation_id_proposa_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);


--
-- Name: formal_no_action_decisions formal_no_action_decisions_root_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.formal_no_action_decisions
    ADD CONSTRAINT formal_no_action_decisions_root_opportunity_id_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


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
-- Name: opportunities opportunities_activity_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_activity_fk FOREIGN KEY (activity_id, subject_id) REFERENCES armi.activities(activity_id, subject_id);


--
-- Name: opportunities opportunities_evidence_id_subject_id_scene_id_creator_part_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_evidence_id_subject_id_scene_id_creator_part_fkey FOREIGN KEY (evidence_id, subject_id, scene_id, creator_party_id) REFERENCES armi.external_evidence(evidence_id, subject_id, scene_id, creator_party_id);


--
-- Name: opportunities opportunities_other_human_evidence_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_other_human_evidence_fk FOREIGN KEY (evidence_id, subject_id, scene_id, other_party_id) REFERENCES armi.external_evidence(evidence_id, subject_id, scene_id, other_party_id);


--
-- Name: opportunities opportunities_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: opportunities opportunities_predecessor_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_predecessor_fk FOREIGN KEY (predecessor_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: opportunities opportunities_root_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.opportunities
    ADD CONSTRAINT opportunities_root_fk FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_rev_other_human_action_intent_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_rev_other_human_action_intent_id_fkey FOREIGN KEY (other_human_action_intent_id) REFERENCES armi.other_human_action_intents(other_human_action_intent_id);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_revision_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_revision_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_revisions_response_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_revisions_response_artifact_id_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: other_human_action_intent_revisions other_human_action_intent_revisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intent_revisions
    ADD CONSTRAINT other_human_action_intent_revisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);


--
-- Name: other_human_action_intents other_human_action_intents_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_current_revision_fk FOREIGN KEY (current_revision_id) REFERENCES armi.other_human_action_intent_revisions(other_human_action_intent_revision_id);


--
-- Name: other_human_action_intents other_human_action_intents_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: other_human_action_intents other_human_action_intents_root_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_root_opportunity_id_fkey FOREIGN KEY (root_opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: other_human_action_intents other_human_action_intents_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: other_human_action_intents other_human_action_intents_scene_id_subject_id_other_party_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_scene_id_subject_id_other_party_fkey FOREIGN KEY (scene_id, subject_id, other_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);


--
-- Name: other_human_action_intents other_human_action_intents_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_action_intents
    ADD CONSTRAINT other_human_action_intents_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_action_intent_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_action_intent_id_fkey FOREIGN KEY (action_intent_id) REFERENCES armi.other_human_action_intents(other_human_action_intent_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_candidate_application_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_candidate_application_id_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_candidate_validation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_candidate_validation_id_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_cognitive_episode_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_cognitive_episode_id_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_effect_id_fkey FOREIGN KEY (effect_id) REFERENCES armi.other_human_effects(other_human_effect_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_subject_commit_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_subject_commit_id_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);


--
-- Name: other_human_dialogue_decisions other_human_dialogue_decisions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_dialogue_decisions
    ADD CONSTRAINT other_human_dialogue_decisions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


--
-- Name: other_human_effects other_human_effects_action_intent_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_action_intent_revision_id_fkey FOREIGN KEY (action_intent_revision_id) REFERENCES armi.other_human_action_intent_revisions(other_human_action_intent_revision_id);


--
-- Name: other_human_effects other_human_effects_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: other_human_effects other_human_effects_payload_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_payload_artifact_id_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: other_human_effects other_human_effects_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: other_human_effects other_human_effects_scene_id_subject_id_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_scene_id_subject_id_other_party_id_fkey FOREIGN KEY (scene_id, subject_id, other_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);


--
-- Name: other_human_effects other_human_effects_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_effects
    ADD CONSTRAINT other_human_effects_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


--
-- Name: other_human_input_interactions other_human_input_interaction_scene_id_subject_id_other_pa_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interaction_scene_id_subject_id_other_pa_fkey FOREIGN KEY (scene_id, subject_id, other_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id);


--
-- Name: other_human_input_interactions other_human_input_interactions_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interactions_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: other_human_input_interactions other_human_input_interactions_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interactions_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: other_human_input_interactions other_human_input_interactions_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_input_interactions
    ADD CONSTRAINT other_human_input_interactions_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_other_human_effect_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_other_human_effect_id_fkey FOREIGN KEY (other_human_effect_id) REFERENCES armi.other_human_effects(other_human_effect_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_other_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_other_party_id_fkey FOREIGN KEY (other_party_id) REFERENCES armi.parties(party_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_payload_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_payload_artifact_id_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);


--
-- Name: other_human_local_inbox_deliveries other_human_local_inbox_deliveries_scene_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.other_human_local_inbox_deliveries
    ADD CONSTRAINT other_human_local_inbox_deliveries_scene_id_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id);


--
-- Name: outbox_items outbox_items_work_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.outbox_items
    ADD CONSTRAINT outbox_items_work_id_fkey FOREIGN KEY (work_id) REFERENCES armi.durable_work(work_id) ON DELETE RESTRICT;


--
-- Name: parties parties_represented_subject_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.parties
    ADD CONSTRAINT parties_represented_subject_id_fkey FOREIGN KEY (represented_subject_id) REFERENCES armi.subjects(subject_id);


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
-- Name: policy_decisions policy_decisions_creator_response_operation_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.policy_decisions
    ADD CONSTRAINT policy_decisions_creator_response_operation_id_fkey FOREIGN KEY (creator_response_operation_id) REFERENCES armi.creator_response_operations(creator_response_operation_id);


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
-- Name: prompt_documents prompt_documents_current_revision_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_documents
    ADD CONSTRAINT prompt_documents_current_revision_fk FOREIGN KEY (current_revision_id) REFERENCES armi.prompt_revisions(prompt_revision_id) DEFERRABLE INITIALLY DEFERRED;


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
-- Name: prompt_revisions prompt_revisions_previous_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.prompt_revisions
    ADD CONSTRAINT prompt_revisions_previous_revision_id_fkey FOREIGN KEY (previous_revision_id) REFERENCES armi.prompt_revisions(prompt_revision_id);


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
-- Name: runtime_bundle_activations runtime_bundle_activations_activated_by_party_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_activated_by_party_id_fkey FOREIGN KEY (activated_by_party_id) REFERENCES armi.parties(party_id);


--
-- Name: runtime_bundle_activations runtime_bundle_activations_manifest_artifact_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.runtime_bundle_activations
    ADD CONSTRAINT runtime_bundle_activations_manifest_artifact_id_fkey FOREIGN KEY (manifest_artifact_id) REFERENCES armi.artifacts(artifact_id);


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
-- Name: subject_component_heads subject_component_heads_current_revision_id_fkey; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_heads
    ADD CONSTRAINT subject_component_heads_current_revision_id_fkey FOREIGN KEY (current_revision_id) REFERENCES armi.subject_component_revisions(component_revision_id);


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
-- Name: subject_component_revisions subject_component_revisions_previous_fk; Type: FK CONSTRAINT; Schema: armi; Owner: -
--

ALTER TABLE ONLY armi.subject_component_revisions
    ADD CONSTRAINT subject_component_revisions_previous_fk FOREIGN KEY (previous_revision_id) REFERENCES armi.subject_component_revisions(component_revision_id);


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


--
-- Name: SCHEMA armi; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA armi TO armi_runtime;
GRANT USAGE ON SCHEMA armi TO armi_admin;
GRANT USAGE ON SCHEMA armi TO armi_migrator;


--
-- Name: TABLE accepted_experiences; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.accepted_experiences TO armi_runtime;
GRANT SELECT ON TABLE armi.accepted_experiences TO armi_admin;


--
-- Name: TABLE action_intent_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.action_intent_revisions TO armi_runtime;
GRANT SELECT ON TABLE armi.action_intent_revisions TO armi_admin;


--
-- Name: COLUMN action_intent_revisions.action_intent_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_intent_revision_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.action_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_intent_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.revision_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(revision_no) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.response_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(response_artifact_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.response_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(response_digest) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.response_bytes; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(response_bytes) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.media_type; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(media_type) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.capability_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_kind) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.operation_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_class) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.audience_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(audience_scope) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.data_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(data_scope) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.codex_task_source_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(codex_task_source_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.task_manifest_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(task_manifest_digest) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: COLUMN action_intent_revisions.validator_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(validator_id) ON TABLE armi.action_intent_revisions TO armi_runtime;


--
-- Name: TABLE action_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.action_intents TO armi_runtime;
GRANT SELECT ON TABLE armi.action_intents TO armi_admin;


--
-- Name: COLUMN action_intents.action_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_intent_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.interaction_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(interaction_scene_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.root_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(root_opportunity_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_revision_id),UPDATE(current_revision_id) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: COLUMN action_intents.action_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_kind) ON TABLE armi.action_intents TO armi_runtime;


--
-- Name: TABLE activities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activities TO armi_runtime;
GRANT SELECT ON TABLE armi.activities TO armi_admin;


--
-- Name: COLUMN activities.activity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_id) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.activity_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_kind) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.origin_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(origin_opportunity_id) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_revision_id),UPDATE(current_revision_id) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(head_version),UPDATE(head_version) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.activities TO armi_runtime;


--
-- Name: COLUMN activities.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.activities TO armi_runtime;


--
-- Name: TABLE activity_attention_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activity_attention_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.activity_attention_decisions TO armi_admin;


--
-- Name: COLUMN activity_attention_decisions.attention_decision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attention_decision_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opportunity_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.candidate_application_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_application_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.activity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.expected_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_revision_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.expected_head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_head_version) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.resource_snapshot_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resource_snapshot_digest) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.decision_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(decision_kind) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.result_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(result_revision_id) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.review_not_before; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(review_not_before) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: COLUMN activity_attention_decisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.activity_attention_decisions TO armi_runtime;


--
-- Name: TABLE activity_internal_work_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activity_internal_work_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.activity_internal_work_decisions TO armi_admin;


--
-- Name: COLUMN activity_internal_work_decisions.work_decision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_decision_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opportunity_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.candidate_application_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_application_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.activity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.expected_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_revision_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.expected_head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_head_version) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.resource_snapshot_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resource_snapshot_digest) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.outcome_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(outcome_kind) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.result_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(result_revision_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.output_material_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(output_material_id) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: COLUMN activity_internal_work_decisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.activity_internal_work_decisions TO armi_runtime;


--
-- Name: TABLE activity_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activity_revisions TO armi_runtime;
GRANT SELECT ON TABLE armi.activity_revisions TO armi_admin;


--
-- Name: COLUMN activity_revisions.activity_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_revision_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.activity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.revision_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(revision_no) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.previous_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(previous_revision_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.goal; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(goal) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.progress_summary; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(progress_summary) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.waiting_condition; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(waiting_condition) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.resumption_cue; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumption_cue) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.next_safe_step; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(next_safe_step) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.terminal_reason; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(terminal_reason) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.related_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(related_scene_id) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.transition_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(transition_kind) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.waiting_condition_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(waiting_condition_kind) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: COLUMN activity_revisions.resume_not_before; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resume_not_before) ON TABLE armi.activity_revisions TO armi_runtime;


--
-- Name: TABLE artifacts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.artifacts TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.artifacts TO armi_admin;


--
-- Name: COLUMN artifacts.artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(artifact_id) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.content_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(content_digest) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.media_type; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(media_type) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.byte_size; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(byte_size) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.storage_locator; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(storage_locator) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.logical_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(logical_kind) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.producer_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(producer_kind) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.producer_trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(producer_trace_id) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.integrity_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(integrity_status) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.retention_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(retention_status) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.deleted_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(deleted_at) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: COLUMN artifacts.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.artifacts TO armi_runtime;


--
-- Name: TABLE audit_events; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.audit_events TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.audit_events TO armi_admin;


--
-- Name: COLUMN audit_events.audit_event_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(audit_event_id) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.actor_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(actor_kind) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.actor_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(actor_ref) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.operation; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.target_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(target_kind) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.target_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(target_ref) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(result_status) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.sensitivity; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(sensitivity) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.request_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_kind) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.request_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_ref) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.before_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(before_version) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.after_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(after_version) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.response_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(response_digest) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.artifact_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(artifact_digest) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.details_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(details_digest) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.policy_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(policy_ref) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.grant_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(grant_ref) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.bundle_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_digest) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.error_category; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(error_category) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: COLUMN audit_events.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.audit_events TO armi_runtime;


--
-- Name: TABLE capabilities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capabilities TO armi_runtime;
GRANT SELECT ON TABLE armi.capabilities TO armi_admin;


--
-- Name: TABLE capability_request_basis_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capability_request_basis_links TO armi_runtime;
GRANT SELECT ON TABLE armi.capability_request_basis_links TO armi_admin;


--
-- Name: COLUMN capability_request_basis_links.capability_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_request_id) ON TABLE armi.capability_request_basis_links TO armi_runtime;


--
-- Name: COLUMN capability_request_basis_links.context_item_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(context_item_id) ON TABLE armi.capability_request_basis_links TO armi_runtime;


--
-- Name: COLUMN capability_request_basis_links.ordinal; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(ordinal) ON TABLE armi.capability_request_basis_links TO armi_runtime;


--
-- Name: TABLE capability_request_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capability_request_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.capability_request_decisions TO armi_admin;


--
-- Name: COLUMN capability_request_decisions.capability_decision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_decision_id) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.capability_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_request_id) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.expected_request_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_request_version) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.resulting_request_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resulting_request_version) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.decision_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(decision_kind) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.command_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(command_digest) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.scope_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scope_digest) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.reason_code; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reason_code) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: COLUMN capability_request_decisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.capability_request_decisions TO armi_runtime;


--
-- Name: TABLE capability_requests; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capability_requests TO armi_runtime;
GRANT SELECT ON TABLE armi.capability_requests TO armi_admin;


--
-- Name: COLUMN capability_requests.capability_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_request_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.interaction_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(interaction_scene_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.capability_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.capability_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_kind) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.operation_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_class) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.audience_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(audience_scope) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.data_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(data_scope) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.workspace_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(workspace_scope) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.artifact_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(artifact_scope) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.network_access; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(network_access) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.requested_valid_for_seconds; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(requested_valid_for_seconds) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.requested_max_uses; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(requested_max_uses) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.requested_max_payload_bytes; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(requested_max_payload_bytes) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.current_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_status) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.request_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(request_version) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.resolved_by_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(resolved_by_party_id) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.resolution_reason_class; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(resolution_reason_class) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.resolved_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(resolved_at) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: COLUMN capability_requests.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.capability_requests TO armi_runtime;


--
-- Name: TABLE codex_result_sources; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.codex_result_sources TO armi_runtime;


--
-- Name: TABLE codex_task_sources; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.codex_task_sources TO armi_runtime;


--
-- Name: TABLE codex_verification_results; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.codex_verification_results TO armi_runtime;


--
-- Name: TABLE cognitive_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_admin;


--
-- Name: COLUMN cognitive_attempts.model_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(model_attempt_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.work_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_attempt_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.attempt_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_no) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.binding_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(binding_digest) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.provider; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(provider) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.model_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(model_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.version_policy; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(version_policy) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.profile; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(profile) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.request_schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_schema_version) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.candidate_schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_schema_version) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.pricing_snapshot_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(pricing_snapshot_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.credential_identity; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(credential_identity) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.request_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_artifact_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.dispatch_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(dispatch_status),UPDATE(dispatch_status) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.provider_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(provider_request_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.provider_model_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(provider_model_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.response_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(response_artifact_id) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.input_tokens; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(input_tokens) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.output_tokens; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(output_tokens) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.cached_input_tokens; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(cached_input_tokens) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.estimated_cost_microyuan; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(estimated_cost_microyuan) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_status) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(error_code) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.dispatched_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(dispatched_at) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.settled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settled_at) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: COLUMN cognitive_attempts.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.cognitive_attempts TO armi_runtime;


--
-- Name: TABLE cognitive_candidate_applications; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_applications TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_candidate_applications TO armi_admin;


--
-- Name: TABLE cognitive_candidate_basis_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_basis_links TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_candidate_basis_links TO armi_admin;


--
-- Name: TABLE cognitive_candidate_validation_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_validation_items TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_candidate_validation_items TO armi_admin;


--
-- Name: TABLE cognitive_candidate_validations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_validations TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_candidate_validations TO armi_admin;


--
-- Name: TABLE cognitive_context_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_context_items TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_context_items TO armi_admin;


--
-- Name: COLUMN cognitive_context_items.context_item_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(context_item_id) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.ordinal; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(ordinal) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.section; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(section) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.item_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(item_kind) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.source_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_kind) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.source_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_ref) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.source_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_version) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.source_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_digest) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.trust_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trust_class) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.disposition; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(disposition) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.reason_code; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reason_code) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.content_bytes; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(content_bytes) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: COLUMN cognitive_context_items.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.cognitive_context_items TO armi_runtime;


--
-- Name: TABLE cognitive_episodes; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_episodes TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_episodes TO armi_admin;


--
-- Name: COLUMN cognitive_episodes.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opportunity_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.base_subject_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(base_subject_version) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.base_state_epoch; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(base_state_epoch) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.bundle_activation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_activation_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.policy_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(policy_digest) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.mechanism_identity; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(mechanism_identity) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.mechanism_config_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(mechanism_config_digest) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.context_manifest_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(context_manifest_artifact_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.compiled_context_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(compiled_context_artifact_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.context_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(context_digest) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.failure_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(failure_code) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.prepared_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(prepared_at) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.model_returned_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(model_returned_at) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.final_disposition; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(final_disposition) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.validated_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(validated_at) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.application_resolution; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(application_resolution) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.committed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(committed_at) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: COLUMN cognitive_episodes.other_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(other_party_id) ON TABLE armi.cognitive_episodes TO armi_runtime;


--
-- Name: TABLE creator_exports; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.manifest_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(manifest_digest) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.table_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(table_count) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.row_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(row_count) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.artifact_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(artifact_count) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.missing_artifacts; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(missing_artifacts) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(error_code) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: COLUMN creator_exports.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.creator_exports TO armi_runtime;


--
-- Name: TABLE creator_input_interactions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.creator_input_interactions TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.creator_input_interactions TO armi_admin;


--
-- Name: COLUMN creator_input_interactions.creator_interaction_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_interaction_id) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(idempotency_key) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.content_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(content_digest) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: COLUMN creator_input_interactions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.creator_input_interactions TO armi_runtime;


--
-- Name: TABLE creator_response_deliveries; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.creator_response_deliveries TO armi_runtime;
GRANT SELECT ON TABLE armi.creator_response_deliveries TO armi_admin;


--
-- Name: COLUMN creator_response_deliveries.creator_response_delivery_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_response_delivery_id) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.effect_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_id) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.interaction_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(interaction_scene_id) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.payload_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_artifact_id) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.payload_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_digest) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.payload_bytes; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_bytes) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.receipt_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(receipt_digest) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: COLUMN creator_response_deliveries.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.creator_response_deliveries TO armi_runtime;


--
-- Name: TABLE creator_response_operations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.creator_response_operations TO armi_runtime;
GRANT SELECT ON TABLE armi.creator_response_operations TO armi_admin;


--
-- Name: COLUMN creator_response_operations.creator_response_operation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_response_operation_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.root_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(root_opportunity_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.interaction_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(interaction_scene_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.action_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_intent_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.formal_no_action_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(formal_no_action_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.admission_work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(admission_work_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.current_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_status),UPDATE(current_status) ON TABLE armi.creator_response_operations TO armi_runtime;
GRANT UPDATE(current_status) ON TABLE armi.creator_response_operations TO armi_admin;


--
-- Name: COLUMN creator_response_operations.matched_grant_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(matched_grant_id),UPDATE(matched_grant_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.completion_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(completion_digest),UPDATE(completion_digest) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.reason_code; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reason_code),UPDATE(reason_code) ON TABLE armi.creator_response_operations TO armi_runtime;
GRANT UPDATE(reason_code) ON TABLE armi.creator_response_operations TO armi_admin;


--
-- Name: COLUMN creator_response_operations.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(completed_at),UPDATE(completed_at) ON TABLE armi.creator_response_operations TO armi_runtime;
GRANT UPDATE(completed_at) ON TABLE armi.creator_response_operations TO armi_admin;


--
-- Name: COLUMN creator_response_operations.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.registration_work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(registration_work_id),UPDATE(registration_work_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.current_policy_decision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_policy_decision_id),UPDATE(current_policy_decision_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.effect_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_id),UPDATE(effect_id) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.effect_registration_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_registration_digest),UPDATE(effect_registration_digest) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.effect_registered_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_registered_at),UPDATE(effect_registered_at) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: COLUMN creator_response_operations.operation_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_kind) ON TABLE armi.creator_response_operations TO armi_runtime;


--
-- Name: TABLE deletion_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.deletion_items TO armi_runtime;


--
-- Name: COLUMN deletion_items.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_status) ON TABLE armi.deletion_items TO armi_runtime;


--
-- Name: COLUMN deletion_items.remaining_location; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(remaining_location) ON TABLE armi.deletion_items TO armi_runtime;


--
-- Name: COLUMN deletion_items.execution_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(execution_digest) ON TABLE armi.deletion_items TO armi_runtime;


--
-- Name: COLUMN deletion_items.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.deletion_items TO armi_runtime;


--
-- Name: TABLE deletion_orders; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.deletion_orders TO armi_runtime;


--
-- Name: COLUMN deletion_orders.execution_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(execution_status) ON TABLE armi.deletion_orders TO armi_runtime;


--
-- Name: COLUMN deletion_orders.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.deletion_orders TO armi_runtime;


--
-- Name: TABLE deployment_environments; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.deployment_environments TO armi_runtime;
GRANT SELECT ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.singleton_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(singleton_key) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.environment_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(environment_id) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.environment_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(environment_kind) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.incarnation; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(incarnation) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.resettable; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resettable) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.test_controls_enabled; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(test_controls_enabled) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.bundle_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_digest) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.config_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(config_digest) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.template_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(template_digest) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.data_root_identity_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(data_root_identity_digest) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.database_identity_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(database_identity_digest) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: COLUMN deployment_environments.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.deployment_environments TO armi_admin;


--
-- Name: TABLE durable_work; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.durable_work TO armi_runtime;
GRANT SELECT ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(work_id) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.work_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_kind) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(work_kind) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.owner_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(owner_kind) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(owner_kind) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.owner_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(owner_ref) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(owner_ref) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(subject_id) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(idempotency_key) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(idempotency_key) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.payload_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_kind) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(payload_kind) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.payload_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_ref) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(payload_ref) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.payload_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_digest) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(payload_digest) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.priority; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(priority) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(priority) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.not_before; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(not_before),UPDATE(not_before) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(not_before),UPDATE(not_before) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.deadline_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(deadline_at) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(deadline_at) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(status),UPDATE(status) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.max_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_attempts) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(max_attempts) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_count),UPDATE(attempt_count) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(attempt_count) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.current_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_attempt_id) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(current_attempt_id) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.lease_owner; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(lease_owner) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(lease_owner) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.lease_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(lease_expires_at) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(lease_expires_at) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.lease_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(lease_token),UPDATE(lease_token) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(lease_token),UPDATE(lease_token) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.result_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_kind) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(result_kind) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.result_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_ref) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(result_ref) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(last_error_code) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(trace_id) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.durable_work TO armi_runtime;
GRANT INSERT(schema_version) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: COLUMN durable_work.updated_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE armi.durable_work TO armi_runtime;
GRANT UPDATE(updated_at) ON TABLE armi.durable_work TO armi_admin;


--
-- Name: TABLE effect_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effect_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.effect_attempts TO armi_admin;


--
-- Name: COLUMN effect_attempts.effect_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_attempt_id) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.effect_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_id) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.attempt_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_no) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.adapter_binding; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(adapter_binding) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.claim_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(claim_token) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.dispatch_state; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(dispatch_state),UPDATE(dispatch_state) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_status) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(error_code) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.dispatched_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(dispatched_at) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.settled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settled_at) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: COLUMN effect_attempts.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.effect_attempts TO armi_runtime;


--
-- Name: TABLE effect_observations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effect_observations TO armi_runtime;
GRANT SELECT ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.effect_observation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_observation_id) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(effect_observation_id) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.effect_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_id) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(effect_id) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.effect_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_attempt_id) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(effect_attempt_id) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.observation_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_kind) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(observation_kind) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.reliability; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reliability) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(reliability) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.receiver_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(receiver_ref) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(receiver_ref) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.observation_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_digest) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(observation_digest) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: COLUMN effect_observations.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.effect_observations TO armi_runtime;
GRANT INSERT(schema_version) ON TABLE armi.effect_observations TO armi_admin;


--
-- Name: TABLE effect_outbox_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT SELECT ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: COLUMN effect_outbox_items.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE(status) ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: COLUMN effect_outbox_items.available_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(available_at) ON TABLE armi.effect_outbox_items TO armi_runtime;


--
-- Name: COLUMN effect_outbox_items.cancelled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(cancelled_at) ON TABLE armi.effect_outbox_items TO armi_runtime;


--
-- Name: COLUMN effect_outbox_items.claim_owner; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claim_owner) ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE(claim_owner) ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: COLUMN effect_outbox_items.claim_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claim_expires_at) ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE(claim_expires_at) ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: COLUMN effect_outbox_items.claim_token; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claim_token) ON TABLE armi.effect_outbox_items TO armi_runtime;


--
-- Name: COLUMN effect_outbox_items.attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(attempt_count) ON TABLE armi.effect_outbox_items TO armi_runtime;


--
-- Name: COLUMN effect_outbox_items.delivered_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(delivered_at) ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE(delivered_at) ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: COLUMN effect_outbox_items.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE(last_error_code) ON TABLE armi.effect_outbox_items TO armi_admin;


--
-- Name: TABLE effects; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.effects TO armi_runtime;
GRANT SELECT ON TABLE armi.effects TO armi_admin;


--
-- Name: COLUMN effects.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.effects TO armi_runtime;
GRANT UPDATE(status) ON TABLE armi.effects TO armi_admin;


--
-- Name: COLUMN effects.verification_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(verification_status) ON TABLE armi.effects TO armi_runtime;
GRANT UPDATE(verification_status) ON TABLE armi.effects TO armi_admin;


--
-- Name: COLUMN effects.cancelled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(cancelled_at) ON TABLE armi.effects TO armi_runtime;


--
-- Name: COLUMN effects.current_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_attempt_id) ON TABLE armi.effects TO armi_runtime;


--
-- Name: COLUMN effects.current_observation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_observation_id) ON TABLE armi.effects TO armi_runtime;
GRANT UPDATE(current_observation_id) ON TABLE armi.effects TO armi_admin;


--
-- Name: COLUMN effects.settlement_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settlement_digest) ON TABLE armi.effects TO armi_runtime;
GRANT UPDATE(settlement_digest) ON TABLE armi.effects TO armi_admin;


--
-- Name: COLUMN effects.settled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settled_at) ON TABLE armi.effects TO armi_runtime;
GRANT UPDATE(settled_at) ON TABLE armi.effects TO armi_admin;


--
-- Name: TABLE exact_life_query_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.result_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_artifact_id) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.result_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_digest) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.result_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_count) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.failure_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(failure_code) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.result_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_opportunity_id) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: COLUMN exact_life_query_intents.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.exact_life_query_intents TO armi_runtime;


--
-- Name: TABLE experience_evidence_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.experience_evidence_links TO armi_runtime;
GRANT SELECT ON TABLE armi.experience_evidence_links TO armi_admin;


--
-- Name: TABLE external_evidence; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.external_evidence TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.external_evidence TO armi_admin;


--
-- Name: COLUMN external_evidence.evidence_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(evidence_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.creator_interaction_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_interaction_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(artifact_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.source_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_kind) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.trust_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trust_status) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.acceptance_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(acceptance_status) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.web_observation_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(web_observation_request_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.observation_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_attempt_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.codex_task_source_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(codex_task_source_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.codex_verification_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(codex_verification_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.other_human_interaction_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(other_human_interaction_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: COLUMN external_evidence.other_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(other_party_id) ON TABLE armi.external_evidence TO armi_runtime;


--
-- Name: TABLE formal_no_action_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.formal_no_action_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.formal_no_action_decisions TO armi_admin;


--
-- Name: COLUMN formal_no_action_decisions.formal_no_action_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(formal_no_action_id) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.candidate_application_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_application_id) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.root_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(root_opportunity_id) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.decision_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(decision_kind) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.reason_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reason_class) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.basis_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(basis_digest) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: COLUMN formal_no_action_decisions.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.formal_no_action_decisions TO armi_runtime;


--
-- Name: TABLE interaction_scenes; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.interaction_scenes TO armi_runtime;
GRANT SELECT ON TABLE armi.interaction_scenes TO armi_admin;


--
-- Name: COLUMN interaction_scenes.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.scene_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_key) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.scene_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_kind) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.primary_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(primary_party_id) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.audience_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(audience_scope) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.current_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_status),UPDATE(current_status) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.closed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(closed_at) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.recent_context_boundary; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(recent_context_boundary) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: COLUMN interaction_scenes.primary_party_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(primary_party_kind) ON TABLE armi.interaction_scenes TO armi_runtime;


--
-- Name: TABLE life_generations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.life_generations TO armi_runtime;
GRANT SELECT ON TABLE armi.life_generations TO armi_admin;


--
-- Name: COLUMN life_generations.life_generation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(life_generation_id) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: COLUMN life_generations.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: COLUMN life_generations.generation_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(generation_no) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: COLUMN life_generations.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: COLUMN life_generations.opened_subject_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opened_subject_version) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: COLUMN life_generations.activation_reason; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activation_reason) ON TABLE armi.life_generations TO armi_runtime;


--
-- Name: TABLE life_material_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.life_material_revisions TO armi_runtime;


--
-- Name: TABLE life_materials; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.life_materials TO armi_runtime;


--
-- Name: COLUMN life_materials.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_revision_id) ON TABLE armi.life_materials TO armi_runtime;


--
-- Name: COLUMN life_materials.head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(head_version) ON TABLE armi.life_materials TO armi_runtime;


--
-- Name: COLUMN life_materials.deleted_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(deleted_at) ON TABLE armi.life_materials TO armi_runtime;


--
-- Name: COLUMN life_materials.updated_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE armi.life_materials TO armi_runtime;


--
-- Name: TABLE maintenance_phase_results; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_runtime;
GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_admin;


--
-- Name: COLUMN maintenance_phase_results.maintenance_phase_result_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(maintenance_phase_result_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opportunity_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.cognitive_episode_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(cognitive_episode_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.candidate_validation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_validation_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.candidate_application_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(candidate_application_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.maintenance_session_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(maintenance_session_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.maintenance_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(maintenance_revision_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.expected_head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expected_head_version) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.phase; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(phase) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.outcome; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(outcome) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.result_summary; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(result_summary) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.creator_visible_problem; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_visible_problem) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.memory_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(memory_id) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: COLUMN maintenance_phase_results.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.maintenance_phase_results TO armi_runtime;


--
-- Name: TABLE maintenance_session_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.maintenance_session_revisions TO armi_runtime;
GRANT SELECT ON TABLE armi.maintenance_session_revisions TO armi_admin;


--
-- Name: TABLE maintenance_sessions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.maintenance_sessions TO armi_runtime;
GRANT SELECT ON TABLE armi.maintenance_sessions TO armi_admin;


--
-- Name: COLUMN maintenance_sessions.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_revision_id) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: COLUMN maintenance_sessions.head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(head_version) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: COLUMN maintenance_sessions.finished_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(finished_at) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: COLUMN maintenance_sessions.wake_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(wake_request_id) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: COLUMN maintenance_sessions.wake_requested_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(wake_requested_at) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: COLUMN maintenance_sessions.quiet_until; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(quiet_until) ON TABLE armi.maintenance_sessions TO armi_runtime;


--
-- Name: TABLE memory_relations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.memory_relations TO armi_runtime;


--
-- Name: TABLE observation_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.observation_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.observation_attempts TO armi_admin;


--
-- Name: COLUMN observation_attempts.observation_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_attempt_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.web_observation_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(web_observation_request_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.work_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_attempt_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.work_lease_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_lease_token) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.attempt_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_no) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.binding_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(binding_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.credential_identity; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(credential_identity) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.dispatch_state; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(dispatch_state),UPDATE(dispatch_state) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.provider_request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(provider_request_digest) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.provider_model_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(provider_model_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.result_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_artifact_id) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.result_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_digest) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.input_tokens; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(input_tokens) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.output_tokens; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(output_tokens) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.web_search_calls; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(web_search_calls) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.citation_count; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(citation_count) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.estimated_cost_microyuan; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(estimated_cost_microyuan) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_status) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(error_code) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.dispatched_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(dispatched_at) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.settled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settled_at) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: COLUMN observation_attempts.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.observation_attempts TO armi_runtime;


--
-- Name: TABLE observation_tool_calls; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.observation_tool_calls TO armi_runtime;
GRANT SELECT ON TABLE armi.observation_tool_calls TO armi_admin;


--
-- Name: COLUMN observation_tool_calls.observation_tool_call_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_tool_call_id) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.observation_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_attempt_id) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.call_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(call_no) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.action_type; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_type) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.provider_identity_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(provider_identity_digest) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.action_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_digest) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.completion_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(completion_status) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: COLUMN observation_tool_calls.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.observation_tool_calls TO armi_runtime;


--
-- Name: TABLE opportunities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.opportunities TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.opportunities TO armi_admin;


--
-- Name: COLUMN opportunities.opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(opportunity_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.evidence_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(evidence_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.eligibility_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(eligibility_status) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.current_disposition; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_disposition),UPDATE(current_disposition) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.available_after; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(available_after) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(expires_at) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.selected_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(selected_at) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.root_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(root_opportunity_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.predecessor_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(predecessor_opportunity_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.reconsideration_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reconsideration_no) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.resolved_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(resolved_at) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.source_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_kind) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.source_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_ref) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.source_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_version) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.source_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_digest) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.activity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activity_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: COLUMN opportunities.other_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(other_party_id) ON TABLE armi.opportunities TO armi_runtime;


--
-- Name: TABLE other_human_action_intent_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_action_intent_revisions TO armi_runtime;


--
-- Name: TABLE other_human_action_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_action_intents TO armi_runtime;


--
-- Name: COLUMN other_human_action_intents.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_revision_id) ON TABLE armi.other_human_action_intents TO armi_runtime;


--
-- Name: TABLE other_human_dialogue_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_dialogue_decisions TO armi_runtime;


--
-- Name: TABLE other_human_effects; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_effects TO armi_runtime;


--
-- Name: COLUMN other_human_effects.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.other_human_effects TO armi_runtime;


--
-- Name: COLUMN other_human_effects.settlement_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settlement_digest) ON TABLE armi.other_human_effects TO armi_runtime;


--
-- Name: COLUMN other_human_effects.settled_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(settled_at) ON TABLE armi.other_human_effects TO armi_runtime;


--
-- Name: TABLE other_human_input_interactions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_input_interactions TO armi_runtime;


--
-- Name: TABLE other_human_local_inbox_deliveries; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.other_human_local_inbox_deliveries TO armi_runtime;


--
-- Name: TABLE outbox_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.outbox_items TO armi_runtime;
GRANT SELECT ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.outbox_item_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(outbox_item_id) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(outbox_item_id) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(work_id) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.message_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(message_kind) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(message_kind) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.payload_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_digest) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(payload_digest) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(status),UPDATE(status) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.available_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(available_at),UPDATE(available_at) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(available_at),UPDATE(available_at) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.claimed_by; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claimed_by) ON TABLE armi.outbox_items TO armi_runtime;
GRANT UPDATE(claimed_by) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.claim_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claim_expires_at) ON TABLE armi.outbox_items TO armi_runtime;
GRANT UPDATE(claim_expires_at) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.claim_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(claim_token),UPDATE(claim_token) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(claim_token),UPDATE(claim_token) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_count),UPDATE(attempt_count) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(attempt_count) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.max_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_attempts) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(max_attempts) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.outbox_items TO armi_runtime;
GRANT UPDATE(last_error_code) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.delivered_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(delivered_at) ON TABLE armi.outbox_items TO armi_runtime;
GRANT UPDATE(delivered_at) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(trace_id) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.outbox_items TO armi_runtime;
GRANT INSERT(schema_version) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: COLUMN outbox_items.updated_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE armi.outbox_items TO armi_runtime;
GRANT UPDATE(updated_at) ON TABLE armi.outbox_items TO armi_admin;


--
-- Name: TABLE parties; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.parties TO armi_runtime;
GRANT SELECT ON TABLE armi.parties TO armi_admin;


--
-- Name: COLUMN parties.party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(party_id) ON TABLE armi.parties TO armi_runtime;


--
-- Name: COLUMN parties.party_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(party_kind) ON TABLE armi.parties TO armi_runtime;


--
-- Name: COLUMN parties.represented_subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(represented_subject_id) ON TABLE armi.parties TO armi_runtime;


--
-- Name: COLUMN parties.display_label; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(display_label) ON TABLE armi.parties TO armi_runtime;


--
-- Name: COLUMN parties.creator_role; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_role) ON TABLE armi.parties TO armi_runtime;


--
-- Name: COLUMN parties.declared_identity_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(declared_identity_key) ON TABLE armi.parties TO armi_runtime;


--
-- Name: TABLE permission_grants; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.permission_grants TO armi_runtime;
GRANT SELECT ON TABLE armi.permission_grants TO armi_admin;


--
-- Name: COLUMN permission_grants.grant_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(grant_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.capability_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_request_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.capability_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(capability_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.interaction_scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(interaction_scene_id) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.operation_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_class) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.audience_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(audience_scope) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.data_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(data_scope) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.valid_from; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(valid_from) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.valid_until; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(valid_until) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.max_uses; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_uses) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.consumed_uses; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(consumed_uses) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.max_payload_bytes; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_payload_bytes) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.scope_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scope_digest) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.revoked_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(revoked_at) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.workspace_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(workspace_scope) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.artifact_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(artifact_scope) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: COLUMN permission_grants.network_access; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(network_access) ON TABLE armi.permission_grants TO armi_runtime;


--
-- Name: TABLE policy_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.policy_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.policy_decisions TO armi_admin;


--
-- Name: COLUMN policy_decisions.is_current; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(is_current) ON TABLE armi.policy_decisions TO armi_runtime;


--
-- Name: TABLE prompt_documents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.prompt_documents TO armi_runtime;
GRANT SELECT ON TABLE armi.prompt_documents TO armi_admin;


--
-- Name: COLUMN prompt_documents.prompt_document_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(prompt_document_id) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: COLUMN prompt_documents.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: COLUMN prompt_documents.prompt_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(prompt_kind) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: COLUMN prompt_documents.write_authority; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(write_authority) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: COLUMN prompt_documents.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_revision_id),UPDATE(current_revision_id) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: COLUMN prompt_documents.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.prompt_documents TO armi_runtime;


--
-- Name: TABLE prompt_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.prompt_revisions TO armi_runtime;
GRANT SELECT ON TABLE armi.prompt_revisions TO armi_admin;


--
-- Name: COLUMN prompt_revisions.prompt_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(prompt_revision_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.prompt_document_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(prompt_document_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.revision_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(revision_no) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.previous_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(previous_revision_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.content_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(content_artifact_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.content_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(content_digest) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.author_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(author_party_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: COLUMN prompt_revisions.change_reason; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(change_reason) ON TABLE armi.prompt_revisions TO armi_runtime;


--
-- Name: TABLE relationship_experience_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.relationship_experience_links TO armi_runtime;


--
-- Name: TABLE relationship_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.relationship_revisions TO armi_runtime;


--
-- Name: TABLE relationships; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.relationships TO armi_runtime;


--
-- Name: COLUMN relationships.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_revision_id) ON TABLE armi.relationships TO armi_runtime;


--
-- Name: COLUMN relationships.head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(head_version) ON TABLE armi.relationships TO armi_runtime;


--
-- Name: TABLE runtime_bundle_activations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_bundle_activations TO armi_runtime;
GRANT SELECT ON TABLE armi.runtime_bundle_activations TO armi_admin;


--
-- Name: COLUMN runtime_bundle_activations.bundle_activation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_activation_id) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.bundle_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_version) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.bundle_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_digest) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.manifest_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(manifest_artifact_id) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.fixed_policy_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fixed_policy_digest) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.fixed_prompt_set_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fixed_prompt_set_digest) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.creator_asset_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_asset_digest) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: COLUMN runtime_bundle_activations.activated_by_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(activated_by_party_id) ON TABLE armi.runtime_bundle_activations TO armi_runtime;


--
-- Name: TABLE runtime_instances; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_instances TO armi_runtime;
GRANT SELECT ON TABLE armi.runtime_instances TO armi_admin;


--
-- Name: COLUMN runtime_instances.runtime_instance_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(runtime_instance_id) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.life_generation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(life_generation_id) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.bundle_activation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_activation_id) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.fence_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fence_token) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.runtime_instances TO armi_runtime;
GRANT UPDATE(status) ON TABLE armi.runtime_instances TO armi_admin;


--
-- Name: COLUMN runtime_instances.last_heartbeat_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_heartbeat_at) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.lease_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(lease_expires_at),UPDATE(lease_expires_at) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: COLUMN runtime_instances.stopped_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(stopped_at) ON TABLE armi.runtime_instances TO armi_runtime;
GRANT UPDATE(stopped_at) ON TABLE armi.runtime_instances TO armi_admin;


--
-- Name: COLUMN runtime_instances.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.runtime_instances TO armi_runtime;


--
-- Name: TABLE runtime_recovery_runs; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_runtime;
GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_admin;


--
-- Name: COLUMN runtime_recovery_runs.recovery_run_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(recovery_run_id) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.runtime_instance_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(runtime_instance_id) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.life_generation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(life_generation_id) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.bundle_activation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(bundle_activation_id) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.fence_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fence_token) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.requeued_work_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(requeued_work_count),UPDATE(requeued_work_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.terminal_work_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(terminal_work_count),UPDATE(terminal_work_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.requeued_outbox_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(requeued_outbox_count),UPDATE(requeued_outbox_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.dead_outbox_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(dead_outbox_count),UPDATE(dead_outbox_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_work_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_work_count),UPDATE(resumable_work_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_outbox_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_outbox_count),UPDATE(resumable_outbox_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.critical_artifact_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(critical_artifact_count),UPDATE(critical_artifact_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.blocker_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(blocker_count),UPDATE(blocker_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.summary_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(summary_digest) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_opportunity_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_opportunity_count),UPDATE(resumable_opportunity_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_cognitive_episode_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_cognitive_episode_count),UPDATE(resumable_cognitive_episode_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_model_attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_model_attempt_count),UPDATE(resumable_model_attempt_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_candidate_validation_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_candidate_validation_count),UPDATE(resumable_candidate_validation_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_subject_commit_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_subject_commit_count),UPDATE(resumable_subject_commit_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_capability_request_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_capability_request_count),UPDATE(resumable_capability_request_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_response_operation_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_response_operation_count),UPDATE(resumable_response_operation_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_effect_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_effect_count),UPDATE(resumable_effect_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_effect_outbox_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_effect_outbox_count),UPDATE(resumable_effect_outbox_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_effect_attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_effect_attempt_count),UPDATE(resumable_effect_attempt_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.reliable_effect_observation_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reliable_effect_observation_count),UPDATE(reliable_effect_observation_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.creator_response_delivery_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_response_delivery_count),UPDATE(creator_response_delivery_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_web_observation_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_web_observation_count),UPDATE(resumable_web_observation_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.unknown_web_observation_attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(unknown_web_observation_attempt_count),UPDATE(unknown_web_observation_attempt_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_web_research_intent_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_web_research_intent_count),UPDATE(resumable_web_research_intent_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.pending_web_evidence_acceptance_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(pending_web_evidence_acceptance_count),UPDATE(pending_web_evidence_acceptance_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_web_cognition_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_web_cognition_count),UPDATE(resumable_web_cognition_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_admin_correction_work_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_admin_correction_work_count),UPDATE(resumable_admin_correction_work_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_codex_task_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_codex_task_count),UPDATE(resumable_codex_task_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.resumable_codex_effect_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(resumable_codex_effect_count),UPDATE(resumable_codex_effect_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: COLUMN runtime_recovery_runs.pending_codex_result_acceptance_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(pending_codex_result_acceptance_count),UPDATE(pending_codex_result_acceptance_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;


--
-- Name: TABLE scene_timeline_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.scene_timeline_items TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.scene_timeline_items TO armi_admin;


--
-- Name: COLUMN scene_timeline_items.timeline_item_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(timeline_item_id) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.source_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_kind) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.source_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_ref) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.source_event_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_event_no) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.result_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(result_status) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.occurred_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(occurred_at) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: COLUMN scene_timeline_items.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.scene_timeline_items TO armi_runtime;


--
-- Name: TABLE schema_migrations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.schema_migrations TO armi_runtime;
GRANT SELECT ON TABLE armi.schema_migrations TO armi_admin;
GRANT SELECT ON TABLE armi.schema_migrations TO armi_migrator;


--
-- Name: TABLE sleep_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.sleep_decisions TO armi_runtime;
GRANT SELECT ON TABLE armi.sleep_decisions TO armi_admin;


--
-- Name: TABLE subject_commits; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.subject_commits TO armi_runtime;
GRANT SELECT ON TABLE armi.subject_commits TO armi_admin;


--
-- Name: TABLE subject_component_heads; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subject_component_heads TO armi_runtime;
GRANT SELECT ON TABLE armi.subject_component_heads TO armi_admin;


--
-- Name: COLUMN subject_component_heads.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.subject_component_heads TO armi_runtime;


--
-- Name: COLUMN subject_component_heads.component_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_kind) ON TABLE armi.subject_component_heads TO armi_runtime;


--
-- Name: COLUMN subject_component_heads.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_revision_id),UPDATE(current_revision_id) ON TABLE armi.subject_component_heads TO armi_runtime;
GRANT UPDATE(current_revision_id) ON TABLE armi.subject_component_heads TO armi_admin;


--
-- Name: COLUMN subject_component_heads.component_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_version),UPDATE(component_version) ON TABLE armi.subject_component_heads TO armi_runtime;
GRANT UPDATE(component_version) ON TABLE armi.subject_component_heads TO armi_admin;


--
-- Name: TABLE subject_component_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT SELECT ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.component_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_revision_id) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(component_revision_id) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(subject_id) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.component_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_kind) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(component_kind) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.component_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_version) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(component_version) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.previous_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(previous_revision_id) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(previous_revision_id) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.origin_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(origin_kind) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(origin_kind) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.origin_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(origin_ref) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(origin_ref) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(subject_commit_id) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.semantic_payload; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(semantic_payload) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(semantic_payload) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(privacy_scope) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(proposal_ref) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: COLUMN subject_component_revisions.semantic_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(semantic_digest) ON TABLE armi.subject_component_revisions TO armi_runtime;
GRANT INSERT(semantic_digest) ON TABLE armi.subject_component_revisions TO armi_admin;


--
-- Name: TABLE subjective_memories; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.subjective_memories TO armi_runtime;


--
-- Name: COLUMN subjective_memories.current_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_revision_id) ON TABLE armi.subjective_memories TO armi_runtime;


--
-- Name: COLUMN subjective_memories.head_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(head_version) ON TABLE armi.subjective_memories TO armi_runtime;


--
-- Name: TABLE subjective_memory_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.subjective_memory_revisions TO armi_runtime;


--
-- Name: TABLE subjects; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subjects TO armi_runtime;
GRANT SELECT ON TABLE armi.subjects TO armi_admin;


--
-- Name: COLUMN subjects.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.singleton_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(singleton_key) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.birth_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(birth_request_id) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.birth_idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(birth_idempotency_key) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.birth_manifest_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(birth_manifest_digest) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.current_generation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_generation_id) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.current_bundle_activation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(current_bundle_activation_id) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.subject_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(subject_version) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: COLUMN subjects.state_epoch; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(state_epoch) ON TABLE armi.subjects TO armi_admin;
GRANT UPDATE(state_epoch) ON TABLE armi.subjects TO armi_runtime;


--
-- Name: TABLE web_evidence_sources; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_evidence_sources TO armi_runtime;
GRANT SELECT ON TABLE armi.web_evidence_sources TO armi_admin;


--
-- Name: COLUMN web_evidence_sources.web_evidence_source_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(web_evidence_source_id) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.evidence_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(evidence_id) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.observation_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_attempt_id) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.citation_no; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(citation_no) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.source_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_artifact_id) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.canonical_url_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(canonical_url_digest) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.title_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(title_digest) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.citation_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(citation_digest) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.acquisition_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(acquisition_kind) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: COLUMN web_evidence_sources.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.web_evidence_sources TO armi_runtime;


--
-- Name: TABLE web_observation_requests; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_observation_requests TO armi_runtime;
GRANT SELECT ON TABLE armi.web_observation_requests TO armi_admin;


--
-- Name: COLUMN web_observation_requests.web_observation_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(web_observation_request_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.runtime_instance_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(runtime_instance_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.fence_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fence_token) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(idempotency_key) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.operation_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_class) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.request_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_artifact_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.request_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(request_digest) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.binding_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(binding_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.deadline_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(deadline_at) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.max_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_attempts) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.max_cost_microyuan; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_cost_microyuan) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.result_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_artifact_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.result_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_digest) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: COLUMN web_observation_requests.web_research_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(web_research_intent_id) ON TABLE armi.web_observation_requests TO armi_runtime;


--
-- Name: TABLE web_research_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_research_intents TO armi_runtime;
GRANT SELECT ON TABLE armi.web_research_intents TO armi_admin;


--
-- Name: COLUMN web_research_intents.web_research_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(web_research_intent_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.source_opportunity_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(source_opportunity_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(scene_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.creator_party_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_party_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.purpose; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(purpose) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.operation_class; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(operation_class) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.query_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(query_artifact_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.query_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(query_digest) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(idempotency_key) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.admission_work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(admission_work_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.web_observation_request_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(web_observation_request_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- Name: COLUMN web_research_intents.schema_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(schema_version) ON TABLE armi.web_research_intents TO armi_runtime;


--
-- PostgreSQL database dump complete
--

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4 (Debian 18.4-1.pgdg13+1)
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: capabilities; Type: TABLE DATA; Schema: armi; Owner: -
--

INSERT INTO armi.capabilities VALUES ('01985d00-0000-7000-8000-000000000027', 'creator.scene.reply', 'creator-interface', 'send', 'armi.creator-scene-reply-scope.v1', 'available', 'creator_response_receipt', 1, 'sha256:4c13c64439fd4c2df3c6daa43e1ebc2f8c58e7e65de22fe9eb5bc1ee9297b657');
INSERT INTO armi.capabilities VALUES ('01985d00-0000-7000-8000-000000000038', 'codex.delegated-work', 'codex-runner', 'execute', 'armi.codex-delegated-work-scope.v1', 'available', 'codex_runner_openai_python_sdk_isolation_v2', 2, 'sha256:784efc4ae76060da99d37fd2aaa2872e105ade73a46dee212f4660c4707c1d87');


--
-- PostgreSQL database dump complete
--
