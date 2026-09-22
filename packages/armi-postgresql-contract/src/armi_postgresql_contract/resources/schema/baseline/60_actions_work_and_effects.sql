-- Current ARMI schema tables owned by this baseline module.



-- Expression owns the complete outcome of one response-admission responsibility.


--
--



--
--



--
--



--

--
-- Name: durable_work; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.durable_work (
    work_id uuid NOT NULL,
    work_kind text NOT NULL,
    generation integer DEFAULT 1 NOT NULL,
    predecessor_work_id uuid,
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
    reconciliation_required boolean DEFAULT false NOT NULL,
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
    CONSTRAINT durable_work_generation_check CHECK ((generation >= 1)),
    CONSTRAINT durable_work_generation_predecessor_check CHECK ((((generation = 1) AND (predecessor_work_id IS NULL)) OR ((generation > 1) AND (predecessor_work_id IS NOT NULL)))),
    CONSTRAINT durable_work_predecessor_work_id_check CHECK (((predecessor_work_id IS NULL) OR (uuid_extract_version(predecessor_work_id) = 7))),
    CONSTRAINT durable_work_reconciliation_check CHECK ((NOT ((status = ANY (ARRAY['completed'::text, 'failed'::text, 'cancelled'::text])) AND reconciliation_required))),
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
    CONSTRAINT durable_work_work_kind_check CHECK ((work_kind = ANY (ARRAY['event.appraise'::text, 'cognition.context.prepare'::text, 'cognition.execute'::text, 'external.content.recognize'::text, 'external.content.finalize'::text, 'life.query.execute'::text, 'context.embedding.project'::text, 'artifact.object.delete'::text, 'live.vision.capture'::text, 'live.vision.observe'::text])))
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
    dispatch_runtime_instance_id uuid,
    dispatch_runtime_fence_token bigint,
    data_rights_contact_generation bigint,
    data_rights_use_generation bigint,
    CONSTRAINT effect_attempts_adapter_binding_check CHECK ((adapter_binding = ANY (ARRAY['armi.local-inbox-adapter.postgresql'::text, 'armi.external-message-adapter'::text, 'armi.effect-adapter.live-voice-audio'::text, 'armi.codex-runner.openai-python-sdk'::text]))),
    CONSTRAINT effect_attempts_attempt_no_check CHECK (((attempt_no >= 1) AND (attempt_no <= 2))),
    CONSTRAINT effect_attempts_check CHECK ((((dispatch_state = 'prepared'::text) AND (result_status IS NULL) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'dispatching'::text) AND (result_status IS NULL) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((dispatch_state = 'settled'::text) AND (result_status IS NOT NULL) AND (settled_at IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = ANY (ARRAY['failed'::text, 'cancelled'::text])) AND (dispatched_at IS NULL)))))),
    CONSTRAINT effect_attempts_check1 CHECK (((result_status = ANY (ARRAY['failed'::text, 'unknown'::text])) = (error_code IS NOT NULL))),
    CONSTRAINT effect_attempts_claim_token_check CHECK ((claim_token > 0)),
    CONSTRAINT effect_attempts_dispatch_fence_check CHECK (((dispatched_at IS NULL AND dispatch_runtime_instance_id IS NULL AND dispatch_runtime_fence_token IS NULL AND data_rights_contact_generation IS NULL AND data_rights_use_generation IS NULL) OR (dispatched_at IS NOT NULL AND dispatch_runtime_instance_id IS NOT NULL AND dispatch_runtime_fence_token > 0 AND data_rights_contact_generation > 0 AND data_rights_use_generation > 0))),
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
    conclusion text NOT NULL,
    reason_code text NOT NULL,
    evidence_kind text NOT NULL,
    evidence_ref text,
    evidence_digest text,
    source_identity text NOT NULL,
    receiver_ref uuid,
    observation_digest text NOT NULL,
    observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    receiver_external_ref text,
    CONSTRAINT effect_observations_check CHECK (((observation_kind = 'receipt'::text) = (receiver_ref IS NOT NULL))),
    CONSTRAINT effect_observations_check1 CHECK (((conclusion = 'unknown'::text) = (reliability = 'inconclusive'::text))),
    CONSTRAINT effect_observations_conclusion_check CHECK ((conclusion = ANY (ARRAY['completed'::text, 'failed'::text, 'unknown'::text, 'cancelled'::text]))),
    CONSTRAINT effect_observations_evidence_kind_check CHECK ((evidence_kind = ANY (ARRAY['adapter_receipt'::text, 'adapter_rejection'::text, 'adapter_ambiguous'::text, 'codex_verification'::text, 'owner_state'::text, 'local_delivery'::text, 'platform_receipt'::text, 'receiver_confirmation'::text, 'operator_attestation'::text, 'inconclusive'::text]))),
    CONSTRAINT effect_observations_evidence_digest_check CHECK (((evidence_digest IS NULL) OR (evidence_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT effect_observations_evidence_ref_check CHECK (((evidence_ref IS NULL) OR (evidence_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'::text))),
    CONSTRAINT effect_observations_reason_code_check CHECK ((reason_code ~ '^[A-Z][A-Z0-9-]{1,127}$'::text)),
    CONSTRAINT effect_observations_source_identity_check CHECK (((length(source_identity) >= 1) AND (length(source_identity) <= 256))),
    CONSTRAINT effect_observations_operator_check CHECK (((evidence_kind = 'operator_attestation'::text) = (reliability = 'operator_attested'::text))),
    CONSTRAINT effect_observations_effect_observation_id_check CHECK ((uuid_extract_version(effect_observation_id) = 7)),
    CONSTRAINT effect_observations_external_ref_check CHECK (((receiver_external_ref IS NULL) OR (receiver_external_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text))),
    CONSTRAINT effect_observations_external_ref_shape_check CHECK (((receiver_external_ref IS NULL) OR (observation_kind = 'receipt'::text))),
    CONSTRAINT effect_observations_observation_digest_check CHECK ((observation_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT effect_observations_observation_kind_check CHECK ((observation_kind = ANY (ARRAY['receipt'::text, 'query'::text, 'rejection'::text, 'ambiguous'::text, 'runner_verified'::text, 'runner_failed'::text, 'runner_unknown'::text, 'runner_cancelled'::text]))),
    CONSTRAINT effect_observations_receiver_ref_check CHECK (((receiver_ref IS NULL) OR (uuid_extract_version(receiver_ref) = 7))),
    CONSTRAINT effect_observations_reliability_check CHECK ((reliability = ANY (ARRAY['reliable'::text, 'operator_attested'::text, 'inconclusive'::text])))
);


--
-- Name: effects; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.effects (
    effect_id uuid NOT NULL,
    dispatch_status text DEFAULT 'ready'::text NOT NULL,
    available_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    claim_owner uuid,
    claim_expires_at timestamp(6) with time zone,
    claim_token bigint DEFAULT 0 NOT NULL,
    attempt_count smallint DEFAULT 0 NOT NULL,
    max_attempts smallint DEFAULT 2 NOT NULL,
    dispatch_deadline timestamp(6) with time zone,
    delivered_at timestamp(6) with time zone,
    last_error_code text,
    CONSTRAINT effects_dispatch_attempt_count_check CHECK (((attempt_count >= 0) AND (attempt_count <= 2))),
    CONSTRAINT effects_dispatch_check CHECK ((((dispatch_status = 'ready'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (delivered_at IS NULL)) OR ((dispatch_status = 'claimed'::text) AND (claim_owner IS NOT NULL) AND (claim_expires_at IS NOT NULL) AND (claim_token > 0) AND (delivered_at IS NULL)) OR ((dispatch_status = 'delivered'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (delivered_at IS NOT NULL)) OR ((dispatch_status = ANY (ARRAY['dead'::text, 'unknown'::text])) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (delivered_at IS NULL) AND (last_error_code IS NOT NULL)) OR ((dispatch_status = 'cancelled'::text) AND (claim_owner IS NULL) AND (claim_expires_at IS NULL) AND (delivered_at IS NULL)))),
    CONSTRAINT effects_dispatch_claim_token_check CHECK ((claim_token >= 0)),
    CONSTRAINT effects_dispatch_deadline_check CHECK ((dispatch_deadline IS NULL OR dispatch_deadline > available_at)),
    CONSTRAINT effects_dispatch_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^(EFFECT|CODEX)-[A-Z0-9-]+$'::text))),
    CONSTRAINT effects_dispatch_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 2))),
    CONSTRAINT effects_dispatch_status_check CHECK ((dispatch_status = ANY (ARRAY['ready'::text, 'claimed'::text, 'delivered'::text, 'dead'::text, 'unknown'::text, 'cancelled'::text]))),
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    context_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    effect_kind text NOT NULL,
    destination_kind text NOT NULL,
    destination_party_id uuid,
    status text NOT NULL,
    verification_status text NOT NULL,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    cancelled_at timestamp(6) with time zone,
    trace_id text NOT NULL,
    current_attempt_id uuid,
    current_observation_id uuid,
    settled_at timestamp(6) with time zone,
    action_intent_id uuid NOT NULL,
    root_opportunity_id uuid NOT NULL,
    operation_ref uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    subject_commit_id uuid NOT NULL,
    codex_task_source_id uuid,
    CONSTRAINT effects_intent_id_check CHECK (uuid_extract_version(action_intent_id) = 7),
    CONSTRAINT effects_operation_ref_check CHECK (uuid_extract_version(operation_ref) = 7),
    CONSTRAINT effects_codex_source_check CHECK ((effect_kind = 'codex_delegation') = (codex_task_source_id IS NOT NULL)),
    destination_binding_id uuid,
    live_voice_turn_id uuid,
    local_delivery_id uuid UNIQUE,
    local_receipt_digest text,
    local_delivered_at timestamp(6) with time zone,
    CONSTRAINT effects_local_delivery_check CHECK (
        (local_delivery_id IS NULL AND local_receipt_digest IS NULL AND local_delivered_at IS NULL)
        OR (local_delivery_id IS NOT NULL AND local_receipt_digest IS NOT NULL
            AND local_delivered_at IS NOT NULL
            AND destination_kind IN ('creator_inbox', 'other_human_inbox'))
    ),
    CONSTRAINT effects_local_delivery_id_check CHECK (uuid_extract_version(local_delivery_id) = 7),
    CONSTRAINT effects_local_receipt_digest_check CHECK (local_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT effects_destination_check CHECK ((destination_kind = ANY (ARRAY['creator_inbox'::text, 'other_human_inbox'::text, 'codex_workspace'::text, 'external_group'::text, 'external_private'::text, 'live_voice_audio'::text]))),
    CONSTRAINT effects_live_voice_shape_check CHECK (((destination_kind = 'live_voice_audio'::text) = (live_voice_turn_id IS NOT NULL))),
    -- Classification is derived from effect_kind; only the destination is stored.
    CONSTRAINT effects_family_check CHECK (
        destination_party_id IS NOT NULL AND (
            (effect_kind = 'creator_response' AND (
                (destination_kind IN ('creator_inbox', 'live_voice_audio') AND destination_binding_id IS NULL)
                OR (destination_kind = 'external_private' AND destination_binding_id IS NOT NULL)))
            OR (effect_kind = 'local_inbox_delivery' AND destination_kind = 'other_human_inbox' AND destination_binding_id IS NULL)
            OR (effect_kind = 'external_group_delivery' AND destination_kind = 'external_group' AND destination_binding_id IS NOT NULL)
            OR (effect_kind = 'external_private_delivery' AND destination_kind = 'external_private' AND destination_binding_id IS NOT NULL)
            OR (effect_kind = 'codex_delegation' AND destination_kind = 'codex_workspace' AND destination_binding_id IS NULL)
        )
    ),
    CONSTRAINT effects_id_check CHECK ((uuid_extract_version(effect_id) = 7)),
    CONSTRAINT effects_lifecycle_check CHECK ((((status = 'registered'::text) AND (verification_status = 'not_started'::text) AND (current_attempt_id IS NULL) AND (current_observation_id IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = 'dispatching'::text) AND (verification_status = 'pending'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NULL) AND (settled_at IS NULL) AND (cancelled_at IS NULL)) OR ((status = ANY (ARRAY['completed'::text, 'failed'::text])) AND (verification_status = ANY (ARRAY['verified'::text, 'operator_attested'::text])) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'unknown'::text) AND (verification_status = 'inconclusive'::text) AND (current_attempt_id IS NOT NULL) AND (current_observation_id IS NOT NULL) AND (settled_at IS NOT NULL) AND (cancelled_at IS NULL)) OR ((status = 'cancelled'::text) AND (verification_status = 'verified'::text) AND (settled_at IS NOT NULL) AND (cancelled_at = settled_at)))),
    CONSTRAINT effects_payload_bytes_check CHECK (((payload_bytes >= 1) AND (payload_bytes <= 65536))),
    CONSTRAINT effects_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text))
);

--
--



--
--
