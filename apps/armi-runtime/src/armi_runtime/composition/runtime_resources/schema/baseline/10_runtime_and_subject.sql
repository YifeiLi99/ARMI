-- Current ARMI schema tables owned by this baseline module.

CREATE TABLE armi.schema_baseline_identity (
    singleton_key boolean DEFAULT true NOT NULL,
    baseline_identity text NOT NULL,
    installed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT schema_baseline_identity_pkey PRIMARY KEY (singleton_key),
    CONSTRAINT schema_baseline_identity_singleton_check CHECK (singleton_key),
    CONSTRAINT schema_baseline_identity_value_check CHECK (
        baseline_identity = 'armi.schema-baseline.v1'::text
    )
);

INSERT INTO armi.schema_baseline_identity (baseline_identity)
VALUES ('armi.schema-baseline.v1');

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
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT deployment_environments_check CHECK (((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text])) OR ((NOT resettable) AND (NOT test_controls_enabled)))),
    CONSTRAINT deployment_environments_check1 CHECK (((NOT test_controls_enabled) OR (environment_kind = ANY (ARRAY['system_test'::text, 'acceptance'::text])))),
    CONSTRAINT deployment_environments_environment_id_check CHECK ((uuid_extract_version(environment_id) = 7)),
    CONSTRAINT deployment_environments_environment_kind_check CHECK ((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text, 'active'::text, 'restore_quarantine'::text]))),
    CONSTRAINT deployment_environments_incarnation_check CHECK ((incarnation > 0)),
    CONSTRAINT deployment_environments_singleton_key_check CHECK (singleton_key)
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
-- Name: runtime_bundle_activations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_bundle_activations (
    bundle_activation_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    bundle_version text NOT NULL,
    fixed_policy_digest text NOT NULL,
    model_binding text,
    status text NOT NULL,
    activated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    deactivated_at timestamp(6) with time zone,
    activated_by_party_id uuid NOT NULL,
    CONSTRAINT runtime_bundle_activations_bundle_activation_id_check CHECK ((uuid_extract_version(bundle_activation_id) = 7)),
    CONSTRAINT runtime_bundle_activations_bundle_version_check CHECK ((bundle_version = '0.0.0'::text)),
    CONSTRAINT runtime_bundle_activations_check CHECK ((((status = 'current'::text) AND (deactivated_at IS NULL)) OR ((status = 'superseded'::text) AND (deactivated_at IS NOT NULL)))),
    CONSTRAINT runtime_bundle_activations_fixed_policy_digest_check CHECK ((fixed_policy_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
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
    CONSTRAINT runtime_instances_check CHECK ((lease_expires_at > last_heartbeat_at)),
    CONSTRAINT runtime_instances_check1 CHECK ((((status = 'active'::text) AND (stopped_at IS NULL)) OR ((status = ANY (ARRAY['fenced'::text, 'stopped'::text])) AND (stopped_at IS NOT NULL)))),
    CONSTRAINT runtime_instances_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT runtime_instances_runtime_instance_id_check CHECK ((uuid_extract_version(runtime_instance_id) = 7)),
    CONSTRAINT runtime_instances_status_check CHECK ((status = ANY (ARRAY['active'::text, 'fenced'::text, 'stopped'::text])))
);

--
-- Name: runtime_recovery_metrics; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_recovery_metrics (
    recovery_run_id uuid NOT NULL,
    metric_kind text NOT NULL,
    metric_value integer NOT NULL,
    CONSTRAINT runtime_recovery_metrics_kind_check CHECK ((metric_kind ~ '^[a-z][a-z0-9._-]{0,127}$'::text)),
    CONSTRAINT runtime_recovery_metrics_value_check CHECK ((metric_value >= 0))
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
    blocker_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT runtime_recovery_runs_blocker_count_check CHECK ((blocker_count >= 0)),
    CONSTRAINT runtime_recovery_runs_check CHECK ((((status = 'running'::text) AND (completed_at IS NULL)) OR ((status = ANY (ARRAY['safe'::text, 'blocked'::text, 'abandoned'::text])) AND (completed_at IS NOT NULL)))),
    CONSTRAINT runtime_recovery_runs_check1 CHECK (((status <> 'safe'::text) OR (blocker_count = 0))),
    CONSTRAINT runtime_recovery_runs_check2 CHECK (((status <> 'blocked'::text) OR (blocker_count > 0))),
    CONSTRAINT runtime_recovery_runs_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT runtime_recovery_runs_recovery_run_id_check CHECK ((uuid_extract_version(recovery_run_id) = 7)),
    CONSTRAINT runtime_recovery_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'safe'::text, 'blocked'::text, 'abandoned'::text])))
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
    runtime_instance_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    trace_id text NOT NULL,
    committed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT subject_commits_base_state_epoch_check CHECK ((base_state_epoch >= 0)),
    CONSTRAINT subject_commits_base_subject_version_check CHECK ((base_subject_version >= 0)),
    CONSTRAINT subject_commits_check CHECK ((new_subject_version = (base_subject_version + 1))),
    CONSTRAINT subject_commits_fence_token_check CHECK ((fence_token > 0)),
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
    CONSTRAINT subject_component_revisions_component_kind_check CHECK ((component_kind = ANY (ARRAY['self'::text, 'mind'::text, 'life_mode'::text]))),
    CONSTRAINT subject_component_revisions_component_revision_id_check CHECK ((uuid_extract_version(component_revision_id) = 7)),
    CONSTRAINT subject_component_revisions_component_version_check CHECK ((component_version > 0)),
    CONSTRAINT subject_component_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (component_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL)) OR ((origin_kind = 'admin_correction'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'module_migration'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)))),
    CONSTRAINT subject_component_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text, 'module_migration'::text]))),
    CONSTRAINT subject_component_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
    CONSTRAINT subject_component_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT subject_component_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT subject_component_revisions_semantic_payload_check CHECK ((jsonb_typeof(semantic_payload) = 'object'::text))
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
