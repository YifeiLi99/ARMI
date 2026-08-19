-- Current ARMI schema tables owned by this baseline module.

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
    codex_task_source_id uuid,
    task_manifest_digest text,
    validator_id text,
    CONSTRAINT action_intent_revisions_bytes_check CHECK (((response_bytes IS NULL) OR ((response_bytes >= 1) AND (response_bytes <= 65536)))),
    CONSTRAINT action_intent_revisions_digest_check CHECK (((response_digest IS NULL) OR (response_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT action_intent_revisions_family_check CHECK ((((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL) AND (validator_id IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'local.other-human-inbox.deliver'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL) AND (validator_id IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'external.group.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'social_group'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL) AND (validator_id IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'external.private.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL) AND (validator_id IS NULL)) OR ((response_artifact_id IS NULL) AND (response_digest IS NULL) AND (response_bytes IS NULL) AND (media_type IS NULL) AND (capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (codex_task_source_id IS NOT NULL) AND (task_manifest_digest IS NOT NULL) AND (task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text) AND (validator_id IS NOT NULL)))),
    CONSTRAINT action_intent_revisions_id_check CHECK ((uuid_extract_version(action_intent_revision_id) = 7)),
    CONSTRAINT action_intent_revisions_response_shape_check CHECK ((((response_artifact_id IS NULL) = (response_digest IS NULL)) AND ((response_digest IS NULL) = (response_bytes IS NULL)) AND ((response_bytes IS NULL) = (media_type IS NULL)))),
    CONSTRAINT action_intent_revisions_revision_no_check CHECK ((revision_no > 0))
);

--
-- Name: action_intents; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.action_intents (
    action_intent_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    context_party_id uuid NOT NULL,
    root_opportunity_id uuid NOT NULL,
    purpose text NOT NULL,
    current_revision_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    action_kind text NOT NULL,
    operation_ref uuid NOT NULL,
    CONSTRAINT action_intents_id_check CHECK ((uuid_extract_version(action_intent_id) = 7)),
    CONSTRAINT action_intents_kind_check CHECK ((action_kind = ANY (ARRAY['party_response'::text, 'codex_delegation'::text]))),
    CONSTRAINT action_intents_operation_ref_check CHECK ((uuid_extract_version(operation_ref) = 7)),
    CONSTRAINT action_intents_purpose_check CHECK ((purpose = ANY (ARRAY['respond_to_creator'::text, 'respond_to_other_human'::text, 'delegate_codex_work'::text]))),
    CONSTRAINT action_intents_shape_check CHECK ((((action_kind = 'party_response'::text) AND (purpose = ANY (ARRAY['respond_to_creator'::text, 'respond_to_other_human'::text]))) OR ((action_kind = 'codex_delegation'::text) AND (purpose = 'delegate_codex_work'::text))))
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
    CONSTRAINT capabilities_availability_chk CHECK ((availability_status = ANY (ARRAY['available'::text, 'unavailable'::text]))),
    CONSTRAINT capabilities_id_v7_chk CHECK (("substring"((capability_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capabilities_kind_chk CHECK ((capability_kind = ANY (ARRAY['creator.scene.reply'::text, 'codex.delegated-work'::text, 'local.other-human-inbox.deliver'::text, 'external.group.message.send'::text, 'external.private.message.send'::text]))),
    CONSTRAINT capabilities_operation_chk CHECK ((((capability_kind = ANY (ARRAY['creator.scene.reply'::text, 'local.other-human-inbox.deliver'::text, 'external.group.message.send'::text, 'external.private.message.send'::text])) AND (operation_class = 'send'::text)) OR ((capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text)))),
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
    reason_code text,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT capability_decisions_digest_chk CHECK ((command_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT capability_decisions_id_v7_chk CHECK (("substring"((capability_decision_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capability_decisions_kind_chk CHECK ((decision_kind = ANY (ARRAY['grant'::text, 'limit'::text, 'deny'::text, 'revoke'::text, 'expire'::text]))),
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
    current_status text DEFAULT 'pending'::text NOT NULL,
    request_version bigint DEFAULT 1 NOT NULL,
    resolved_by_party_id uuid,
    resolution_reason_class text,
    resolved_at timestamp(6) with time zone,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT capability_requests_id_v7_chk CHECK (("substring"((capability_request_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT capability_requests_kind_chk CHECK ((capability_kind = ANY (ARRAY['creator.scene.reply'::text, 'codex.delegated-work'::text]))),
    CONSTRAINT capability_requests_operation_chk CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text)) OR ((capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text)))),
    CONSTRAINT capability_requests_proposal_chk CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT capability_requests_resolution_chk CHECK ((((current_status = 'pending'::text) AND (request_version = 1) AND (resolved_by_party_id IS NULL) AND (resolution_reason_class IS NULL) AND (resolved_at IS NULL)) OR ((current_status <> 'pending'::text) AND (request_version > 1) AND (resolved_by_party_id IS NOT NULL) AND (resolved_at IS NOT NULL)))),
    CONSTRAINT capability_requests_scope_chk CHECK ((((capability_kind = 'creator.scene.reply'::text) AND (audience_scope IS NOT NULL) AND (audience_scope = 'creator'::text) AND (data_scope IS NOT NULL) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (workspace_scope IS NULL) AND (artifact_scope IS NULL) AND (network_access IS NULL) AND ((requested_valid_for_seconds >= 60) AND (requested_valid_for_seconds <= 604800)) AND ((requested_max_uses >= 1) AND (requested_max_uses <= 16)) AND (requested_max_payload_bytes IS NOT NULL) AND ((requested_max_payload_bytes >= 1) AND (requested_max_payload_bytes <= 65536))) OR ((capability_kind = 'codex.delegated-work'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (workspace_scope IS NOT NULL) AND (workspace_scope = 'isolated_ephemeral'::text) AND (artifact_scope IS NOT NULL) AND (artifact_scope = 'explicit_only'::text) AND (network_access IS NOT NULL) AND (network_access = false) AND ((requested_valid_for_seconds >= 60) AND (requested_valid_for_seconds <= 3600)) AND (requested_max_uses = 1) AND (requested_max_payload_bytes IS NULL)))),
    CONSTRAINT capability_requests_status_chk CHECK ((current_status = ANY (ARRAY['pending'::text, 'granted'::text, 'limited'::text, 'denied'::text, 'revoked'::text, 'expired'::text]))),
    CONSTRAINT capability_requests_version_chk CHECK ((request_version > 0))
);

--
-- Name: dialogue_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.dialogue_decisions (
    dialogue_decision_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid,
    subject_commit_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    context_party_id uuid NOT NULL,
    proposal_ref text,
    decision_kind text NOT NULL,
    reason_class text,
    action_intent_id uuid,
    effect_id uuid,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    operation_ref uuid NOT NULL,
    CONSTRAINT dialogue_decisions_id_check CHECK ((uuid_extract_version(dialogue_decision_id) = 7)),
    CONSTRAINT dialogue_decisions_kind_check CHECK ((decision_kind = ANY (ARRAY['reply'::text, 'decline'::text, 'silence'::text, 'defer'::text, 'end_conversation'::text]))),
    CONSTRAINT dialogue_decisions_operation_ref_check CHECK ((uuid_extract_version(operation_ref) = 7)),
    CONSTRAINT dialogue_decisions_shape_check CHECK ((((decision_kind = 'reply'::text) AND (proposal_ref IS NOT NULL) AND (action_intent_id IS NOT NULL)) OR ((decision_kind <> 'reply'::text) AND (action_intent_id IS NULL) AND (effect_id IS NULL))))
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
    claim_token bigint NOT NULL,
    dispatch_state text NOT NULL,
    result_status text,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT effect_attempts_adapter_binding_check CHECK ((adapter_binding = ANY (ARRAY['armi.local-inbox-adapter.postgresql-v1'::text, 'armi.external-message-adapter.v1'::text, 'armi.codex-runner.openai-python-sdk-v1'::text]))),
    CONSTRAINT effect_attempts_attempt_no_check CHECK (((attempt_no >= 1) AND (attempt_no <= 2))),
    CONSTRAINT effect_attempts_check CHECK ((((dispatch_state = 'prepared'::text) AND (result_status IS NULL) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'dispatching'::text) AND (result_status IS NULL) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status IS NOT NULL) AND (settled_at IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = ANY (ARRAY['failed'::text, 'cancelled'::text])) AND (dispatched_at IS NULL)))))),
    CONSTRAINT effect_attempts_check1 CHECK (((result_status = ANY (ARRAY['failed'::text, 'unknown'::text])) = (error_code IS NOT NULL))),
    CONSTRAINT effect_attempts_claim_token_check CHECK ((claim_token > 0)),
    CONSTRAINT effect_attempts_dispatch_state_check CHECK ((dispatch_state = ANY (ARRAY['prepared'::text, 'dispatching'::text, 'settled'::text]))),
    CONSTRAINT effect_attempts_effect_attempt_id_check CHECK ((uuid_extract_version(effect_attempt_id) = 7)),
    CONSTRAINT effect_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'::text))),
    CONSTRAINT effect_attempts_result_status_check CHECK ((result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text])))
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
    receiver_external_ref text,
    CONSTRAINT effect_observations_check CHECK (((observation_kind = 'receipt'::text) = (receiver_ref IS NOT NULL))),
    CONSTRAINT effect_observations_check1 CHECK (((observation_kind = 'ambiguous'::text) = (reliability = 'inconclusive'::text))),
    CONSTRAINT effect_observations_effect_observation_id_check CHECK ((uuid_extract_version(effect_observation_id) = 7)),
    CONSTRAINT effect_observations_external_ref_check CHECK (((receiver_external_ref IS NULL) OR (receiver_external_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text))),
    CONSTRAINT effect_observations_external_ref_shape_check CHECK (((receiver_external_ref IS NULL) OR (observation_kind = 'receipt'::text))),
    CONSTRAINT effect_observations_observation_digest_check CHECK ((observation_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effect_observations_observation_kind_check CHECK ((observation_kind = ANY (ARRAY['receipt'::text, 'query'::text, 'rejection'::text, 'ambiguous'::text, 'runner_verified'::text, 'runner_failed'::text, 'runner_unknown'::text, 'runner_cancelled'::text]))),
    CONSTRAINT effect_observations_receiver_ref_check CHECK (((receiver_ref IS NULL) OR (uuid_extract_version(receiver_ref) = 7))),
    CONSTRAINT effect_observations_reliability_check CHECK ((reliability = ANY (ARRAY['reliable'::text, 'inconclusive'::text])))
);

--
-- Name: effect_outbox_items; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effect_outbox_items (
    effect_outbox_item_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    message_kind text NOT NULL,
    status text NOT NULL,
    available_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    cancelled_at timestamp(6) with time zone,
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
    CONSTRAINT effect_outbox_items_status_check CHECK ((status = ANY (ARRAY['ready'::text, 'claimed'::text, 'delivered'::text, 'dead'::text, 'unknown'::text, 'cancelled'::text])))
);

--
-- Name: effects; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effects (
    effect_id uuid NOT NULL,
    action_intent_revision_id uuid NOT NULL,
    policy_decision_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    context_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    effect_kind text NOT NULL,
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    authorization_basis text NOT NULL,
    destination_kind text NOT NULL,
    destination_party_id uuid,
    registration_digest text NOT NULL,
    status text NOT NULL,
    verification_status text NOT NULL,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    cancelled_at timestamp(6) with time zone,
    trace_id text NOT NULL,
    current_attempt_id uuid,
    current_observation_id uuid,
    settled_at timestamp(6) with time zone,
    action_intent_id uuid NOT NULL,
    destination_binding_id uuid,
    CONSTRAINT effects_authorization_check CHECK ((authorization_basis = ANY (ARRAY['creator_grant'::text, 'runtime_builtin'::text, 'runtime_configuration'::text]))),
    CONSTRAINT effects_destination_check CHECK ((destination_kind = ANY (ARRAY['creator_inbox'::text, 'other_human_inbox'::text, 'codex_workspace'::text, 'external_group'::text, 'external_private'::text]))),
    CONSTRAINT effects_family_check CHECK ((((effect_kind = 'creator_response'::text) AND (capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (authorization_basis = 'creator_grant'::text) AND (destination_kind = ANY (ARRAY['creator_inbox'::text, 'external_private'::text])) AND (destination_party_id IS NOT NULL) AND (((destination_kind = 'creator_inbox'::text) AND (destination_binding_id IS NULL)) OR ((destination_kind = 'external_private'::text) AND (destination_binding_id IS NOT NULL))) AND (policy_decision_id IS NOT NULL)) OR ((effect_kind = 'local_inbox_delivery'::text) AND (capability_kind = 'local.other-human-inbox.deliver'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_builtin'::text) AND (destination_kind = 'other_human_inbox'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NULL) AND (policy_decision_id IS NULL)) OR ((effect_kind = 'external_group_delivery'::text) AND (capability_kind = 'external.group.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'social_group'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_configuration'::text) AND (destination_kind = 'external_group'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NOT NULL) AND (policy_decision_id IS NULL)) OR ((effect_kind = 'external_private_delivery'::text) AND (capability_kind = 'external.private.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_configuration'::text) AND (destination_kind = 'external_private'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NOT NULL) AND (policy_decision_id IS NULL)) OR ((effect_kind = 'codex_delegation'::text) AND (capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (authorization_basis = 'creator_grant'::text) AND (destination_kind = 'codex_workspace'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NULL) AND (policy_decision_id IS NOT NULL)))),
    CONSTRAINT effects_id_check CHECK ((uuid_extract_version(effect_id) = 7)),
    CONSTRAINT effects_lifecycle_check CHECK ((((status = 'registered'::text) AND (verification_status = 'not_started'::text) AND (current_attempt_id IS NULL) AND (current_observation_id IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = 'dispatching'::text) AND (verification_status = 'pending'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = ANY (ARRAY['completed'::text, 'failed'::text])) AND (verification_status = 'verified'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'unknown'::text) AND (verification_status = 'inconclusive'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'cancelled'::text) AND (verification_status = 'verified'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at = settled_at)))),
    CONSTRAINT effects_payload_bytes_check CHECK (((payload_bytes >= 1) AND (payload_bytes <= 65536))),
    CONSTRAINT effects_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effects_registration_digest_check CHECK ((registration_digest ~ '^sha256:[0-9a-f]{64}$'::text))
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
    status text DEFAULT 'active'::text NOT NULL,
    revoked_at timestamp(6) with time zone,
    workspace_scope text,
    artifact_scope text,
    network_access boolean,
    CONSTRAINT permission_grants_id_v7_chk CHECK (("substring"((grant_id)::text, 15, 1) = '7'::text)),
    CONSTRAINT permission_grants_revoked_chk CHECK ((((status = 'active'::text) AND (revoked_at IS NULL)) OR ((status = ANY (ARRAY['revoked'::text, 'expired'::text])) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT permission_grants_scope_chk CHECK ((((operation_class = 'send'::text) AND (audience_scope IS NOT NULL) AND (audience_scope = 'creator'::text) AND (data_scope IS NOT NULL) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (workspace_scope IS NULL) AND (artifact_scope IS NULL) AND (network_access IS NULL) AND (valid_until > valid_from) AND (valid_until <= (valid_from + '7 days'::interval)) AND ((max_uses >= 1) AND (max_uses <= 16)) AND ((consumed_uses >= 0) AND (consumed_uses <= max_uses)) AND (max_payload_bytes IS NOT NULL) AND ((max_payload_bytes >= 1) AND (max_payload_bytes <= 65536))) OR ((operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (workspace_scope IS NOT NULL) AND (workspace_scope = 'isolated_ephemeral'::text) AND (artifact_scope IS NOT NULL) AND (artifact_scope = 'explicit_only'::text) AND (network_access IS NOT NULL) AND (network_access = false) AND (valid_until > valid_from) AND (valid_until <= (valid_from + '01:00:00'::interval)) AND (max_uses = 1) AND ((consumed_uses >= 0) AND (consumed_uses <= 1)) AND (max_payload_bytes IS NULL)))),
    CONSTRAINT permission_grants_status_chk CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text, 'expired'::text])))
);

--
-- Name: policy_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.policy_decisions (
    policy_decision_id uuid NOT NULL,
    action_intent_revision_id uuid NOT NULL,
    matched_grant_id uuid,
    decision_outcome text NOT NULL,
    policy_identity text NOT NULL,
    reason_code text NOT NULL,
    supersedes_policy_decision_id uuid,
    is_current boolean DEFAULT true NOT NULL,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    valid_until timestamp(6) with time zone,
    CONSTRAINT policy_decisions_check CHECK (((decision_outcome = 'allowed'::text) = (matched_grant_id IS NOT NULL))),
    CONSTRAINT policy_decisions_check1 CHECK (((valid_until IS NULL) OR (valid_until > decided_at))),
    CONSTRAINT policy_decisions_check2 CHECK (((supersedes_policy_decision_id IS NULL) OR (supersedes_policy_decision_id <> policy_decision_id))),
    CONSTRAINT policy_decisions_decision_outcome_check CHECK ((decision_outcome = ANY (ARRAY['allowed'::text, 'denied'::text, 'confirmation_required'::text, 'unavailable'::text]))),
    CONSTRAINT policy_decisions_policy_decision_id_check CHECK ((uuid_extract_version(policy_decision_id) = 7)),
    CONSTRAINT policy_decisions_policy_identity_check CHECK ((policy_identity = 'armi.policy-engine.deterministic-v1'::text)),
    CONSTRAINT policy_decisions_reason_code_check CHECK ((reason_code ~ '^POLICY-[A-Z0-9-]+$'::text))
);
