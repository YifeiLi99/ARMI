-- Current ARMI schema tables owned by this baseline module.

--
-- Name: activity_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activity_revisions (
    subject_id uuid NOT NULL,
    activity_kind text DEFAULT 'self_directed' NOT NULL,
    origin_opportunity_id uuid,
    origin_admin_change_id uuid,
    activity_created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    privacy_scope text DEFAULT 'private' NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    root_activity_id uuid GENERATED ALWAYS AS (CASE WHEN revision_no=1 THEN activity_id END) STORED UNIQUE,
    CONSTRAINT activity_revisions_root_subject_key UNIQUE (root_activity_id, subject_id),
    CONSTRAINT activity_revisions_stable_identity_key UNIQUE (activity_id, activity_revision_id, subject_id, activity_created_at),
    CONSTRAINT activity_revisions_identity_check CHECK (uuid_extract_version(activity_id)=7),
    CONSTRAINT activity_revisions_activity_kind_check CHECK (activity_kind='self_directed'),
    CONSTRAINT activity_revisions_privacy_scope_check CHECK (privacy_scope='private'),
    CONSTRAINT activity_revisions_origin_check CHECK ((origin_opportunity_id IS NULL) <> (origin_admin_change_id IS NULL)),
    activity_revision_id uuid NOT NULL,
    opportunity_id uuid UNIQUE,
    cognitive_episode_id uuid,
    candidate_application_id uuid,
    output_material_id uuid,
    CONSTRAINT activity_revisions_work_origin_check CHECK ((opportunity_id IS NULL AND cognitive_episode_id IS NULL AND candidate_application_id IS NULL AND output_material_id IS NULL) OR (opportunity_id IS NOT NULL AND cognitive_episode_id IS NOT NULL AND candidate_application_id IS NOT NULL AND candidate_validation_id IS NOT NULL)),
    activity_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid,
    candidate_validation_id uuid,
    proposal_ref text,
    goal text,
    progress_summary text,
    waiting_condition text,
    resumption_cue text,
    next_safe_step text,
    status text NOT NULL,
    terminal_reason text,
    related_scene_id uuid,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    transition_kind text NOT NULL,
    waiting_condition_kind text,
    resume_not_before timestamp(6) with time zone,
    data_rights_redacted_at timestamp(6) with time zone,
    admin_change_id uuid,
    CONSTRAINT activity_revisions_activity_revision_id_check CHECK ((uuid_extract_version(activity_revision_id) = 7)),
    CONSTRAINT activity_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT activity_revisions_check1 CHECK (((data_rights_redacted_at IS NOT NULL) OR ((status = ANY (ARRAY['completed'::text, 'abandoned'::text, 'failed'::text])) = (terminal_reason IS NOT NULL)))),
    CONSTRAINT activity_revisions_goal_check CHECK (((goal IS NULL) OR ((octet_length(goal) >= 1) AND (octet_length(goal) <= 8192)))),
    CONSTRAINT activity_revisions_next_safe_step_check CHECK (((octet_length(next_safe_step) >= 1) AND (octet_length(next_safe_step) <= 4096))),
    CONSTRAINT activity_revisions_payload_shape_check CHECK (((data_rights_redacted_at IS NOT NULL) OR ((status = ANY (ARRAY['completed'::text, 'abandoned'::text, 'failed'::text])) AND (terminal_reason IS NOT NULL) AND (next_safe_step IS NULL) AND (waiting_condition IS NULL) AND (waiting_condition_kind IS NULL) AND (resumption_cue IS NULL) AND (resume_not_before IS NULL)) OR ((status = ANY (ARRAY['ready'::text, 'in_progress'::text, 'resuming'::text])) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NULL) AND (waiting_condition_kind IS NULL) AND (resumption_cue IS NULL) AND (resume_not_before IS NULL)) OR ((status = 'waiting'::text) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NOT NULL) AND (waiting_condition_kind = ANY (ARRAY['time'::text, 'creator_input'::text, 'external_evidence'::text])) AND (resumption_cue IS NOT NULL) AND ((waiting_condition_kind = 'time'::text) = (resume_not_before IS NOT NULL))) OR ((status = 'paused'::text) AND (terminal_reason IS NULL) AND (next_safe_step IS NOT NULL) AND (waiting_condition IS NOT NULL) AND (waiting_condition_kind = 'scheduled_review'::text) AND (resumption_cue IS NOT NULL) AND (resume_not_before IS NOT NULL)))),
    CONSTRAINT activity_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT activity_revisions_admin_provenance CHECK ((admin_change_id IS NULL AND transition_kind NOT IN ('admin_update','admin_delete')) OR (admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL AND transition_kind IN ('created','admin_update','admin_delete'))),
    CONSTRAINT activity_revisions_provenance_check CHECK ((admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL) OR (((transition_kind = ANY (ARRAY['system_pause'::text,'data_rights'::text])) AND (subject_commit_id IS NULL) AND (candidate_validation_id IS NULL) AND (proposal_ref IS NULL)) OR ((transition_kind <> ALL (ARRAY['system_pause'::text,'data_rights'::text])) AND (subject_commit_id IS NOT NULL) AND (candidate_validation_id IS NOT NULL) AND (proposal_ref IS NOT NULL)))),
    CONSTRAINT activity_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT activity_revisions_status_check CHECK ((status = ANY (ARRAY['considering'::text, 'ready'::text, 'in_progress'::text, 'waiting'::text, 'paused'::text, 'resuming'::text, 'completed'::text, 'abandoned'::text, 'failed'::text]))),
    CONSTRAINT activity_revisions_transition_kind_check CHECK ((transition_kind = ANY (ARRAY['admin_update'::text, 'admin_delete'::text, 'created'::text, 'engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text, 'system_fail'::text, 'system_pause'::text, 'data_rights'::text]))),
    CONSTRAINT activity_revisions_transition_state_check CHECK ((admin_change_id IS NOT NULL AND ((transition_kind='admin_update' AND status IN ('ready','paused','waiting')) OR (transition_kind='admin_delete' AND status='abandoned'))) OR (((transition_kind = 'created'::text) AND (revision_no = 1) AND (status = 'ready'::text)) OR ((transition_kind = 'engage'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'progress'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'wait'::text) AND (status = 'waiting'::text)) OR ((transition_kind = ANY (ARRAY['pause'::text, 'system_pause'::text])) AND (status = 'paused'::text)) OR ((transition_kind = 'resume'::text) AND (status = 'resuming'::text)) OR ((transition_kind = 'complete'::text) AND (status = 'completed'::text)) OR ((transition_kind = ANY (ARRAY['abandon'::text,'data_rights'::text])) AND (status = 'abandoned'::text)) OR ((transition_kind = 'system_fail'::text) AND (status = 'failed'::text)))),
    CONSTRAINT activity_revisions_waiting_kind_check CHECK (((waiting_condition_kind IS NULL) OR (waiting_condition_kind = ANY (ARRAY['time'::text, 'creator_input'::text, 'external_evidence'::text, 'scheduled_review'::text]))))
);



--
--



--
-- Name: maintenance_sessions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.maintenance_sessions (
    maintenance_session_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    origin_opportunity_id uuid,
    cycle_anchor_kind text NOT NULL,
    cycle_anchor_ref uuid NOT NULL,
    consideration_at timestamp(6) with time zone NOT NULL,
    deadline_at timestamp(6) with time zone NOT NULL,
    trigger_kind text NOT NULL,
    sleep_episode_id uuid,
    started_subject_version bigint NOT NULL,
    started_state_epoch bigint NOT NULL,
    current_revision_id uuid UNIQUE,
    phase text DEFAULT 'preparing' NOT NULL,
    result_status text DEFAULT 'running' NOT NULL,
    phase_completed_at timestamp(6) with time zone,
    updated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT maintenance_sessions_phase_check CHECK (phase IN ('preparing','memory_maintenance','self_check','reflect_self','reflect_mind','reflect_mood','reflect_prompt','life_quiet','resume_check','completed')),
    CONSTRAINT maintenance_sessions_result_check CHECK (result_status IN ('running','completed','interrupted','failed') AND ((phase='completed')=(result_status='completed'))),
    CONSTRAINT maintenance_sessions_phase_token_check CHECK (uuid_extract_version(current_revision_id)=7),
    head_version bigint DEFAULT 1 NOT NULL,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    finished_at timestamp(6) with time zone,
    wake_request_id uuid,
    wake_requested_at timestamp(6) with time zone,
    wake_source_kind text,
    wake_source_ref uuid,
    quiet_until timestamp(6) with time zone,
    CONSTRAINT maintenance_sessions_check CHECK ((consideration_at < deadline_at)),
    CONSTRAINT maintenance_sessions_check1 CHECK (((trigger_kind = 'subject_choice'::text) = (sleep_episode_id IS NOT NULL))),
    CONSTRAINT maintenance_sessions_current_revision_required CHECK ((current_revision_id IS NOT NULL)),
    CONSTRAINT maintenance_sessions_cycle_anchor_kind_check CHECK ((cycle_anchor_kind = ANY (ARRAY['subject_birth'::text, 'maintenance_session'::text]))),
    CONSTRAINT maintenance_sessions_cycle_anchor_ref_check CHECK ((uuid_extract_version(cycle_anchor_ref) = 7)),
    CONSTRAINT maintenance_sessions_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT maintenance_sessions_maintenance_session_id_check CHECK ((uuid_extract_version(maintenance_session_id) = 7)),
    CONSTRAINT maintenance_sessions_quiet_window CHECK (((quiet_until IS NULL) OR (quiet_until >= started_at))),
    CONSTRAINT maintenance_sessions_started_state_epoch_check CHECK ((started_state_epoch >= 0)),
    CONSTRAINT maintenance_sessions_started_subject_version_check CHECK ((started_subject_version >= 0)),
    CONSTRAINT maintenance_sessions_trigger_kind_check CHECK ((trigger_kind = ANY (ARRAY['subject_choice'::text, 'system_deadline'::text]))),
    CONSTRAINT maintenance_sessions_wake_request_id_check CHECK (((wake_request_id IS NULL) OR (uuid_extract_version(wake_request_id) = 7))),
    CONSTRAINT maintenance_sessions_wake_request_shape CHECK (((wake_request_id IS NULL) = (wake_requested_at IS NULL) AND (wake_requested_at IS NULL) = (wake_source_kind IS NULL) AND (wake_source_kind IS NULL) = (wake_source_ref IS NULL))),
    CONSTRAINT maintenance_sessions_wake_source_kind_check CHECK (((wake_source_kind IS NULL) OR (wake_source_kind = ANY (ARRAY['creator_request'::text, 'creator_input'::text])))),
    CONSTRAINT maintenance_sessions_wake_source_ref_check CHECK (((wake_source_ref IS NULL) OR (uuid_extract_version(wake_source_ref) = 7)))
);
