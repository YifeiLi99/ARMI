-- Current ARMI schema tables owned by this baseline module.

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
-- Name: external_content_recognition_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.external_content_recognition_attempts (
    recognition_attempt_id uuid CONSTRAINT external_content_recognition_at_recognition_attempt_id_not_null NOT NULL,
    external_message_part_id uuid CONSTRAINT external_content_recognition__external_message_part_id_not_null NOT NULL,
    work_id uuid NOT NULL,
    work_attempt_id uuid NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    request_artifact_id uuid CONSTRAINT external_content_recognition_attem_request_artifact_id_not_null NOT NULL,
    dispatch_status text NOT NULL,
    provider_request_id text,
    provider_model_id text,
    response_artifact_id uuid,
    input_tokens integer,
    output_tokens integer,
    estimated_cost_microyuan bigint,
    result_status text,
    error_code text,
    dispatched_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    settled_at timestamp(6) with time zone,
    CONSTRAINT external_content_recognition_attempts_dispatch_check CHECK ((dispatch_status = ANY (ARRAY['dispatched'::text, 'settled'::text]))),
    CONSTRAINT external_content_recognition_attempts_id_check CHECK ((uuid_extract_version(recognition_attempt_id) = 7)),
    CONSTRAINT external_content_recognition_attempts_result_check CHECK (((result_status IS NULL) OR (result_status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'unknown'::text])))),
    CONSTRAINT external_content_recognition_attempts_settlement_check CHECK ((((dispatch_status = 'dispatched'::text) AND (result_status IS NULL) AND (settled_at IS NULL) AND (response_artifact_id IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'settled'::text) AND (result_status IS NOT NULL) AND (settled_at IS NOT NULL) AND (((result_status = 'succeeded'::text) AND (response_artifact_id IS NOT NULL) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (error_code IS NOT NULL)))))),
    CONSTRAINT external_content_recognition_attempts_usage_check CHECK ((((input_tokens IS NULL) OR (input_tokens >= 0)) AND ((output_tokens IS NULL) OR (output_tokens >= 0)) AND ((estimated_cost_microyuan IS NULL) OR (estimated_cost_microyuan >= 0))))
);

--
-- Name: external_message_parts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.external_message_parts (
    external_message_part_id uuid NOT NULL,
    interaction_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    part_kind text NOT NULL,
    text_value text,
    target_key text,
    external_locator text,
    declared_file_name text,
    declared_media_type text,
    declared_byte_size bigint,
    processing_status text NOT NULL,
    raw_artifact_id uuid,
    interpretation_artifact_id uuid,
    interpretation_text text,
    failure_code text,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    settled_at timestamp(6) with time zone,
    visual_role text,
    source_kind text,
    source_summary text,
    detected_media_type text,
    pixel_width integer,
    pixel_height integer,
    frame_count integer,
    CONSTRAINT external_message_parts_detected_media_type_check CHECK (((detected_media_type IS NULL) OR (detected_media_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$'::text))),
    CONSTRAINT external_message_parts_id_check CHECK ((uuid_extract_version(external_message_part_id) = 7)),
    CONSTRAINT external_message_parts_kind_check CHECK ((part_kind = ANY (ARRAY['text'::text, 'mention'::text, 'reply'::text, 'face'::text, 'image'::text, 'audio'::text, 'video'::text, 'file'::text, 'unknown'::text]))),
    CONSTRAINT external_message_parts_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 64))),
    CONSTRAINT external_message_parts_settlement_check CHECK ((((processing_status = 'pending'::text) AND (settled_at IS NULL) AND (interpretation_artifact_id IS NULL) AND (interpretation_text IS NULL) AND (failure_code IS NULL)) OR ((processing_status = 'not_required'::text) AND (settled_at IS NULL) AND (raw_artifact_id IS NULL) AND (interpretation_artifact_id IS NULL) AND (interpretation_text IS NULL) AND (failure_code IS NULL)) OR ((processing_status = 'skipped'::text) AND (settled_at IS NOT NULL) AND (raw_artifact_id IS NULL) AND (interpretation_artifact_id IS NULL) AND (interpretation_text IS NULL) AND (failure_code IS NULL)) OR ((processing_status = 'succeeded'::text) AND (settled_at IS NOT NULL) AND (interpretation_artifact_id IS NOT NULL) AND (interpretation_text IS NOT NULL) AND (failure_code IS NULL)) OR ((processing_status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (settled_at IS NOT NULL) AND (interpretation_artifact_id IS NULL) AND (interpretation_text IS NULL) AND (failure_code IS NOT NULL)))),
    CONSTRAINT external_message_parts_shape_check CHECK ((((part_kind = ANY (ARRAY['text'::text, 'face'::text, 'unknown'::text])) AND (text_value IS NOT NULL) AND (target_key IS NULL) AND (external_locator IS NULL)) OR ((part_kind = ANY (ARRAY['mention'::text, 'reply'::text])) AND (text_value IS NULL) AND (target_key IS NOT NULL) AND (external_locator IS NULL)) OR ((part_kind = ANY (ARRAY['image'::text, 'audio'::text, 'video'::text, 'file'::text])) AND (text_value IS NULL) AND (target_key IS NULL) AND (external_locator IS NOT NULL)))),
    CONSTRAINT external_message_parts_size_check CHECK (((declared_byte_size IS NULL) OR (declared_byte_size >= 0))),
    CONSTRAINT external_message_parts_source_kind_check CHECK (((source_kind IS NULL) OR (source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'::text))),
    CONSTRAINT external_message_parts_source_summary_check CHECK (((source_summary IS NULL) OR ((octet_length(source_summary) >= 1) AND (octet_length(source_summary) <= 512)))),
    CONSTRAINT external_message_parts_status_check CHECK ((processing_status = ANY (ARRAY['not_required'::text, 'pending'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text, 'skipped'::text]))),
    CONSTRAINT external_message_parts_visual_role_check CHECK (((visual_role IS NULL) OR (visual_role = ANY (ARRAY['ordinary'::text, 'sticker'::text, 'sticker_candidate'::text, 'platform_special'::text, 'unknown'::text])))),
    CONSTRAINT external_message_parts_visual_shape_check CHECK ((((part_kind <> 'image'::text) AND (visual_role IS NULL) AND (source_kind IS NULL) AND (source_summary IS NULL) AND (detected_media_type IS NULL) AND (pixel_width IS NULL) AND (pixel_height IS NULL) AND (frame_count IS NULL)) OR ((part_kind = 'image'::text) AND (((visual_role IS NULL) AND (source_kind IS NULL) AND (source_summary IS NULL)) OR ((visual_role IS NOT NULL) AND (source_kind IS NOT NULL))) AND (((detected_media_type IS NULL) AND (pixel_width IS NULL) AND (pixel_height IS NULL) AND (frame_count IS NULL)) OR ((detected_media_type IS NOT NULL) AND (pixel_width > 0) AND (pixel_height > 0) AND (frame_count > 0) AND (((pixel_width)::bigint * (pixel_height)::bigint) <= 36000000))))))
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
-- Name: live_vision_observation_frames; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_vision_observation_frames (
    observation_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    artifact_id uuid,
    content_digest text NOT NULL,
    byte_size bigint NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    captured_at timestamp(6) with time zone NOT NULL,
    purge_after timestamp(6) with time zone NOT NULL,
    purged_at timestamp(6) with time zone,
    CONSTRAINT live_vision_observation_frames_byte_size_check CHECK ((byte_size > 0)),
    CONSTRAINT live_vision_observation_frames_check CHECK ((purge_after > captured_at)),
    CONSTRAINT live_vision_observation_frames_check1 CHECK (((artifact_id IS NULL) = (purged_at IS NOT NULL))),
    CONSTRAINT live_vision_observation_frames_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT live_vision_observation_frames_height_check CHECK ((height > 0)),
    CONSTRAINT live_vision_observation_frames_ordinal_check CHECK (((ordinal >= 1) AND (ordinal <= 4))),
    CONSTRAINT live_vision_observation_frames_width_check CHECK ((width > 0))
);

--
-- Name: live_vision_observations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_vision_observations (
    observation_id uuid NOT NULL,
    session_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    observation_no bigint NOT NULL,
    trigger_kind text NOT NULL,
    status text NOT NULL,
    change_score double precision,
    change_class text,
    scene_summary text,
    visible_change text,
    uncertainty text,
    provider text,
    model_id text,
    input_tokens integer,
    output_tokens integer,
    evidence_id uuid,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    settled_at timestamp(6) with time zone,
    error_code text,
    CONSTRAINT live_vision_observations_change_class_check CHECK ((change_class = ANY (ARRAY['none'::text, 'minor'::text, 'notable'::text, 'uncertain'::text]))),
    CONSTRAINT live_vision_observations_change_score_check CHECK (((change_score >= (0)::double precision) AND (change_score <= (1)::double precision))),
    CONSTRAINT live_vision_observations_check CHECK ((((status = ANY (ARRAY['registered'::text, 'recognizing'::text])) AND (settled_at IS NULL)) OR ((status = 'completed'::text) AND (settled_at IS NOT NULL) AND (scene_summary IS NOT NULL) AND (visible_change IS NOT NULL) AND (change_class IS NOT NULL) AND (error_code IS NULL)) OR ((status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (settled_at IS NOT NULL) AND (error_code IS NOT NULL)))),
    CONSTRAINT live_vision_observations_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^VISION-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_vision_observations_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens >= 0))),
    CONSTRAINT live_vision_observations_observation_id_check CHECK ((uuid_extract_version(observation_id) = 7)),
    CONSTRAINT live_vision_observations_observation_no_check CHECK ((observation_no > 0)),
    CONSTRAINT live_vision_observations_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens >= 0))),
    CONSTRAINT live_vision_observations_scene_summary_check CHECK (((scene_summary IS NULL) OR ((length(scene_summary) >= 1) AND (length(scene_summary) <= 2048)))),
    CONSTRAINT live_vision_observations_status_check CHECK ((status = ANY (ARRAY['registered'::text, 'recognizing'::text, 'completed'::text, 'failed'::text, 'unknown'::text]))),
    CONSTRAINT live_vision_observations_trigger_kind_check CHECK ((trigger_kind = ANY (ARRAY['initial'::text, 'scene_change'::text, 'periodic_refresh'::text, 'manual'::text]))),
    CONSTRAINT live_vision_observations_uncertainty_check CHECK (((uncertainty IS NULL) OR ((length(uncertainty) >= 1) AND (length(uncertainty) <= 1024)))),
    CONSTRAINT live_vision_observations_visible_change_check CHECK (((visible_change IS NULL) OR ((length(visible_change) >= 1) AND (length(visible_change) <= 2048))))
);

--
-- Name: live_vision_sessions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_vision_sessions (
    session_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    state text NOT NULL,
    device_name text NOT NULL,
    device_path text NOT NULL,
    usb_location_id text NOT NULL,
    backend text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    fps integer NOT NULL,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    ended_at timestamp(6) with time zone,
    error_code text,
    CONSTRAINT live_vision_sessions_backend_check CHECK ((backend = 'DSHOW'::text)),
    CONSTRAINT live_vision_sessions_check CHECK (((state = ANY (ARRAY['stopped'::text, 'failed'::text])) = (ended_at IS NOT NULL))),
    CONSTRAINT live_vision_sessions_device_name_check CHECK (((length(btrim(device_name)) >= 1) AND (length(btrim(device_name)) <= 512))),
    CONSTRAINT live_vision_sessions_device_path_check CHECK (((length(btrim(device_path)) >= 1) AND (length(btrim(device_path)) <= 1024))),
    CONSTRAINT live_vision_sessions_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^VISION-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_vision_sessions_fps_check CHECK ((fps = 5)),
    CONSTRAINT live_vision_sessions_height_check CHECK ((height = 720)),
    CONSTRAINT live_vision_sessions_session_id_check CHECK ((uuid_extract_version(session_id) = 7)),
    CONSTRAINT live_vision_sessions_state_check CHECK ((state = ANY (ARRAY['starting'::text, 'observing'::text, 'degraded'::text, 'unavailable'::text, 'stopping'::text, 'stopped'::text, 'failed'::text]))),
    CONSTRAINT live_vision_sessions_usb_location_id_check CHECK (((length(btrim(usb_location_id)) >= 1) AND (length(btrim(usb_location_id)) <= 512))),
    CONSTRAINT live_vision_sessions_width_check CHECK ((width = 1280))
);

--
-- Name: live_voice_playback_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_voice_playback_attempts (
    playback_attempt_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    destination_kind text DEFAULT 'local_audio'::text NOT NULL,
    attempt_no smallint DEFAULT 1 NOT NULL,
    result_status text NOT NULL,
    frames_written bigint DEFAULT 0 NOT NULL,
    error_code text,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    first_frame_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT live_voice_playback_attempt_check CHECK ((attempt_no = 1)),
    CONSTRAINT live_voice_playback_destination_check CHECK ((destination_kind = 'local_audio'::text)),
    CONSTRAINT live_voice_playback_error_check CHECK (((error_code IS NULL) OR (error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_voice_playback_frames_check CHECK ((frames_written >= 0)),
    CONSTRAINT live_voice_playback_id_check CHECK ((uuid_extract_version(playback_attempt_id) = 7)),
    CONSTRAINT live_voice_playback_result_check CHECK ((((result_status = 'registered'::text) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((result_status = 'completed'::text) AND (settled_at IS NOT NULL) AND (frames_written > 0) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'partial'::text, 'unknown'::text])) AND (settled_at IS NOT NULL) AND (error_code IS NOT NULL)))),
    CONSTRAINT live_voice_playback_status_check CHECK ((result_status = ANY (ARRAY['registered'::text, 'completed'::text, 'failed'::text, 'partial'::text, 'unknown'::text])))
);

--
-- Name: live_voice_provider_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_voice_provider_attempts (
    provider_attempt_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    service_kind text NOT NULL,
    provider text NOT NULL,
    resource_id text NOT NULL,
    model_identity text,
    attempt_no smallint DEFAULT 1 NOT NULL,
    result_status text NOT NULL,
    error_code text,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    first_result_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT live_voice_attempts_binding_check CHECK ((((length(btrim(provider)) >= 1) AND (length(btrim(provider)) <= 64)) AND ((length(btrim(resource_id)) >= 1) AND (length(btrim(resource_id)) <= 128)))),
    CONSTRAINT live_voice_attempts_error_check CHECK (((error_code IS NULL) OR (error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_voice_attempts_id_check CHECK ((uuid_extract_version(provider_attempt_id) = 7)),
    CONSTRAINT live_voice_attempts_number_check CHECK ((attempt_no = 1)),
    CONSTRAINT live_voice_attempts_result_check CHECK ((((result_status = 'started'::text) AND (settled_at IS NULL) AND (error_code IS NULL)) OR ((result_status = 'completed'::text) AND (settled_at IS NOT NULL) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'partial'::text, 'unknown'::text])) AND (settled_at IS NOT NULL) AND (error_code IS NOT NULL)))),
    CONSTRAINT live_voice_attempts_service_check CHECK ((service_kind = ANY (ARRAY['asr'::text, 'llm'::text, 'tts'::text]))),
    CONSTRAINT live_voice_attempts_status_check CHECK ((result_status = ANY (ARRAY['started'::text, 'completed'::text, 'failed'::text, 'partial'::text, 'unknown'::text])))
);

--
-- Name: live_voice_sessions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_voice_sessions (
    session_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    state text NOT NULL,
    context_version text,
    input_host_api text NOT NULL,
    input_device_name text NOT NULL,
    output_host_api text NOT NULL,
    output_device_name text NOT NULL,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    ended_at timestamp(6) with time zone,
    error_code text,
    CONSTRAINT live_voice_sessions_context_check CHECK (((context_version IS NULL) OR ((length(context_version) >= 1) AND (length(context_version) <= 128)))),
    CONSTRAINT live_voice_sessions_device_check CHECK ((((length(btrim(input_host_api)) >= 1) AND (length(btrim(input_host_api)) <= 128)) AND ((length(btrim(input_device_name)) >= 1) AND (length(btrim(input_device_name)) <= 512)) AND ((length(btrim(output_host_api)) >= 1) AND (length(btrim(output_host_api)) <= 128)) AND ((length(btrim(output_device_name)) >= 1) AND (length(btrim(output_device_name)) <= 512)))),
    CONSTRAINT live_voice_sessions_error_check CHECK (((error_code IS NULL) OR (error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_voice_sessions_id_check CHECK ((uuid_extract_version(session_id) = 7)),
    CONSTRAINT live_voice_sessions_lifecycle_check CHECK (((state = ANY (ARRAY['stopped'::text, 'failed'::text, 'unavailable'::text])) = (ended_at IS NOT NULL))),
    CONSTRAINT live_voice_sessions_state_check CHECK ((state = ANY (ARRAY['starting'::text, 'listening'::text, 'recognizing'::text, 'thinking'::text, 'speaking'::text, 'waiting_slow'::text, 'stopped'::text, 'failed'::text, 'unavailable'::text])))
);

--
-- Name: live_voice_text_fragments; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_voice_text_fragments (
    fragment_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    fragment_no smallint NOT NULL,
    body text NOT NULL,
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT live_voice_fragments_body_check CHECK (((length(btrim(body)) >= 1) AND (length(btrim(body)) <= 160))),
    CONSTRAINT live_voice_fragments_id_check CHECK ((uuid_extract_version(fragment_id) = 7)),
    CONSTRAINT live_voice_fragments_number_check CHECK (((fragment_no >= 1) AND (fragment_no <= 64)))
);

--
-- Name: live_voice_turns; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.live_voice_turns (
    turn_id uuid NOT NULL,
    session_id uuid NOT NULL,
    turn_no bigint NOT NULL,
    interaction_id uuid,
    final_transcript text,
    decision_kind text,
    spoken_text text DEFAULT ''::text NOT NULL,
    model_identity text,
    context_version text,
    result_status text DEFAULT 'recognizing'::text NOT NULL,
    error_code text,
    speech_ended_at timestamp(6) with time zone,
    first_audio_at timestamp(6) with time zone,
    completed_at timestamp(6) with time zone,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT live_voice_turns_decision_check CHECK (((decision_kind IS NULL) OR (decision_kind = ANY (ARRAY['speak'::text, 'wait'::text, 'silent'::text])))),
    CONSTRAINT live_voice_turns_error_check CHECK (((error_code IS NULL) OR (error_code ~ '^VOICE-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT live_voice_turns_first_audio_check CHECK (((first_audio_at IS NULL) OR (speech_ended_at IS NULL) OR (first_audio_at >= speech_ended_at))),
    CONSTRAINT live_voice_turns_id_check CHECK ((uuid_extract_version(turn_id) = 7)),
    CONSTRAINT live_voice_turns_number_check CHECK ((turn_no > 0)),
    CONSTRAINT live_voice_turns_spoken_check CHECK ((length(spoken_text) <= 4096)),
    CONSTRAINT live_voice_turns_status_check CHECK ((result_status = ANY (ARRAY['recognizing'::text, 'thinking'::text, 'speaking'::text, 'waiting_slow'::text, 'completed'::text, 'failed'::text, 'partial'::text, 'unknown'::text, 'silent'::text]))),
    CONSTRAINT live_voice_turns_transcript_check CHECK (((final_transcript IS NULL) OR ((length(btrim(final_transcript)) >= 1) AND (length(btrim(final_transcript)) <= 4096))))
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
    cognition_content_digest text,
    recognition_status text DEFAULT 'not_required'::text NOT NULL,
    modality text DEFAULT 'text'::text NOT NULL,
    CONSTRAINT party_input_interactions_cognition_digest_check CHECK (((cognition_content_digest IS NULL) OR (cognition_content_digest ~ '^sha256:[0-9a-f]{64}$'::text))),
    CONSTRAINT party_input_interactions_content_digest_check CHECK ((content_digest ~ '^sha256:[0-9a-f]{64}$'::text)),
    CONSTRAINT party_input_interactions_external_message_key_check CHECK (((external_message_key IS NULL) OR (external_message_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text))),
    CONSTRAINT party_input_interactions_external_shape_check CHECK ((((external_binding_id IS NULL) AND (external_message_key IS NULL) AND (addressed_to_subject IS NULL)) OR ((purpose = ANY (ARRAY['creator_message'::text, 'other_human_message'::text])) AND (external_binding_id IS NOT NULL) AND (external_message_key IS NOT NULL) AND (addressed_to_subject IS NOT NULL)))),
    CONSTRAINT party_input_interactions_id_check CHECK ((uuid_extract_version(interaction_id) = 7)),
    CONSTRAINT party_input_interactions_idempotency_check CHECK ((idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'::text)),
    CONSTRAINT party_input_interactions_modality_check CHECK ((modality = ANY (ARRAY['text'::text, 'media_file'::text, 'live_voice'::text]))),
    CONSTRAINT party_input_interactions_purpose_check CHECK ((purpose = ANY (ARRAY['creator_message'::text, 'other_human_message'::text, 'codex_task_request'::text]))),
    CONSTRAINT party_input_interactions_recognition_status_check CHECK ((recognition_status = ANY (ARRAY['not_required'::text, 'pending'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text, 'skipped'::text]))),
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

--
-- Name: visual_recognition_attempts; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.visual_recognition_attempts (
    visual_attempt_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    attempt_no smallint DEFAULT 1 NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    request_artifact_id uuid NOT NULL,
    response_artifact_id uuid,
    provider_request_id text,
    status text NOT NULL,
    input_tokens integer,
    output_tokens integer,
    error_code text,
    prepared_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    dispatched_at timestamp(6) with time zone,
    settled_at timestamp(6) with time zone,
    CONSTRAINT visual_recognition_attempts_attempt_no_check CHECK ((attempt_no = 1)),
    CONSTRAINT visual_recognition_attempts_check CHECK ((((status = 'prepared'::text) AND (dispatched_at IS NULL) AND (settled_at IS NULL)) OR ((status = 'dispatched'::text) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL)) OR ((status = 'succeeded'::text) AND (dispatched_at IS NOT NULL) AND (settled_at IS NOT NULL) AND (response_artifact_id IS NOT NULL) AND (error_code IS NULL)) OR ((status = ANY (ARRAY['failed'::text, 'unknown'::text])) AND (settled_at IS NOT NULL) AND (error_code IS NOT NULL)))),
    CONSTRAINT visual_recognition_attempts_error_code_check CHECK (((error_code IS NULL) OR (error_code ~ '^VISION-[A-Z0-9-]{1,120}$'::text))),
    CONSTRAINT visual_recognition_attempts_input_tokens_check CHECK (((input_tokens IS NULL) OR (input_tokens >= 0))),
    CONSTRAINT visual_recognition_attempts_output_tokens_check CHECK (((output_tokens IS NULL) OR (output_tokens >= 0))),
    CONSTRAINT visual_recognition_attempts_status_check CHECK ((status = ANY (ARRAY['prepared'::text, 'dispatched'::text, 'succeeded'::text, 'failed'::text, 'unknown'::text]))),
    CONSTRAINT visual_recognition_attempts_visual_attempt_id_check CHECK ((uuid_extract_version(visual_attempt_id) = 7))
);
