ALTER TABLE armi.effects
    DROP CONSTRAINT effects_status_check,
    DROP CONSTRAINT effects_verification_status_check,
    DROP CONSTRAINT effects_check,
    ADD CONSTRAINT effects_status_check CHECK (
        status IN ('registered', 'dispatching', 'completed', 'failed', 'unknown', 'cancelled')
    ),
    ADD CONSTRAINT effects_verification_status_check CHECK (
        verification_status IN ('not_started', 'pending', 'verified', 'inconclusive')
    ),
    ADD COLUMN trace_id text;

UPDATE armi.effects AS effect
SET trace_id = work.trace_id
FROM armi.creator_response_operations AS operation
JOIN armi.durable_work AS work ON work.work_id = operation.registration_work_id
WHERE operation.creator_response_operation_id = effect.creator_response_operation_id;

ALTER TABLE armi.effects
    ALTER COLUMN trace_id SET NOT NULL,
    ADD CONSTRAINT effects_trace_id_check CHECK (trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32));

ALTER TABLE armi.effect_outbox_items
    DROP CONSTRAINT effect_outbox_items_status_check,
    DROP CONSTRAINT effect_outbox_items_check,
    ADD COLUMN claim_owner uuid,
    ADD COLUMN claim_expires_at timestamptz(6),
    ADD COLUMN claim_token bigint NOT NULL DEFAULT 0 CHECK (claim_token >= 0),
    ADD COLUMN attempt_count smallint NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 2),
    ADD COLUMN max_attempts smallint NOT NULL DEFAULT 2 CHECK (max_attempts = 2),
    ADD COLUMN dispatch_deadline timestamptz(6),
    ADD COLUMN delivered_at timestamptz(6),
    ADD COLUMN last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^EFFECT-[A-Z0-9-]+$'
    );

UPDATE armi.effect_outbox_items AS outbox
SET dispatch_deadline = decision.valid_until,
    payload_digest = effect.payload_digest
FROM armi.effects AS effect
JOIN armi.policy_decisions AS decision
  ON decision.policy_decision_id = effect.policy_decision_id
WHERE outbox.effect_id = effect.effect_id;

ALTER TABLE armi.effect_outbox_items
    ALTER COLUMN dispatch_deadline SET NOT NULL,
    ADD CONSTRAINT effect_outbox_items_status_check CHECK (
        status IN ('ready', 'claimed', 'delivered', 'dead', 'unknown', 'cancelled')
    ),
    ADD CONSTRAINT effect_outbox_items_check CHECK (
        (status = 'ready' AND claim_owner IS NULL AND claim_expires_at IS NULL
            AND cancelled_at IS NULL AND delivered_at IS NULL)
        OR (status = 'claimed' AND claim_owner IS NOT NULL AND claim_expires_at IS NOT NULL
            AND claim_token > 0 AND cancelled_at IS NULL AND delivered_at IS NULL)
        OR (status = 'delivered' AND claim_owner IS NULL AND claim_expires_at IS NULL
            AND cancelled_at IS NULL AND delivered_at IS NOT NULL)
        OR (status IN ('dead', 'unknown') AND claim_owner IS NULL AND claim_expires_at IS NULL
            AND cancelled_at IS NULL AND delivered_at IS NULL AND last_error_code IS NOT NULL)
        OR (status = 'cancelled' AND claim_owner IS NULL AND claim_expires_at IS NULL
            AND cancelled_at IS NOT NULL AND delivered_at IS NULL)
    ),
    ADD CONSTRAINT effect_outbox_items_deadline_check CHECK (
        dispatch_deadline > available_at
    );

CREATE TABLE armi.creator_response_deliveries (
    creator_response_delivery_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(creator_response_delivery_id) = 7),
    effect_id uuid NOT NULL UNIQUE REFERENCES armi.effects(effect_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    payload_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    payload_bytes integer NOT NULL CHECK (payload_bytes BETWEEN 1 AND 65536),
    receipt_digest text NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    received_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1)
);

CREATE TABLE armi.effect_attempts (
    effect_attempt_id uuid PRIMARY KEY CHECK (uuid_extract_version(effect_attempt_id) = 7),
    effect_id uuid NOT NULL REFERENCES armi.effects(effect_id),
    attempt_no smallint NOT NULL CHECK (attempt_no BETWEEN 1 AND 2),
    adapter_binding text NOT NULL
        CHECK (adapter_binding = 'armi.creator-response-adapter.postgresql-inbox-v1'),
    request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    claim_token bigint NOT NULL CHECK (claim_token > 0),
    dispatch_state text NOT NULL CHECK (dispatch_state IN ('prepared', 'dispatching', 'settled')),
    result_status text CHECK (result_status IN ('succeeded', 'failed', 'unknown', 'cancelled')),
    error_code text CHECK (error_code IS NULL OR error_code ~ '^EFFECT-[A-Z0-9-]+$'),
    prepared_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    dispatched_at timestamptz(6),
    settled_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (effect_id, attempt_no),
    UNIQUE (effect_id, claim_token),
    CHECK (
        (dispatch_state = 'prepared' AND result_status IS NULL
            AND dispatched_at IS NULL AND settled_at IS NULL AND error_code IS NULL)
        OR (dispatch_state = 'dispatching' AND result_status IS NULL
            AND dispatched_at IS NOT NULL AND settled_at IS NULL AND error_code IS NULL)
        OR (dispatch_state = 'settled' AND result_status IS NOT NULL
            AND settled_at IS NOT NULL
            AND (dispatched_at IS NOT NULL
                OR (result_status IN ('failed', 'cancelled')
                    AND dispatched_at IS NULL)))
    ),
    CHECK ((result_status IN ('failed', 'unknown')) = (error_code IS NOT NULL))
);

CREATE TABLE armi.effect_observations (
    effect_observation_id uuid PRIMARY KEY CHECK (uuid_extract_version(effect_observation_id) = 7),
    effect_id uuid NOT NULL REFERENCES armi.effects(effect_id),
    effect_attempt_id uuid NOT NULL REFERENCES armi.effect_attempts(effect_attempt_id),
    observation_kind text NOT NULL CHECK (
        observation_kind IN ('receipt', 'query', 'rejection', 'ambiguous')
    ),
    reliability text NOT NULL CHECK (reliability IN ('reliable', 'inconclusive')),
    receiver_ref uuid,
    observation_digest text NOT NULL CHECK (observation_digest ~ '^sha256:[0-9a-f]{64}$'),
    observed_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (effect_attempt_id, observation_kind, observation_digest),
    CHECK ((observation_kind = 'receipt') = (receiver_ref IS NOT NULL)),
    CHECK (receiver_ref IS NULL OR uuid_extract_version(receiver_ref) = 7),
    CHECK ((observation_kind = 'ambiguous') = (reliability = 'inconclusive'))
);

ALTER TABLE armi.effects
    ADD COLUMN current_attempt_id uuid REFERENCES armi.effect_attempts(effect_attempt_id),
    ADD COLUMN current_observation_id uuid REFERENCES armi.effect_observations(effect_observation_id),
    ADD COLUMN settlement_digest text CHECK (
        settlement_digest IS NULL OR settlement_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    ADD COLUMN settled_at timestamptz(6),
    ADD CONSTRAINT effects_check CHECK (
        (status = 'registered' AND verification_status = 'not_started'
            AND current_attempt_id IS NULL AND current_observation_id IS NULL
            AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'dispatching' AND verification_status = 'pending'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NULL
            AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'completed' AND verification_status = 'verified'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'failed' AND verification_status = 'verified'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'unknown' AND verification_status = 'inconclusive'
            AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
            AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND verification_status = 'not_started'
            AND current_attempt_id IS NULL AND current_observation_id IS NULL
            AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NOT NULL)
    );

ALTER TABLE armi.creator_response_operations
    DROP CONSTRAINT creator_response_operations_current_status_check,
    DROP CONSTRAINT creator_response_operations_check,
    DROP CONSTRAINT creator_response_operations_effect_state_check,
    ADD CONSTRAINT creator_response_operations_current_status_check CHECK (
        current_status IN (
            'pending', 'accepted', 'effect_registered', 'effect_dispatching',
            'effect_completed', 'effect_failed', 'effect_unknown', 'effect_cancelled',
            'no_action', 'unauthorized', 'unavailable', 'failed'
        )
    ),
    ADD CONSTRAINT creator_response_operations_check CHECK (
        (current_status = 'pending' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NULL AND reason_code IS NULL AND completed_at IS NULL)
        OR (current_status = 'accepted' AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('effect_registered', 'effect_dispatching', 'effect_completed', 'effect_cancelled') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('effect_failed', 'effect_unknown') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NOT NULL AND completion_digest IS NOT NULL AND reason_code IS NOT NULL AND completed_at IS NOT NULL)
        OR (current_status = 'no_action' AND action_intent_id IS NULL AND formal_no_action_id IS NOT NULL AND admission_work_id IS NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NULL AND completed_at IS NOT NULL)
        OR (current_status IN ('unauthorized', 'unavailable', 'failed') AND action_intent_id IS NOT NULL AND formal_no_action_id IS NULL AND admission_work_id IS NOT NULL AND matched_grant_id IS NULL AND completion_digest IS NOT NULL AND reason_code IS NOT NULL AND completed_at IS NOT NULL)
    ),
    ADD CONSTRAINT creator_response_operations_effect_state_check CHECK (
        (current_status IN ('effect_registered', 'effect_dispatching', 'effect_completed', 'effect_failed', 'effect_unknown', 'effect_cancelled')
            AND current_policy_decision_id IS NOT NULL AND effect_id IS NOT NULL
            AND effect_registration_digest IS NOT NULL AND effect_registered_at IS NOT NULL)
        OR (current_status IN ('unauthorized', 'unavailable')
            AND current_policy_decision_id IS NOT NULL AND effect_id IS NULL
            AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
        OR (current_status NOT IN ('effect_registered', 'effect_dispatching', 'effect_completed', 'effect_failed', 'effect_unknown', 'effect_cancelled', 'unauthorized', 'unavailable')
            AND current_policy_decision_id IS NULL AND effect_id IS NULL
            AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_effect_attempt_count integer NOT NULL DEFAULT 0
        CHECK (resumable_effect_attempt_count >= 0),
    ADD COLUMN reliable_effect_observation_count integer NOT NULL DEFAULT 0
        CHECK (reliable_effect_observation_count >= 0),
    ADD COLUMN creator_response_delivery_count integer NOT NULL DEFAULT 0
        CHECK (creator_response_delivery_count >= 0);

REVOKE ALL ON TABLE armi.creator_response_deliveries, armi.effect_attempts, armi.effect_observations
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.creator_response_deliveries, armi.effect_attempts, armi.effect_observations
TO armi_runtime;
GRANT INSERT (creator_response_delivery_id, effect_id, interaction_scene_id,
              creator_party_id, payload_artifact_id, payload_digest,
              payload_bytes, receipt_digest, schema_version)
ON armi.creator_response_deliveries TO armi_runtime;
GRANT INSERT (effect_attempt_id, effect_id, attempt_no, adapter_binding,
              request_digest, claim_token, dispatch_state, schema_version)
ON armi.effect_attempts TO armi_runtime;
GRANT INSERT (effect_observation_id, effect_id, effect_attempt_id,
              observation_kind, reliability, receiver_ref,
              observation_digest, schema_version)
ON armi.effect_observations TO armi_runtime;
GRANT UPDATE (dispatch_state, result_status, error_code, dispatched_at, settled_at)
ON armi.effect_attempts TO armi_runtime;
GRANT UPDATE (status, verification_status, current_attempt_id, current_observation_id,
              settlement_digest, settled_at)
ON armi.effects TO armi_runtime;
GRANT UPDATE (status, available_at, claim_owner, claim_expires_at, claim_token,
              attempt_count, delivered_at, last_error_code)
ON armi.effect_outbox_items TO armi_runtime;
GRANT UPDATE (current_status, reason_code, completed_at)
ON armi.creator_response_operations TO armi_runtime;
GRANT INSERT (timeline_item_id, scene_id, source_kind, source_ref, source_event_no,
              result_status, occurred_at, schema_version)
ON armi.scene_timeline_items TO armi_runtime;
GRANT INSERT (resumable_effect_attempt_count, reliable_effect_observation_count,
              creator_response_delivery_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_effect_attempt_count, reliable_effect_observation_count,
              creator_response_delivery_count)
ON armi.runtime_recovery_runs TO armi_runtime;
