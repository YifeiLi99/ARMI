-- Current ARMI schema tables owned by this baseline module.

CREATE TABLE armi.schema_baseline_identity (
    singleton_key boolean DEFAULT true NOT NULL,
    baseline_identity text NOT NULL,
    resource_digest text NOT NULL DEFAULT '',
    installed_catalog_digest text NOT NULL DEFAULT '',
    role_policy_digest text NOT NULL DEFAULT '',
    installed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT schema_baseline_identity_pkey PRIMARY KEY (singleton_key),
    CONSTRAINT schema_baseline_identity_singleton_check CHECK (singleton_key),
    CONSTRAINT schema_baseline_identity_value_check CHECK (
        baseline_identity = 'armi.schema-baseline.v70'::text
    ),
    CONSTRAINT schema_baseline_identity_resource_digest_check CHECK (
        resource_digest = '' OR resource_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT schema_baseline_identity_catalog_digest_check CHECK (
        installed_catalog_digest = '' OR installed_catalog_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT schema_baseline_identity_role_digest_check CHECK (
        role_policy_digest = '' OR role_policy_digest ~ '^sha256:[0-9a-f]{64}$'
    )
);

INSERT INTO armi.schema_baseline_identity (baseline_identity)
VALUES ('armi.schema-baseline.v70');

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
    identity_key_digest text,
    identity_key_bound_at timestamp(6) with time zone,
    CONSTRAINT deployment_environments_identity_key_pair CHECK ((identity_key_digest IS NULL) = (identity_key_bound_at IS NULL)),
    CONSTRAINT deployment_environments_identity_key_digest CHECK (identity_key_digest IS NULL OR identity_key_digest ~ '^sha256:[0-9a-f]{64}$'),
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT deployment_environments_check CHECK (((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text])) OR ((NOT resettable) AND (NOT test_controls_enabled)))),
    CONSTRAINT deployment_environments_check1 CHECK (((NOT test_controls_enabled) OR (environment_kind = ANY (ARRAY['system_test'::text, 'acceptance'::text])))),
    CONSTRAINT deployment_environments_environment_id_check CHECK ((uuid_extract_version(environment_id) = 7)),
    CONSTRAINT deployment_environments_environment_kind_check CHECK ((environment_kind = ANY (ARRAY['development'::text, 'system_test'::text, 'acceptance'::text, 'active'::text, 'restore_quarantine'::text]))),
    CONSTRAINT deployment_environments_incarnation_check CHECK ((incarnation > 0)),
    CONSTRAINT deployment_environments_singleton_key_check CHECK (singleton_key)
);


--
-- Name: prompt_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.prompt_revisions (
    subject_id uuid NOT NULL,
    prompt_kind text NOT NULL,
    status text DEFAULT 'active' NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    CONSTRAINT prompt_revisions_kind_check CHECK (prompt_kind IN ('personality_anchor','creator_guidance','subject_guidance')),
    CONSTRAINT prompt_revisions_status_check CHECK (status IN ('active','inactive')),
    CONSTRAINT prompt_revisions_anchor_check CHECK (prompt_kind <> 'personality_anchor' OR (status='active' AND change_reason='birth' AND revision_no=1 AND admin_change_id IS NULL)),
    CONSTRAINT prompt_revisions_kind_reason_check CHECK (
        (change_reason='birth' AND prompt_kind='personality_anchor') OR
        (change_reason IN ('subject_created','subject_revised') AND prompt_kind='subject_guidance') OR
        (change_reason IN ('created','revised','deactivated') AND (prompt_kind='creator_guidance' OR admin_change_id IS NOT NULL))),
    CONSTRAINT prompt_revisions_document_id_check CHECK (uuid_extract_version(prompt_document_id)=7),
    prompt_revision_id uuid NOT NULL,
    prompt_document_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    content_artifact_id uuid NOT NULL,
    content_digest text NOT NULL,
    author_party_id uuid,
    subject_commit_id uuid,
    change_reason text NOT NULL,
    activated_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    admin_change_id uuid,
    CONSTRAINT prompt_revisions_change_reason_check CHECK ((change_reason = ANY (ARRAY['birth'::text, 'created'::text, 'revised'::text, 'deactivated'::text, 'subject_created'::text, 'subject_revised'::text]))),
    CONSTRAINT prompt_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT prompt_revisions_check1 CHECK ((((change_reason = 'birth'::text) AND (revision_no = 1)) OR (change_reason <> 'birth'::text))),
    CONSTRAINT prompt_revisions_check2 CHECK ((((change_reason = ANY (ARRAY['subject_created'::text, 'subject_revised'::text])) AND (subject_commit_id IS NOT NULL)) OR ((change_reason <> ALL (ARRAY['subject_created'::text, 'subject_revised'::text])) AND (subject_commit_id IS NULL)))),
    CONSTRAINT prompt_revisions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT prompt_revisions_prompt_revision_id_check CHECK ((uuid_extract_version(prompt_revision_id) = 7)),
    CONSTRAINT prompt_revisions_revision_no_check CHECK ((revision_no >= 1)),
    CONSTRAINT prompt_revisions_admin_provenance CHECK (((admin_change_id IS NULL AND author_party_id IS NOT NULL) OR (admin_change_id IS NOT NULL AND author_party_id IS NULL AND subject_commit_id IS NULL)))
);


--
-- Name: runtime_instances; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.runtime_instances (
    runtime_instance_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    bundle_activation_id uuid NOT NULL,
    fence_token bigint NOT NULL,
    status text NOT NULL,
    process_pid bigint,
    process_created_at_microseconds bigint,
    process_executable_identity text,
    process_command_identity text,
    environment_id uuid,
    process_incarnation bigint,
    started_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    last_heartbeat_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    lease_expires_at timestamp(6) with time zone NOT NULL,
    stopped_at timestamp(6) with time zone,
    recovery_status text,
    recovery_started_at timestamp(6) with time zone,
    recovery_completed_at timestamp(6) with time zone,
    recovery_blocker_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT runtime_instances_recovery_status_check CHECK (recovery_status IN ('running', 'safe', 'blocked', 'abandoned')),
    CONSTRAINT runtime_instances_recovery_state_check CHECK (
        (recovery_status IS NULL AND recovery_started_at IS NULL AND recovery_completed_at IS NULL AND recovery_blocker_count = 0)
        OR (recovery_status IS NOT NULL AND recovery_started_at IS NOT NULL
            AND ((recovery_status = 'running' AND recovery_completed_at IS NULL)
                 OR (recovery_status <> 'running' AND recovery_completed_at IS NOT NULL)))
    ),
    CONSTRAINT runtime_instances_recovery_blockers_check CHECK (
        recovery_blocker_count >= 0 AND (recovery_status <> 'safe' OR recovery_blocker_count = 0)
        AND (recovery_status <> 'blocked' OR recovery_blocker_count > 0)
    ),
    CONSTRAINT runtime_instances_check CHECK ((lease_expires_at > last_heartbeat_at)),
    CONSTRAINT runtime_instances_check1 CHECK ((((status = 'active'::text) AND (stopped_at IS NULL)) OR ((status = ANY (ARRAY['fenced'::text, 'stopped'::text])) AND (stopped_at IS NOT NULL)))),
    CONSTRAINT runtime_instances_fence_token_check CHECK ((fence_token > 0)),
    CONSTRAINT runtime_instances_process_identity_check CHECK (((status <> 'active'::text) OR ((process_pid IS NOT NULL) AND (process_pid > 0) AND (process_created_at_microseconds IS NOT NULL) AND (process_created_at_microseconds > 0) AND (process_executable_identity IS NOT NULL) AND (process_executable_identity <> ''::text) AND (process_command_identity IS NOT NULL) AND (process_command_identity ~ '^sha256:[0-9a-f]{64}$'::text) AND (environment_id IS NOT NULL) AND (uuid_extract_version(environment_id) = 7) AND (process_incarnation IS NOT NULL) AND (process_incarnation > 0)))),
    CONSTRAINT runtime_instances_runtime_instance_id_check CHECK ((uuid_extract_version(runtime_instance_id) = 7)),
    CONSTRAINT runtime_instances_status_check CHECK ((status = ANY (ARRAY['active'::text, 'fenced'::text, 'stopped'::text])))
);

--
--



--
-- Name: subject_component_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subject_component_revisions (
    is_current boolean DEFAULT false NOT NULL,
    component_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    component_kind text NOT NULL,
    component_version bigint NOT NULL,
    previous_revision_id uuid,
    origin_kind text NOT NULL,
    origin_ref uuid NOT NULL,
    subject_commit_id uuid,
    semantic_payload jsonb NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    proposal_ref text,
    data_rights_redacted_at timestamp(6) with time zone,
    admin_change_id uuid,
    CONSTRAINT subject_component_revisions_component_kind_check CHECK ((component_kind = ANY (ARRAY['self'::text, 'life_mode'::text]))),
    CONSTRAINT subject_component_revisions_component_revision_id_check CHECK ((uuid_extract_version(component_revision_id) = 7)),
    CONSTRAINT subject_component_revisions_component_version_check CHECK ((component_version > 0)),
    CONSTRAINT subject_component_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction'),
    CONSTRAINT subject_component_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (component_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL)) OR ((origin_kind = ANY (ARRAY['admin_correction'::text,'data_rights'::text])) AND (component_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)))),
    CONSTRAINT subject_component_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text,  'data_rights'::text]))),
    CONSTRAINT subject_component_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
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
    current_bundle_activation_id uuid NOT NULL UNIQUE,
    birth_contract_digest text NOT NULL,
    birth_creator_party_id uuid NOT NULL,
    CONSTRAINT subjects_birth_contract_digest_check CHECK (birth_contract_digest ~ '^sha256:[0-9a-f]{64}$'),
    subject_version bigint DEFAULT 0 NOT NULL,
    state_epoch bigint DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    maintenance_latest_accepted_ordinal bigint DEFAULT 0 NOT NULL,
    maintenance_processed_through_ordinal bigint DEFAULT 0 NOT NULL,
    CONSTRAINT subjects_maintenance_coverage_check CHECK (
        maintenance_processed_through_ordinal >= 0 AND
        maintenance_latest_accepted_ordinal >= maintenance_processed_through_ordinal),
    born_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT subjects_birth_idempotency_key_check CHECK (((length(birth_idempotency_key) >= 1) AND (length(birth_idempotency_key) <= 128) AND (birth_idempotency_key ~ '^[A-Za-z0-9._:-]+$'::text))),
    CONSTRAINT subjects_birth_manifest_digest_check CHECK ((birth_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT subjects_birth_request_id_check CHECK ((uuid_extract_version(birth_request_id) = 7)),
    CONSTRAINT subjects_current_bundle_activation_id_check CHECK ((uuid_extract_version(current_bundle_activation_id) = 7)),
    CONSTRAINT subjects_singleton_key_check CHECK ((singleton_key = 1)),
    CONSTRAINT subjects_state_epoch_check CHECK ((state_epoch >= 0)),
    CONSTRAINT subjects_status_check CHECK ((status = ANY (ARRAY['active'::text, 'blocked'::text, 'deceased'::text]))),
    CONSTRAINT subjects_subject_id_check CHECK ((uuid_extract_version(subject_id) = 7)),
    CONSTRAINT subjects_subject_version_check CHECK ((subject_version >= 0))
);


CREATE TABLE armi.mind_revisions (
    is_current boolean DEFAULT false NOT NULL,
    mind_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    mind_version bigint NOT NULL,
    previous_revision_id uuid,
    origin_kind text NOT NULL,
    origin_ref uuid NOT NULL,
    subject_commit_id uuid,
    semantic_payload jsonb NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    proposal_ref text,
    data_rights_redacted_at timestamp(6) with time zone,
    admin_change_id uuid,
    CONSTRAINT mind_revisions_mind_revision_id_check CHECK ((uuid_extract_version(mind_revision_id) = 7)),
    CONSTRAINT mind_revisions_mind_version_check CHECK ((mind_version > 0)),
    CONSTRAINT mind_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction'),
    CONSTRAINT mind_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (mind_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (mind_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL)) OR ((origin_kind = ANY (ARRAY['admin_correction'::text,'data_rights'::text])) AND (mind_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)))),
    CONSTRAINT mind_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text,  'data_rights'::text]))),
    CONSTRAINT mind_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
    CONSTRAINT mind_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT mind_revisions_semantic_payload_check CHECK ((jsonb_typeof(semantic_payload) = 'object'::text))
);
