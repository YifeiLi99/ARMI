CREATE TABLE armi.policy_decisions (
    policy_decision_id uuid PRIMARY KEY CHECK (uuid_extract_version(policy_decision_id) = 7),
    action_intent_revision_id uuid NOT NULL REFERENCES armi.action_intent_revisions(action_intent_revision_id),
    creator_response_operation_id uuid NOT NULL REFERENCES armi.creator_response_operations(creator_response_operation_id),
    matched_grant_id uuid REFERENCES armi.permission_grants(grant_id),
    decision_outcome text NOT NULL CHECK (decision_outcome IN ('allowed', 'denied', 'confirmation_required', 'unavailable')),
    policy_identity text NOT NULL CHECK (policy_identity = 'armi.policy-engine.deterministic-v1'),
    decision_digest text NOT NULL CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$'),
    reason_code text NOT NULL CHECK (reason_code ~ '^POLICY-[A-Z0-9-]+$'),
    supersedes_policy_decision_id uuid REFERENCES armi.policy_decisions(policy_decision_id),
    is_current boolean NOT NULL DEFAULT true,
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    valid_until timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK ((decision_outcome = 'allowed') = (matched_grant_id IS NOT NULL)),
    CHECK (valid_until IS NULL OR valid_until > decided_at),
    CHECK (supersedes_policy_decision_id IS NULL OR supersedes_policy_decision_id <> policy_decision_id)
);

CREATE UNIQUE INDEX policy_decisions_one_current
ON armi.policy_decisions (action_intent_revision_id) WHERE is_current;

CREATE TABLE armi.effects (
    effect_id uuid PRIMARY KEY CHECK (uuid_extract_version(effect_id) = 7),
    action_intent_revision_id uuid NOT NULL REFERENCES armi.action_intent_revisions(action_intent_revision_id),
    creator_response_operation_id uuid NOT NULL UNIQUE REFERENCES armi.creator_response_operations(creator_response_operation_id),
    policy_decision_id uuid NOT NULL UNIQUE REFERENCES armi.policy_decisions(policy_decision_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    payload_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    payload_bytes integer NOT NULL CHECK (payload_bytes BETWEEN 1 AND 65536),
    effect_kind text NOT NULL CHECK (effect_kind = 'creator_response'),
    capability_kind text NOT NULL CHECK (capability_kind = 'creator.scene.reply'),
    operation_class text NOT NULL CHECK (operation_class = 'send'),
    audience_scope text NOT NULL CHECK (audience_scope = 'creator'),
    data_scope text NOT NULL CHECK (data_scope = 'creator_visible_response'),
    purpose text NOT NULL CHECK (purpose = 'respond_to_creator'),
    registration_digest text NOT NULL CHECK (registration_digest ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('registered', 'cancelled')),
    verification_status text NOT NULL CHECK (verification_status = 'not_started'),
    registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    cancelled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (action_intent_revision_id, effect_kind),
    CHECK ((status = 'registered' AND cancelled_at IS NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL))
);

CREATE TABLE armi.effect_outbox_items (
    effect_outbox_item_id uuid PRIMARY KEY CHECK (uuid_extract_version(effect_outbox_item_id) = 7),
    effect_id uuid NOT NULL UNIQUE REFERENCES armi.effects(effect_id),
    message_kind text NOT NULL CHECK (message_kind = 'effect.dispatch'),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('ready', 'cancelled')),
    available_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    cancelled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK ((status = 'ready' AND cancelled_at IS NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL))
);

ALTER TABLE armi.creator_response_operations
    DROP CONSTRAINT creator_response_operations_current_status_check,
    DROP CONSTRAINT creator_response_operations_check,
    ADD COLUMN registration_work_id uuid UNIQUE REFERENCES armi.durable_work(work_id),
    ADD COLUMN current_policy_decision_id uuid UNIQUE REFERENCES armi.policy_decisions(policy_decision_id),
    ADD COLUMN effect_id uuid UNIQUE REFERENCES armi.effects(effect_id),
    ADD COLUMN effect_registration_digest text CHECK (effect_registration_digest IS NULL OR effect_registration_digest ~ '^sha256:[0-9a-f]{64}$'),
    ADD COLUMN effect_registered_at timestamptz(6),
    ADD CONSTRAINT creator_response_operations_current_status_check CHECK (
        current_status IN ('pending', 'accepted', 'effect_registered', 'effect_cancelled', 'no_action', 'unauthorized', 'unavailable', 'failed')
    ),
    ADD CONSTRAINT creator_response_operations_check CHECK (
        (current_status = 'pending' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NULL AND reason_code IS NULL AND completed_at IS NULL)
        OR (current_status = 'accepted' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('effect_registered', 'effect_cancelled') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status = 'no_action' AND action_intent_id IS NULL AND formal_no_action_id IS NOT NULL AND admission_work_id IS NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('unauthorized', 'unavailable', 'failed') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NOT NULL AND completed_at IS NOT NULL)
    ),
    ADD CONSTRAINT creator_response_operations_effect_state_check CHECK (
        (current_status = 'effect_registered' AND current_policy_decision_id IS NOT NULL AND effect_id IS NOT NULL AND effect_registration_digest IS NOT NULL AND effect_registered_at IS NOT NULL)
        OR (current_status = 'effect_cancelled' AND current_policy_decision_id IS NOT NULL AND effect_id IS NOT NULL AND effect_registration_digest IS NOT NULL AND effect_registered_at IS NOT NULL)
        OR (current_status IN ('unauthorized', 'unavailable') AND current_policy_decision_id IS NOT NULL AND effect_id IS NULL AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
        OR (current_status NOT IN ('effect_registered', 'effect_cancelled', 'unauthorized', 'unavailable') AND current_policy_decision_id IS NULL AND effect_id IS NULL AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_effect_count integer NOT NULL DEFAULT 0 CHECK (resumable_effect_count >= 0),
    ADD COLUMN resumable_effect_outbox_count integer NOT NULL DEFAULT 0 CHECK (resumable_effect_outbox_count >= 0);

REVOKE ALL ON TABLE armi.policy_decisions, armi.effects, armi.effect_outbox_items
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.policy_decisions, armi.effects, armi.effect_outbox_items TO armi_runtime;
GRANT INSERT ON TABLE armi.policy_decisions, armi.effects, armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE (is_current) ON armi.policy_decisions TO armi_runtime;
GRANT UPDATE (status, cancelled_at) ON armi.effects TO armi_runtime;
GRANT UPDATE (status, cancelled_at) ON armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE (consumed_uses, status, revoked_at) ON armi.permission_grants TO armi_runtime;
GRANT INSERT (registration_work_id, current_policy_decision_id, effect_id, effect_registration_digest, effect_registered_at)
ON armi.creator_response_operations TO armi_runtime;
GRANT UPDATE (registration_work_id, current_status, current_policy_decision_id, effect_id, effect_registration_digest, effect_registered_at, reason_code, completed_at)
ON armi.creator_response_operations TO armi_runtime;
GRANT INSERT (resumable_effect_count, resumable_effect_outbox_count) ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_effect_count, resumable_effect_outbox_count) ON armi.runtime_recovery_runs TO armi_runtime;
