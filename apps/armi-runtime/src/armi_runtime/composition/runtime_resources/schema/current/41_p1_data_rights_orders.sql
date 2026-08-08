CREATE TABLE armi.deletion_orders (
    deletion_order_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(deletion_order_id) = 7),
    requester_party_id uuid NOT NULL,
    requester_kind text NOT NULL
        CHECK (requester_kind IN ('creator', 'other_human')),
    order_kind text NOT NULL
        CHECK (order_kind IN ('stop_contact', 'stop_use', 'delete_related')),
    scope_kind text NOT NULL
        CHECK (scope_kind IN ('party_contact', 'party_local_data')),
    scope_party_id uuid NOT NULL,
    reason_code text NOT NULL
        CHECK (reason_code = 'requester_exercised_local_right'),
    status text NOT NULL CHECK (status = 'effective'),
    execution_status text NOT NULL
        CHECK (execution_status IN ('not_required', 'pending')),
    idempotency_key text NOT NULL
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    request_digest text NOT NULL
        CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    effective_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (requester_party_id, requester_kind)
        REFERENCES armi.parties(party_id, party_kind),
    FOREIGN KEY (scope_party_id, requester_kind)
        REFERENCES armi.parties(party_id, party_kind),
    UNIQUE (requester_party_id, idempotency_key),
    UNIQUE (requester_party_id, order_kind),
    CHECK (requester_party_id = scope_party_id),
    CHECK (
        (order_kind = 'stop_contact' AND scope_kind = 'party_contact')
        OR (order_kind IN ('stop_use', 'delete_related')
            AND scope_kind = 'party_local_data')
    ),
    CHECK (
        (order_kind = 'delete_related' AND execution_status = 'pending')
        OR (order_kind <> 'delete_related'
            AND execution_status = 'not_required')
    ),
    CHECK (completed_at IS NULL)
);

CREATE INDEX deletion_orders_effective_party_idx
    ON armi.deletion_orders (requester_party_id, order_kind)
    WHERE status = 'effective';

REVOKE ALL ON TABLE armi.deletion_orders
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT, INSERT ON TABLE armi.deletion_orders TO armi_runtime;
