CREATE TABLE armi.durable_work (
    work_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(work_id) = 7),
    work_kind text NOT NULL
        CHECK (work_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    owner_kind text NOT NULL
        CHECK (owner_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    owner_ref uuid NOT NULL
        CHECK (uuid_extract_version(owner_ref) = 7),
    subject_id uuid
        CHECK (
            subject_id IS NULL
            OR uuid_extract_version(subject_id) = 7
        ),
    idempotency_key text NOT NULL
        CHECK (
            length(idempotency_key) BETWEEN 1 AND 128
            AND idempotency_key ~ '^[A-Za-z0-9._:-]+$'
        ),
    payload_kind text
        CHECK (
            payload_kind IS NULL
            OR payload_kind ~ '^[a-z][a-z0-9._-]{0,63}$'
        ),
    payload_ref uuid
        CHECK (
            payload_ref IS NULL
            OR uuid_extract_version(payload_ref) = 7
        ),
    payload_digest text NOT NULL
        CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    priority smallint NOT NULL DEFAULT 0
        CHECK (priority BETWEEN 0 AND 100),
    not_before timestamptz(6) NOT NULL,
    deadline_at timestamptz(6) NOT NULL,
    status text NOT NULL DEFAULT 'ready'
        CHECK (
            status IN (
                'ready',
                'leased',
                'completed',
                'failed',
                'cancelled'
            )
        ),
    max_attempts smallint NOT NULL
        CHECK (max_attempts BETWEEN 1 AND 100),
    attempt_count smallint NOT NULL DEFAULT 0
        CHECK (attempt_count BETWEEN 0 AND max_attempts),
    current_attempt_id uuid
        CHECK (
            current_attempt_id IS NULL
            OR uuid_extract_version(current_attempt_id) = 7
        ),
    lease_owner uuid
        CHECK (
            lease_owner IS NULL
            OR uuid_extract_version(lease_owner) = 7
        ),
    lease_expires_at timestamptz(6),
    lease_token bigint NOT NULL DEFAULT 0
        CHECK (lease_token >= 0),
    result_kind text
        CHECK (
            result_kind IS NULL
            OR result_kind ~ '^[a-z][a-z0-9._-]{0,63}$'
        ),
    result_ref uuid
        CHECK (
            result_ref IS NULL
            OR uuid_extract_version(result_ref) = 7
        ),
    last_error_code text
        CHECK (
            last_error_code IS NULL
            OR last_error_code ~ '^[A-Z][A-Z0-9-]{0,127}$'
        ),
    trace_id text NOT NULL
        CHECK (
            trace_id ~ '^[0-9a-f]{32}$'
            AND trace_id <> repeat('0', 32)
        ),
    schema_version smallint NOT NULL DEFAULT 1
        CHECK (schema_version = 1),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (owner_kind, owner_ref, work_kind, idempotency_key),
    CHECK ((payload_kind IS NULL) = (payload_ref IS NULL)),
    CHECK ((result_kind IS NULL) = (result_ref IS NULL)),
    CHECK (deadline_at > not_before),
    CHECK (
        (
            status = 'leased'
            AND current_attempt_id IS NOT NULL
            AND lease_owner IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND lease_token > 0
            AND attempt_count > 0
        )
        OR (
            status <> 'leased'
            AND current_attempt_id IS NULL
            AND lease_owner IS NULL
            AND lease_expires_at IS NULL
        )
    ),
    CHECK (
        (status = 'completed' AND result_ref IS NOT NULL)
        OR (status <> 'completed' AND result_ref IS NULL)
    )
);

CREATE INDEX durable_work_claim_idx
    ON armi.durable_work (
        status,
        not_before,
        priority DESC,
        work_id
    )
    WHERE status IN ('ready', 'leased');

CREATE INDEX durable_work_expired_lease_idx
    ON armi.durable_work (lease_expires_at, work_id)
    WHERE status = 'leased';

CREATE TABLE armi.outbox_items (
    outbox_item_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(outbox_item_id) = 7),
    work_id uuid NOT NULL
        REFERENCES armi.durable_work(work_id) ON DELETE RESTRICT,
    message_kind text NOT NULL
        CHECK (message_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    payload_digest text NOT NULL
        CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'claimed', 'delivered', 'dead')),
    available_at timestamptz(6) NOT NULL,
    claimed_by uuid
        CHECK (
            claimed_by IS NULL
            OR uuid_extract_version(claimed_by) = 7
        ),
    claim_expires_at timestamptz(6),
    claim_token bigint NOT NULL DEFAULT 0
        CHECK (claim_token >= 0),
    attempt_count smallint NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    max_attempts smallint NOT NULL
        CHECK (max_attempts BETWEEN 1 AND 100),
    last_error_code text
        CHECK (
            last_error_code IS NULL
            OR last_error_code ~ '^[A-Z][A-Z0-9-]{0,127}$'
        ),
    delivered_at timestamptz(6),
    trace_id text NOT NULL
        CHECK (
            trace_id ~ '^[0-9a-f]{32}$'
            AND trace_id <> repeat('0', 32)
        ),
    schema_version smallint NOT NULL DEFAULT 1
        CHECK (schema_version = 1),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (work_id, message_kind),
    CHECK (attempt_count <= max_attempts),
    CHECK (
        (
            status = 'claimed'
            AND claimed_by IS NOT NULL
            AND claim_expires_at IS NOT NULL
            AND claim_token > 0
            AND attempt_count > 0
        )
        OR (
            status <> 'claimed'
            AND claimed_by IS NULL
            AND claim_expires_at IS NULL
        )
    ),
    CHECK (
        (status = 'delivered' AND delivered_at IS NOT NULL)
        OR (status <> 'delivered' AND delivered_at IS NULL)
    )
);

CREATE INDEX outbox_items_claim_idx
    ON armi.outbox_items (
        status,
        available_at,
        outbox_item_id
    )
    WHERE status IN ('ready', 'claimed');

REVOKE ALL ON TABLE armi.durable_work, armi.outbox_items
    FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.durable_work, armi.outbox_items TO armi_runtime;

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
) ON armi.durable_work TO armi_runtime;

GRANT UPDATE (
    status,
    not_before,
    attempt_count,
    current_attempt_id,
    lease_owner,
    lease_expires_at,
    lease_token,
    result_kind,
    result_ref,
    last_error_code,
    updated_at
) ON armi.durable_work TO armi_runtime;

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
) ON armi.outbox_items TO armi_runtime;

GRANT UPDATE (
    status,
    available_at,
    claimed_by,
    claim_expires_at,
    claim_token,
    attempt_count,
    last_error_code,
    delivered_at,
    updated_at
) ON armi.outbox_items TO armi_runtime;
