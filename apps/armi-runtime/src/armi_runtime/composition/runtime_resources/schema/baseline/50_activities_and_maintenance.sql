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
    CONSTRAINT activities_activity_id_check CHECK ((uuid_extract_version(activity_id) = 7)),
    CONSTRAINT activities_activity_kind_check CHECK ((activity_kind = 'self_directed'::text)),
    CONSTRAINT activities_current_revision_state_check CHECK ((((head_version = 0) AND (current_revision_id IS NULL)) OR ((head_version > 0) AND (current_revision_id IS NOT NULL)))),
    CONSTRAINT activities_head_version_check CHECK ((head_version >= 0)),
    CONSTRAINT activities_privacy_scope_check CHECK ((privacy_scope = 'private'::text))
);

--
-- Name: activity_decisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.activity_decisions (
    activity_decision_id uuid NOT NULL,
    decision_source text NOT NULL,
    opportunity_id uuid NOT NULL,
    cognitive_episode_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    candidate_application_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    expected_revision_id uuid NOT NULL,
    expected_head_version bigint NOT NULL,
    decision_kind text NOT NULL,
    result_revision_id uuid,
    review_not_before timestamp(6) with time zone,
    output_material_id uuid,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT activity_decisions_head_version_check CHECK ((expected_head_version > 0)),
    CONSTRAINT activity_decisions_id_check CHECK ((uuid_extract_version(activity_decision_id) = 7)),
    CONSTRAINT activity_decisions_shape_check CHECK ((((decision_source = 'attention'::text) AND (output_material_id IS NULL)) OR ((decision_source = 'internal_work'::text) AND (review_not_before IS NULL) AND (result_revision_id IS NOT NULL)))),
    CONSTRAINT activity_decisions_source_check CHECK ((decision_source = ANY (ARRAY['attention'::text, 'internal_work'::text])))
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
    CONSTRAINT activity_revisions_status_check CHECK ((status = ANY (ARRAY['considering'::text, 'ready'::text, 'in_progress'::text, 'waiting'::text, 'paused'::text, 'resuming'::text, 'completed'::text, 'abandoned'::text, 'failed'::text]))),
    CONSTRAINT activity_revisions_transition_kind_check CHECK ((transition_kind = ANY (ARRAY['created'::text, 'engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text, 'system_fail'::text]))),
    CONSTRAINT activity_revisions_transition_state_check CHECK ((((transition_kind = 'created'::text) AND (revision_no = 1) AND (status = 'ready'::text)) OR ((transition_kind = 'engage'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'progress'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'wait'::text) AND (status = 'waiting'::text)) OR ((transition_kind = 'pause'::text) AND (status = 'paused'::text)) OR ((transition_kind = 'resume'::text) AND (status = 'resuming'::text)) OR ((transition_kind = 'complete'::text) AND (status = 'completed'::text)) OR ((transition_kind = 'abandon'::text) AND (status = 'abandoned'::text)) OR ((transition_kind = 'system_fail'::text) AND (status = 'failed'::text)))),
    CONSTRAINT activity_revisions_waiting_kind_check CHECK (((waiting_condition_kind IS NULL) OR (waiting_condition_kind = ANY (ARRAY['time'::text, 'creator_input'::text, 'external_evidence'::text, 'scheduled_review'::text]))))
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
    CONSTRAINT maintenance_phase_results_check CHECK ((((phase = 'memory_maintenance'::text) AND (outcome = ANY (ARRAY['memory_changed'::text, 'memory_unchanged'::text]))) OR ((phase = 'self_check'::text) AND (outcome = ANY (ARRAY['issue_found'::text, 'no_issue'::text]))))),
    CONSTRAINT maintenance_phase_results_check1 CHECK (((outcome = 'memory_changed'::text) = (memory_id IS NOT NULL))),
    CONSTRAINT maintenance_phase_results_check2 CHECK (((outcome = 'issue_found'::text) = (creator_visible_problem IS NOT NULL))),
    CONSTRAINT maintenance_phase_results_creator_visible_problem_check CHECK (((creator_visible_problem IS NULL) OR ((length(creator_visible_problem) >= 1) AND (length(creator_visible_problem) <= 512)))),
    CONSTRAINT maintenance_phase_results_expected_head_version_check CHECK ((expected_head_version > 0)),
    CONSTRAINT maintenance_phase_results_maintenance_phase_result_id_check CHECK ((uuid_extract_version(maintenance_phase_result_id) = 7)),
    CONSTRAINT maintenance_phase_results_outcome_check CHECK ((outcome = ANY (ARRAY['memory_changed'::text, 'memory_unchanged'::text, 'issue_found'::text, 'no_issue'::text]))),
    CONSTRAINT maintenance_phase_results_phase_check CHECK ((phase = ANY (ARRAY['memory_maintenance'::text, 'self_check'::text]))),
    CONSTRAINT maintenance_phase_results_result_summary_check CHECK (((length(result_summary) >= 1) AND (length(result_summary) <= 512)))
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
    CONSTRAINT maintenance_session_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (phase = 'preparing'::text) AND (result_status = 'running'::text) AND (transition_kind = 'started'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT maintenance_session_revisions_check1 CHECK (((phase = 'completed'::text) = (result_status = 'completed'::text))),
    CONSTRAINT maintenance_session_revisions_maintenance_revision_id_check CHECK ((uuid_extract_version(maintenance_revision_id) = 7)),
    CONSTRAINT maintenance_session_revisions_phase_check CHECK ((phase = ANY (ARRAY['preparing'::text, 'memory_maintenance'::text, 'self_check'::text, 'life_quiet'::text, 'resume_check'::text, 'completed'::text]))),
    CONSTRAINT maintenance_session_revisions_result_status_check CHECK ((result_status = ANY (ARRAY['running'::text, 'completed'::text, 'interrupted'::text, 'failed'::text]))),
    CONSTRAINT maintenance_session_revisions_revision_no_check CHECK ((revision_no > 0)),
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
    trigger_kind text NOT NULL,
    sleep_decision_id uuid,
    started_subject_version bigint NOT NULL,
    started_state_epoch bigint NOT NULL,
    current_revision_id uuid,
    head_version bigint DEFAULT 1 NOT NULL,
    started_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    finished_at timestamp(6) with time zone,
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
    CONSTRAINT maintenance_sessions_started_state_epoch_check CHECK ((started_state_epoch >= 0)),
    CONSTRAINT maintenance_sessions_started_subject_version_check CHECK ((started_subject_version >= 0)),
    CONSTRAINT maintenance_sessions_trigger_kind_check CHECK ((trigger_kind = ANY (ARRAY['subject_choice'::text, 'system_deadline'::text]))),
    CONSTRAINT maintenance_sessions_wake_request_id_check CHECK (((wake_request_id IS NULL) OR (uuid_extract_version(wake_request_id) = 7))),
    CONSTRAINT maintenance_sessions_wake_request_shape CHECK (((wake_request_id IS NULL) = (wake_requested_at IS NULL)))
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
    decision_kind text NOT NULL,
    review_not_before timestamp(6) with time zone,
    decided_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT sleep_decisions_check CHECK (((decision_kind = 'defer'::text) = (review_not_before IS NOT NULL))),
    CONSTRAINT sleep_decisions_cycle_anchor_ref_check CHECK ((uuid_extract_version(cycle_anchor_ref) = 7)),
    CONSTRAINT sleep_decisions_decision_kind_check CHECK ((decision_kind = ANY (ARRAY['sleep'::text, 'stay_awake'::text, 'defer'::text, 'need_information'::text]))),
    CONSTRAINT sleep_decisions_sleep_decision_id_check CHECK ((uuid_extract_version(sleep_decision_id) = 7))
);
