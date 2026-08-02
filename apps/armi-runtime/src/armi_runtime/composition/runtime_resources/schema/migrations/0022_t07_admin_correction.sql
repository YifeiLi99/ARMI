ALTER TABLE armi.subject_component_revisions
    DROP CONSTRAINT subject_component_revisions_origin_kind_check,
    DROP CONSTRAINT subject_component_revisions_origin_check,
    ADD CONSTRAINT subject_component_revisions_origin_kind_check
    CHECK (origin_kind IN ('bootstrap', 'subject_commit', 'admin_correction')),
    ADD CONSTRAINT subject_component_revisions_origin_check
    CHECK (
        (origin_kind = 'bootstrap'
            AND component_version = 1
            AND previous_revision_id IS NULL
            AND subject_commit_id IS NULL
            AND proposal_ref IS NULL)
        OR (origin_kind = 'subject_commit'
            AND component_version > 1
            AND previous_revision_id IS NOT NULL
            AND subject_commit_id IS NOT NULL
            AND proposal_ref IS NOT NULL
            AND semantic_digest IS NOT NULL)
        OR (origin_kind = 'admin_correction'
            AND component_version > 1
            AND previous_revision_id IS NOT NULL
            AND subject_commit_id IS NULL
            AND proposal_ref IS NULL
            AND semantic_digest IS NOT NULL)
    );

ALTER TABLE armi.subjects
    DROP CONSTRAINT subjects_state_epoch_check,
    ADD CONSTRAINT subjects_state_epoch_check CHECK (state_epoch >= 0);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_admin_correction_work_count integer NOT NULL DEFAULT 0
        CHECK (resumable_admin_correction_work_count >= 0);

GRANT UPDATE (state_epoch) ON armi.subjects TO armi_admin;

GRANT INSERT (
    component_revision_id,
    subject_id,
    component_kind,
    component_version,
    previous_revision_id,
    origin_kind,
    origin_ref,
    subject_commit_id,
    proposal_ref,
    semantic_digest,
    semantic_payload,
    privacy_scope
) ON armi.subject_component_revisions TO armi_admin;

GRANT UPDATE (current_revision_id, component_version)
ON armi.subject_component_heads TO armi_admin;

GRANT DELETE ON
    armi.creator_input_interactions,
    armi.external_evidence,
    armi.opportunities,
    armi.scene_timeline_items,
    armi.audit_events,
    armi.artifacts
TO armi_admin;

GRANT INSERT (
    work_id,
    work_kind,
    owner_kind,
    owner_ref,
    subject_id,
    idempotency_key,
    payload_kind,
    payload_ref,
    payload_digest,
    priority,
    not_before,
    deadline_at,
    status,
    max_attempts,
    attempt_count,
    lease_token,
    trace_id,
    schema_version
) ON armi.durable_work TO armi_admin;

GRANT UPDATE (
    status,
    not_before,
    current_attempt_id,
    lease_owner,
    lease_expires_at,
    lease_token,
    result_kind,
    result_ref,
    last_error_code,
    updated_at
) ON armi.durable_work TO armi_admin;

GRANT INSERT (
    outbox_item_id,
    work_id,
    message_kind,
    payload_digest,
    status,
    available_at,
    claim_token,
    attempt_count,
    max_attempts,
    trace_id,
    schema_version
) ON armi.outbox_items TO armi_admin;

GRANT UPDATE (
    status,
    available_at,
    claimed_by,
    claim_expires_at,
    claim_token,
    last_error_code,
    delivered_at,
    updated_at
) ON armi.outbox_items TO armi_admin;

GRANT UPDATE (status, stopped_at)
ON armi.runtime_instances TO armi_admin;

GRANT INSERT (
    effect_observation_id,
    effect_id,
    effect_attempt_id,
    observation_kind,
    reliability,
    receiver_ref,
    observation_digest,
    schema_version
) ON armi.effect_observations TO armi_admin;

GRANT UPDATE (
    status,
    verification_status,
    current_observation_id,
    settlement_digest,
    settled_at
) ON armi.effects TO armi_admin;

GRANT UPDATE (
    status,
    claim_owner,
    claim_expires_at,
    delivered_at,
    last_error_code
) ON armi.effect_outbox_items TO armi_admin;

GRANT UPDATE (current_status, reason_code, completed_at)
ON armi.creator_response_operations TO armi_admin;

GRANT INSERT (resumable_admin_correction_work_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_admin_correction_work_count)
ON armi.runtime_recovery_runs TO armi_runtime;
