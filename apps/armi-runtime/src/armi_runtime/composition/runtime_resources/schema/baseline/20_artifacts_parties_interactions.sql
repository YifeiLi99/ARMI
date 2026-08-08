-- Frozen ARMI v1 artifacts, parties, and interactions.

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
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT party_input_interactions_id_check CHECK (uuid_extract_version(interaction_id) = 7),
    CONSTRAINT party_input_interactions_purpose_check CHECK (purpose IN ('creator_message', 'other_human_message', 'codex_task_request')),
    CONSTRAINT party_input_interactions_idempotency_check CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT party_input_interactions_request_digest_check CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT party_input_interactions_content_digest_check CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT party_input_interactions_trace_id_check CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    CONSTRAINT party_input_interactions_schema_version_check CHECK (schema_version = 1)
);


CREATE TABLE armi.local_inbox_deliveries (
    delivery_id uuid NOT NULL,
    effect_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    destination_party_id uuid NOT NULL,
    payload_artifact_id uuid NOT NULL,
    payload_digest text NOT NULL,
    payload_bytes integer,
    receipt_digest text NOT NULL,
    delivered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    schema_version smallint DEFAULT 1 NOT NULL,
    CONSTRAINT local_inbox_deliveries_id_check CHECK (uuid_extract_version(delivery_id) = 7),
    CONSTRAINT local_inbox_deliveries_payload_digest_check CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT local_inbox_deliveries_payload_bytes_check CHECK (payload_bytes IS NULL OR payload_bytes BETWEEN 1 AND 65536),
    CONSTRAINT local_inbox_deliveries_receipt_digest_check CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT local_inbox_deliveries_schema_version_check CHECK (schema_version = 1)
);


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
