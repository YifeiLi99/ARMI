-- Current ARMI role grants.

--
-- Name: SCHEMA armi; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA armi TO armi_admin;
GRANT USAGE ON SCHEMA armi TO armi_migrator;
GRANT USAGE ON SCHEMA armi TO armi_runtime;

--
-- Name: SCHEMA armi_extensions; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA armi_extensions TO armi_owner;
GRANT USAGE ON SCHEMA armi_extensions TO armi_migrator;
GRANT USAGE ON SCHEMA armi_extensions TO armi_runtime;
GRANT USAGE ON SCHEMA armi_extensions TO armi_admin;

--
-- Name: TABLE accepted_experiences; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.accepted_experiences TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.accepted_experiences TO armi_runtime;

--
-- Name: TABLE action_intent_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.action_intent_revisions TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.action_intent_revisions TO armi_runtime;

--
-- Name: TABLE action_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.action_intents TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.action_intents TO armi_runtime;

--
-- Name: TABLE activities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activities TO armi_admin;
GRANT SELECT ON TABLE armi.activities TO armi_runtime;

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
-- Name: TABLE activity_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activity_decisions TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.activity_decisions TO armi_runtime;

--
-- Name: TABLE activity_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.activity_revisions TO armi_admin;
GRANT SELECT ON TABLE armi.activity_revisions TO armi_runtime;

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

GRANT SELECT,DELETE ON TABLE armi.artifacts TO armi_admin;
GRANT SELECT ON TABLE armi.artifacts TO armi_runtime;

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
-- Name: TABLE audit_events; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.audit_events TO armi_admin;
GRANT SELECT ON TABLE armi.audit_events TO armi_runtime;

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
-- Name: COLUMN audit_events.policy_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(policy_ref) ON TABLE armi.audit_events TO armi_runtime;

--
-- Name: COLUMN audit_events.grant_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(grant_ref) ON TABLE armi.audit_events TO armi_runtime;

--
-- Name: COLUMN audit_events.error_category; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(error_category) ON TABLE armi.audit_events TO armi_runtime;

--
-- Name: TABLE capabilities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capabilities TO armi_admin;
GRANT SELECT ON TABLE armi.capabilities TO armi_runtime;

--
-- Name: TABLE capability_request_basis_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capability_request_basis_links TO armi_admin;
GRANT SELECT ON TABLE armi.capability_request_basis_links TO armi_runtime;

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

GRANT SELECT ON TABLE armi.capability_request_decisions TO armi_admin;
GRANT SELECT ON TABLE armi.capability_request_decisions TO armi_runtime;

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
-- Name: COLUMN capability_request_decisions.reason_code; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reason_code) ON TABLE armi.capability_request_decisions TO armi_runtime;

--
-- Name: TABLE capability_requests; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.capability_requests TO armi_admin;
GRANT SELECT ON TABLE armi.capability_requests TO armi_runtime;

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
-- Name: TABLE cognition_maintenance_batch_sources; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognition_maintenance_batch_sources TO armi_runtime;
GRANT SELECT ON TABLE armi.cognition_maintenance_batch_sources TO armi_admin;

--
-- Name: TABLE cognition_maintenance_batches; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognition_maintenance_batches TO armi_runtime;
GRANT SELECT ON TABLE armi.cognition_maintenance_batches TO armi_admin;

--
-- Name: TABLE cognition_maintenance_cursors; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognition_maintenance_cursors TO armi_runtime;
GRANT SELECT ON TABLE armi.cognition_maintenance_cursors TO armi_admin;

--
-- Name: TABLE cognitive_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_admin;
GRANT SELECT ON TABLE armi.cognitive_attempts TO armi_runtime;

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
-- Name: TABLE cognitive_branches; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognitive_branches TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_branches TO armi_admin;

--
-- Name: TABLE cognitive_candidate_applications; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_candidate_applications TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_applications TO armi_runtime;

--
-- Name: TABLE cognitive_candidate_basis_links; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_candidate_basis_links TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_basis_links TO armi_runtime;

--
-- Name: TABLE cognitive_candidate_validation_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_candidate_validation_items TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_validation_items TO armi_runtime;

--
-- Name: TABLE cognitive_candidate_validations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_candidate_validations TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.cognitive_candidate_validations TO armi_runtime;

--
-- Name: TABLE cognitive_context_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_context_items TO armi_admin;
GRANT SELECT ON TABLE armi.cognitive_context_items TO armi_runtime;

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
-- Name: TABLE cognitive_dialogue_aggregates; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognitive_dialogue_aggregates TO armi_runtime;
GRANT SELECT ON TABLE armi.cognitive_dialogue_aggregates TO armi_admin;

--
-- Name: TABLE cognitive_episodes; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.cognitive_episodes TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.cognitive_episodes TO armi_runtime;

--
-- Name: TABLE context_embedding_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.context_embedding_attempts TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.context_embedding_attempts TO armi_runtime;

--
-- Name: TABLE context_embedding_coverage; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.context_embedding_coverage TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.context_embedding_coverage TO armi_runtime;

--
-- Name: TABLE context_embedding_projections; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.context_embedding_projections TO armi_admin;
GRANT SELECT,INSERT,DELETE ON TABLE armi.context_embedding_projections TO armi_runtime;

--
-- Name: TABLE context_model_cache_hit_ratios; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.context_model_cache_hit_ratios TO armi_admin;
GRANT SELECT ON TABLE armi.context_model_cache_hit_ratios TO armi_runtime;

--
-- Name: TABLE creator_exports; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.creator_exports TO armi_runtime;

--
-- Name: COLUMN creator_exports.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.creator_exports TO armi_runtime;

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

GRANT SELECT ON TABLE armi.deployment_environments TO armi_admin;
GRANT SELECT ON TABLE armi.deployment_environments TO armi_runtime;

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
-- Name: TABLE dialogue_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.dialogue_decisions TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.dialogue_decisions TO armi_runtime;

--
-- Name: TABLE durable_work; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.durable_work TO armi_admin;
GRANT SELECT ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.work_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_id) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(work_id) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.work_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(work_kind) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(work_kind) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.owner_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(owner_kind) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(owner_kind) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.owner_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(owner_ref) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(owner_ref) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(subject_id) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.idempotency_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(idempotency_key) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(idempotency_key) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.payload_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_kind) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(payload_kind) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.payload_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_ref) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(payload_ref) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.payload_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(payload_digest) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(payload_digest) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.priority; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(priority) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(priority) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.not_before; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(not_before),UPDATE(not_before) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(not_before),UPDATE(not_before) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.deadline_at; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(deadline_at) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(deadline_at) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(status),UPDATE(status) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(status),UPDATE(status) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.max_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(max_attempts) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(max_attempts) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.attempt_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(attempt_count) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(attempt_count),UPDATE(attempt_count) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.current_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(current_attempt_id) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(current_attempt_id) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.lease_owner; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(lease_owner) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(lease_owner) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.lease_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(lease_expires_at) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(lease_expires_at) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.lease_token; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(lease_token),UPDATE(lease_token) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(lease_token),UPDATE(lease_token) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.result_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_kind) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(result_kind) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.result_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_ref) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(result_ref) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(last_error_code) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.trace_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(trace_id) ON TABLE armi.durable_work TO armi_admin;
GRANT INSERT(trace_id) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: COLUMN durable_work.updated_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE armi.durable_work TO armi_admin;
GRANT UPDATE(updated_at) ON TABLE armi.durable_work TO armi_runtime;

--
-- Name: TABLE effect_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effect_attempts TO armi_admin;
GRANT SELECT ON TABLE armi.effect_attempts TO armi_runtime;

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
-- Name: TABLE effect_observations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effect_observations TO armi_admin;
GRANT SELECT ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.effect_observation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_observation_id) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(effect_observation_id) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.effect_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_id) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(effect_id) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.effect_attempt_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(effect_attempt_id) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(effect_attempt_id) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.observation_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_kind) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(observation_kind) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.reliability; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(reliability) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(reliability) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.receiver_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(receiver_ref) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(receiver_ref) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.observation_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(observation_digest) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(observation_digest) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: COLUMN effect_observations.receiver_external_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(receiver_external_ref) ON TABLE armi.effect_observations TO armi_admin;
GRANT INSERT(receiver_external_ref) ON TABLE armi.effect_observations TO armi_runtime;

--
-- Name: TABLE effect_outbox_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.effect_outbox_items TO armi_runtime;

--
-- Name: COLUMN effect_outbox_items.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT UPDATE(status) ON TABLE armi.effect_outbox_items TO armi_runtime;

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

GRANT UPDATE(claim_owner) ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT UPDATE(claim_owner) ON TABLE armi.effect_outbox_items TO armi_runtime;

--
-- Name: COLUMN effect_outbox_items.claim_expires_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(claim_expires_at) ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT UPDATE(claim_expires_at) ON TABLE armi.effect_outbox_items TO armi_runtime;

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

GRANT UPDATE(delivered_at) ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT UPDATE(delivered_at) ON TABLE armi.effect_outbox_items TO armi_runtime;

--
-- Name: COLUMN effect_outbox_items.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.effect_outbox_items TO armi_admin;
GRANT UPDATE(last_error_code) ON TABLE armi.effect_outbox_items TO armi_runtime;

--
-- Name: TABLE effects; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.effects TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.effects TO armi_runtime;

--
-- Name: COLUMN effects.action_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(action_intent_id) ON TABLE armi.effects TO armi_runtime;

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

GRANT SELECT ON TABLE armi.experience_evidence_links TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.experience_evidence_links TO armi_runtime;

--
-- Name: TABLE external_channel_bindings; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.external_channel_bindings TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.external_channel_bindings TO armi_runtime;

--
-- Name: COLUMN external_channel_bindings.scene_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(scene_id) ON TABLE armi.external_channel_bindings TO armi_runtime;

--
-- Name: COLUMN external_channel_bindings.display_label; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(display_label) ON TABLE armi.external_channel_bindings TO armi_runtime;

--
-- Name: COLUMN external_channel_bindings.last_observed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_observed_at) ON TABLE armi.external_channel_bindings TO armi_runtime;

--
-- Name: TABLE external_content_recognition_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.external_content_recognition_attempts TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.external_content_recognition_attempts TO armi_admin;

--
-- Name: TABLE external_evidence; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.external_evidence TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.external_evidence TO armi_runtime;

--
-- Name: COLUMN external_evidence.visual_observation_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(visual_observation_id) ON TABLE armi.external_evidence TO armi_runtime;
GRANT SELECT(visual_observation_id) ON TABLE armi.external_evidence TO armi_admin;

--
-- Name: TABLE external_message_parts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.external_message_parts TO armi_runtime;
GRANT SELECT,DELETE ON TABLE armi.external_message_parts TO armi_admin;

--
-- Name: TABLE interaction_scenes; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.interaction_scenes TO armi_admin;
GRANT SELECT ON TABLE armi.interaction_scenes TO armi_runtime;

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
-- Name: COLUMN interaction_scenes.primary_party_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(primary_party_kind) ON TABLE armi.interaction_scenes TO armi_runtime;

--
-- Name: COLUMN interaction_scenes.scene_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(scene_version) ON TABLE armi.interaction_scenes TO armi_runtime;

--
-- Name: TABLE life_generations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.life_generations TO armi_admin;
GRANT SELECT ON TABLE armi.life_generations TO armi_runtime;

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
-- Name: TABLE live_vision_observation_frames; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_vision_observation_frames TO armi_runtime;
GRANT SELECT ON TABLE armi.live_vision_observation_frames TO armi_admin;

--
-- Name: TABLE live_vision_observations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_vision_observations TO armi_runtime;
GRANT SELECT ON TABLE armi.live_vision_observations TO armi_admin;

--
-- Name: TABLE live_vision_sessions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_vision_sessions TO armi_runtime;
GRANT SELECT ON TABLE armi.live_vision_sessions TO armi_admin;

--
-- Name: TABLE live_voice_playback_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_voice_playback_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.live_voice_playback_attempts TO armi_admin;

--
-- Name: TABLE live_voice_provider_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_voice_provider_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.live_voice_provider_attempts TO armi_admin;

--
-- Name: TABLE live_voice_sessions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_voice_sessions TO armi_runtime;
GRANT SELECT ON TABLE armi.live_voice_sessions TO armi_admin;

--
-- Name: TABLE live_voice_text_fragments; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_voice_text_fragments TO armi_runtime;
GRANT SELECT ON TABLE armi.live_voice_text_fragments TO armi_admin;

--
-- Name: TABLE live_voice_turns; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.live_voice_turns TO armi_runtime;
GRANT SELECT ON TABLE armi.live_voice_turns TO armi_admin;

--
-- Name: TABLE local_inbox_deliveries; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.local_inbox_deliveries TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.local_inbox_deliveries TO armi_runtime;

--
-- Name: TABLE maintenance_phase_results; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_admin;
GRANT SELECT ON TABLE armi.maintenance_phase_results TO armi_runtime;

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
-- Name: TABLE maintenance_session_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.maintenance_session_revisions TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.maintenance_session_revisions TO armi_runtime;

--
-- Name: TABLE maintenance_sessions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.maintenance_sessions TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.maintenance_sessions TO armi_runtime;

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
-- Name: TABLE mood_affective_events; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.mood_affective_events TO armi_runtime;
GRANT SELECT ON TABLE armi.mood_affective_events TO armi_admin;

--
-- Name: TABLE mood_appraisal_events; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.mood_appraisal_events TO armi_runtime;
GRANT SELECT ON TABLE armi.mood_appraisal_events TO armi_admin;

--
-- Name: TABLE mood_heads; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.mood_heads TO armi_runtime;
GRANT SELECT,UPDATE ON TABLE armi.mood_heads TO armi_admin;

--
-- Name: TABLE mood_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT ON TABLE armi.mood_revisions TO armi_runtime;
GRANT SELECT,INSERT ON TABLE armi.mood_revisions TO armi_admin;

--
-- Name: TABLE observation_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.observation_attempts TO armi_admin;
GRANT SELECT ON TABLE armi.observation_attempts TO armi_runtime;

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
-- Name: COLUMN observation_attempts.provider_model_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(provider_model_id) ON TABLE armi.observation_attempts TO armi_runtime;

--
-- Name: COLUMN observation_attempts.result_artifact_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(result_artifact_id) ON TABLE armi.observation_attempts TO armi_runtime;

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
-- Name: TABLE observation_tool_calls; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.observation_tool_calls TO armi_admin;
GRANT SELECT ON TABLE armi.observation_tool_calls TO armi_runtime;

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
-- Name: COLUMN observation_tool_calls.completion_status; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(completion_status) ON TABLE armi.observation_tool_calls TO armi_runtime;

--
-- Name: TABLE opportunities; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.opportunities TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.opportunities TO armi_runtime;

--
-- Name: TABLE parties; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.parties TO armi_admin;
GRANT SELECT ON TABLE armi.parties TO armi_runtime;

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

GRANT INSERT(display_label),UPDATE(display_label) ON TABLE armi.parties TO armi_runtime;

--
-- Name: COLUMN parties.creator_role; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(creator_role) ON TABLE armi.parties TO armi_runtime;

--
-- Name: COLUMN parties.declared_identity_key; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(declared_identity_key) ON TABLE armi.parties TO armi_runtime;

--
-- Name: TABLE party_input_interactions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.party_input_interactions TO armi_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE armi.party_input_interactions TO armi_runtime;

--
-- Name: COLUMN party_input_interactions.modality; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT(modality),INSERT(modality) ON TABLE armi.party_input_interactions TO armi_runtime;
GRANT SELECT(modality) ON TABLE armi.party_input_interactions TO armi_admin;

--
-- Name: TABLE permission_grants; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.permission_grants TO armi_admin;
GRANT SELECT ON TABLE armi.permission_grants TO armi_runtime;

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
-- Name: COLUMN permission_grants.status; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(status) ON TABLE armi.permission_grants TO armi_runtime;

--
-- Name: COLUMN permission_grants.revoked_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(revoked_at) ON TABLE armi.permission_grants TO armi_runtime;

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

GRANT SELECT ON TABLE armi.policy_decisions TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.policy_decisions TO armi_runtime;

--
-- Name: COLUMN policy_decisions.is_current; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(is_current) ON TABLE armi.policy_decisions TO armi_runtime;

--
-- Name: TABLE prompt_documents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.prompt_documents TO armi_admin;
GRANT SELECT ON TABLE armi.prompt_documents TO armi_runtime;

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

GRANT SELECT ON TABLE armi.prompt_revisions TO armi_admin;
GRANT SELECT ON TABLE armi.prompt_revisions TO armi_runtime;

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
-- Name: COLUMN relationships.tombstoned_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(tombstoned_at) ON TABLE armi.relationships TO armi_runtime;

--
-- Name: COLUMN relationships.tombstone_order_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(tombstone_order_id) ON TABLE armi.relationships TO armi_runtime;

--
-- Name: TABLE runtime_bundle_activations; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_bundle_activations TO armi_admin;
GRANT SELECT ON TABLE armi.runtime_bundle_activations TO armi_runtime;

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
-- Name: COLUMN runtime_bundle_activations.fixed_policy_digest; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(fixed_policy_digest) ON TABLE armi.runtime_bundle_activations TO armi_runtime;

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

GRANT SELECT ON TABLE armi.runtime_instances TO armi_admin;
GRANT SELECT ON TABLE armi.runtime_instances TO armi_runtime;

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

GRANT UPDATE(status) ON TABLE armi.runtime_instances TO armi_admin;
GRANT INSERT(status),UPDATE(status) ON TABLE armi.runtime_instances TO armi_runtime;

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

GRANT UPDATE(stopped_at) ON TABLE armi.runtime_instances TO armi_admin;
GRANT UPDATE(stopped_at) ON TABLE armi.runtime_instances TO armi_runtime;

--
-- Name: TABLE runtime_recovery_metrics; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_recovery_metrics TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.runtime_recovery_metrics TO armi_runtime;

--
-- Name: COLUMN runtime_recovery_metrics.metric_value; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(metric_value) ON TABLE armi.runtime_recovery_metrics TO armi_runtime;

--
-- Name: TABLE runtime_recovery_runs; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_admin;
GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_runtime;

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
-- Name: COLUMN runtime_recovery_runs.blocker_count; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(blocker_count),UPDATE(blocker_count) ON TABLE armi.runtime_recovery_runs TO armi_runtime;

--
-- Name: TABLE scene_participants; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.scene_participants TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.scene_participants TO armi_runtime;

--
-- Name: COLUMN scene_participants.last_observed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_observed_at) ON TABLE armi.scene_participants TO armi_runtime;

--
-- Name: TABLE scene_timeline_items; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,DELETE ON TABLE armi.scene_timeline_items TO armi_admin;
GRANT SELECT ON TABLE armi.scene_timeline_items TO armi_runtime;

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
-- Name: TABLE sleep_decisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.sleep_decisions TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.sleep_decisions TO armi_runtime;

--
-- Name: TABLE subject_commits; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subject_commits TO armi_admin;
GRANT SELECT,INSERT ON TABLE armi.subject_commits TO armi_runtime;

--
-- Name: TABLE subject_component_heads; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subject_component_heads TO armi_admin;
GRANT SELECT ON TABLE armi.subject_component_heads TO armi_runtime;

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

GRANT UPDATE(current_revision_id) ON TABLE armi.subject_component_heads TO armi_admin;
GRANT INSERT(current_revision_id),UPDATE(current_revision_id) ON TABLE armi.subject_component_heads TO armi_runtime;

--
-- Name: COLUMN subject_component_heads.component_version; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(component_version) ON TABLE armi.subject_component_heads TO armi_admin;
GRANT INSERT(component_version),UPDATE(component_version) ON TABLE armi.subject_component_heads TO armi_runtime;

--
-- Name: TABLE subject_component_revisions; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT SELECT ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.component_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_revision_id) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(component_revision_id) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.subject_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_id) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(subject_id) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.component_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_kind) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(component_kind) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.component_version; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(component_version) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(component_version) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.previous_revision_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(previous_revision_id) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(previous_revision_id) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.origin_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(origin_kind) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(origin_kind) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.origin_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(origin_ref) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(origin_ref) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.subject_commit_id; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(subject_commit_id) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(subject_commit_id) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.semantic_payload; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(semantic_payload) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(semantic_payload) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.privacy_scope; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(privacy_scope) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(privacy_scope) ON TABLE armi.subject_component_revisions TO armi_runtime;

--
-- Name: COLUMN subject_component_revisions.proposal_ref; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(proposal_ref) ON TABLE armi.subject_component_revisions TO armi_admin;
GRANT INSERT(proposal_ref) ON TABLE armi.subject_component_revisions TO armi_runtime;

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

GRANT SELECT ON TABLE armi.subjects TO armi_admin;
GRANT SELECT ON TABLE armi.subjects TO armi_runtime;

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
-- Name: TABLE visual_recognition_attempts; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE armi.visual_recognition_attempts TO armi_runtime;
GRANT SELECT ON TABLE armi.visual_recognition_attempts TO armi_admin;

--
-- Name: TABLE web_evidence_sources; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_evidence_sources TO armi_admin;
GRANT SELECT ON TABLE armi.web_evidence_sources TO armi_runtime;

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
-- Name: COLUMN web_evidence_sources.acquisition_kind; Type: ACL; Schema: armi; Owner: -
--

GRANT INSERT(acquisition_kind) ON TABLE armi.web_evidence_sources TO armi_runtime;

--
-- Name: TABLE web_observation_requests; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_observation_requests TO armi_admin;
GRANT SELECT ON TABLE armi.web_observation_requests TO armi_runtime;

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
-- Name: COLUMN web_observation_requests.last_error_code; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(last_error_code) ON TABLE armi.web_observation_requests TO armi_runtime;

--
-- Name: COLUMN web_observation_requests.completed_at; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE armi.web_observation_requests TO armi_runtime;

--
-- Name: COLUMN web_observation_requests.web_research_intent_id; Type: ACL; Schema: armi; Owner: -
--

GRANT UPDATE(web_research_intent_id) ON TABLE armi.web_observation_requests TO armi_runtime;

--
-- Name: TABLE web_research_intents; Type: ACL; Schema: armi; Owner: -
--

GRANT SELECT ON TABLE armi.web_research_intents TO armi_admin;
GRANT SELECT ON TABLE armi.web_research_intents TO armi_runtime;

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


GRANT SELECT ON TABLE armi.alembic_version TO armi_admin;
GRANT SELECT ON TABLE armi.alembic_version TO armi_migrator;
GRANT SELECT ON TABLE armi.alembic_version TO armi_runtime;
