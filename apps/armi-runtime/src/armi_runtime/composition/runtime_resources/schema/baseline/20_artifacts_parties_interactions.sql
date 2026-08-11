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
    CONSTRAINT artifacts_retention_status_check CHECK ((retention_status = ANY (ARRAY['retained'::text, 'deleted'::text])))
);

--
-- Name: external_channel_bindings; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.external_channel_bindings (
    external_binding_id uuid NOT NULL,
    channel_kind text NOT NULL,
    account_key text NOT NULL,
    external_kind text NOT NULL,
    external_key text NOT NULL,
    party_id uuid NOT NULL,
    party_kind text NOT NULL,
    scene_id uuid,
    display_label text NOT NULL,
    identity_assurance text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    first_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    last_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT external_channel_bindings_account_check CHECK ((account_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT external_channel_bindings_assurance_check CHECK ((identity_assurance = ANY (ARRAY['platform_observed'::text, 'runtime_configuration'::text]))),
    CONSTRAINT external_channel_bindings_channel_check CHECK ((channel_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT external_channel_bindings_external_key_check CHECK ((external_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT external_channel_bindings_id_check CHECK ((uuid_extract_version(external_binding_id) = 7)),
    CONSTRAINT external_channel_bindings_kind_check CHECK ((external_kind = ANY (ARRAY['person'::text, 'group'::text]))),
    CONSTRAINT external_channel_bindings_label_check CHECK (((length(btrim(display_label)) >= 1) AND (length(btrim(display_label)) <= 256))),
    CONSTRAINT external_channel_bindings_shape_check CHECK ((((external_kind = 'person'::text) AND (party_kind = 'creator'::text) AND (scene_id IS NOT NULL) AND (identity_assurance = 'runtime_configuration'::text)) OR ((external_kind = 'person'::text) AND (party_kind = 'other_human'::text) AND (identity_assurance = 'platform_observed'::text)) OR ((external_kind = 'group'::text) AND (party_kind = 'social_group'::text) AND (scene_id IS NOT NULL) AND (identity_assurance = 'platform_observed'::text)))),
    CONSTRAINT external_channel_bindings_status_check CHECK ((status = 'active'::text)),
    CONSTRAINT external_channel_bindings_time_check CHECK ((last_observed_at >= first_observed_at))
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
    primary_party_kind text DEFAULT 'creator'::text NOT NULL,
    scene_version bigint DEFAULT 1 NOT NULL,
    CONSTRAINT interaction_scenes_audience_scope_check CHECK ((audience_scope = ANY (ARRAY['creator'::text, 'other_human'::text, 'social_group'::text]))),
    CONSTRAINT interaction_scenes_check CHECK ((((current_status = 'open'::text) AND (closed_at IS NULL)) OR ((current_status = 'closed'::text) AND (closed_at IS NOT NULL) AND (closed_at >= opened_at)))),
    CONSTRAINT interaction_scenes_current_status_check CHECK ((current_status = ANY (ARRAY['open'::text, 'closed'::text]))),
    CONSTRAINT interaction_scenes_recent_context_boundary_check CHECK (((recent_context_boundary IS NULL) OR (uuid_extract_version(recent_context_boundary) = 7))),
    CONSTRAINT interaction_scenes_role_shape_check CHECK ((((scene_kind = 'creator_dialogue'::text) AND (audience_scope = 'creator'::text) AND (primary_party_kind = 'creator'::text)) OR ((scene_kind = 'other_human_dialogue'::text) AND (audience_scope = 'other_human'::text) AND (primary_party_kind = 'other_human'::text)) OR ((scene_kind = 'group_dialogue'::text) AND (audience_scope = 'social_group'::text) AND (primary_party_kind = 'social_group'::text)))),
    CONSTRAINT interaction_scenes_scene_id_check CHECK ((uuid_extract_version(scene_id) = 7)),
    CONSTRAINT interaction_scenes_scene_key_check CHECK ((scene_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT interaction_scenes_scene_kind_check CHECK ((scene_kind = ANY (ARRAY['creator_dialogue'::text, 'other_human_dialogue'::text, 'group_dialogue'::text]))),
    CONSTRAINT interaction_scenes_scene_version_check CHECK ((scene_version > 0))
);

--
-- Name: local_inbox_deliveries; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.local_inbox_deliveries (
    delivery_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    destination_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer NOT NULL,
    receipt_digest text NOT NULL,
    delivered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT local_inbox_deliveries_id_check CHECK ((uuid_extract_version(delivery_id) = 7)),
    CONSTRAINT local_inbox_deliveries_payload_bytes_check CHECK (((payload_bytes IS NULL) OR ((payload_bytes >= 1) AND (payload_bytes <= 65536)))),
    CONSTRAINT local_inbox_deliveries_payload_digest_check CHECK ((payload_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT local_inbox_deliveries_receipt_digest_check CHECK ((receipt_digest ~ '^sha256:[0-9a-f]{64}$'::text))
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
    CONSTRAINT parties_display_label_check CHECK ((((party_kind = ANY (ARRAY['subject'::text, 'creator'::text])) AND (display_label IS NULL)) OR ((party_kind = ANY (ARRAY['other_human'::text, 'social_group'::text])) AND ((length(btrim(display_label)) >= 1) AND (length(btrim(display_label)) <= 256))))),
    CONSTRAINT parties_party_id_check CHECK ((uuid_extract_version(party_id) = 7)),
    CONSTRAINT parties_party_kind_check CHECK ((party_kind = ANY (ARRAY['subject'::text, 'creator'::text, 'other_human'::text, 'social_group'::text]))),
    CONSTRAINT parties_role_shape_check CHECK ((((party_kind = 'subject'::text) AND (represented_subject_id IS NOT NULL) AND (creator_role IS NULL) AND (declared_identity_key IS NULL)) OR ((party_kind = 'creator'::text) AND (represented_subject_id IS NULL) AND (creator_role = 'unique_primary_creator'::text) AND (declared_identity_key IS NULL)) OR ((party_kind = ANY (ARRAY['other_human'::text, 'social_group'::text])) AND (represented_subject_id IS NULL) AND (creator_role IS NULL) AND (declared_identity_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)))),
    CONSTRAINT parties_status_check CHECK ((status = 'active'::text))
);

--
-- Name: party_input_interactions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.party_input_interactions (
    interaction_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    source_party_id uuid NOT NULL,
    purpose text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    content_digest text NOT NULL,
    trace_id text NOT NULL,
    received_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    external_binding_id uuid,
    external_message_key text,
    addressed_to_subject boolean,
    CONSTRAINT party_input_interactions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT party_input_interactions_external_message_key_check CHECK (((external_message_key IS NULL) OR (external_message_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text))),
    CONSTRAINT party_input_interactions_external_shape_check CHECK ((((external_binding_id IS NULL) AND (external_message_key IS NULL) AND (addressed_to_subject IS NULL)) OR ((purpose = ANY (ARRAY['creator_message'::text, 'other_human_message'::text])) AND (external_binding_id IS NOT NULL) AND (external_message_key IS NOT NULL) AND (addressed_to_subject IS NOT NULL)))),
    CONSTRAINT party_input_interactions_id_check CHECK ((uuid_extract_version(interaction_id) = 7)),
    CONSTRAINT party_input_interactions_idempotency_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT party_input_interactions_purpose_check CHECK ((purpose = ANY (ARRAY['creator_message'::text, 'other_human_message'::text, 'codex_task_request'::text]))),
    CONSTRAINT party_input_interactions_request_digest_check CHECK ((request_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT party_input_interactions_trace_id_check CHECK ((trace_id ~ '^[0-9a-f]{32}$'::text))
);

--
-- Name: scene_participants; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.scene_participants (
    scene_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    party_id uuid NOT NULL,
    participant_role text NOT NULL,
    first_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    last_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT scene_participants_role_check CHECK ((participant_role = ANY (ARRAY['primary'::text, 'member'::text]))),
    CONSTRAINT scene_participants_time_check CHECK ((last_observed_at >= first_observed_at))
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
    CONSTRAINT scene_timeline_items_result_status_check CHECK ((result_status = ANY (ARRAY['accepted'::text, 'applied'::text, 'waiting'::text, 'rejected'::text, 'unavailable'::text, 'failed'::text, 'unknown'::text, 'completed'::text]))),
    CONSTRAINT scene_timeline_items_source_event_no_check CHECK ((source_event_no > 0)),
    CONSTRAINT scene_timeline_items_source_kind_check CHECK ((source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text)),
    CONSTRAINT scene_timeline_items_source_ref_check CHECK ((uuid_extract_version(source_ref) = 7)),
    CONSTRAINT scene_timeline_items_timeline_item_id_check CHECK ((uuid_extract_version(timeline_item_id) = 7))
);
