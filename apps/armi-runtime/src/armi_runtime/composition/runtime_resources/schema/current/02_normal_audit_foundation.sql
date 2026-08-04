CREATE TABLE armi.audit_events (
    audit_event_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(audit_event_id) = 7),
    actor_kind text NOT NULL
        CHECK (actor_kind ~ '^[a-z][a-z0-9._-]{0,127}$'),
    actor_ref uuid NOT NULL
        CHECK (uuid_extract_version(actor_ref) = 7),
    purpose text NOT NULL
        CHECK (purpose ~ '^[a-z][a-z0-9._-]{0,127}$'),
    operation text NOT NULL
        CHECK (operation ~ '^[a-z][a-z0-9._-]{0,127}$'),
    target_kind text NOT NULL
        CHECK (target_kind ~ '^[a-z][a-z0-9._-]{0,127}$'),
    target_ref uuid NOT NULL
        CHECK (uuid_extract_version(target_ref) = 7),
    result_status text NOT NULL
        CHECK (
            result_status IN (
                'accepted',
                'applied',
                'waiting',
                'rejected',
                'unavailable',
                'failed',
                'unknown',
                'completed'
            )
        ),
    trace_id text NOT NULL
        CHECK (
            trace_id ~ '^[0-9a-f]{32}$'
            AND trace_id <> repeat('0', 32)
        ),
    sensitivity text NOT NULL
        CHECK (sensitivity IN ('internal', 'private', 'restricted')),
    subject_id uuid
        CHECK (
            subject_id IS NULL
            OR uuid_extract_version(subject_id) = 7
        ),
    request_kind text
        CHECK (
            request_kind IS NULL
            OR request_kind ~ '^[a-z][a-z0-9._-]{0,127}$'
        ),
    request_ref uuid
        CHECK (
            request_ref IS NULL
            OR uuid_extract_version(request_ref) = 7
        ),
    before_version bigint CHECK (before_version >= 0),
    after_version bigint CHECK (after_version >= 0),
    request_digest text
        CHECK (
            request_digest IS NULL
            OR request_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    response_digest text
        CHECK (
            response_digest IS NULL
            OR response_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    artifact_digest text
        CHECK (
            artifact_digest IS NULL
            OR artifact_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    details_digest text
        CHECK (
            details_digest IS NULL
            OR details_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    policy_ref uuid
        CHECK (
            policy_ref IS NULL
            OR uuid_extract_version(policy_ref) = 7
        ),
    grant_ref uuid
        CHECK (
            grant_ref IS NULL
            OR uuid_extract_version(grant_ref) = 7
        ),
    bundle_digest text
        CHECK (
            bundle_digest IS NULL
            OR bundle_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    error_category text
        CHECK (
            error_category IS NULL
            OR error_category IN (
                'input',
                'auth',
                'scope',
                'state',
                'conflict',
                'idempotency',
                'policy',
                'capability',
                'dependency',
                'effect',
                'integrity',
                'admin',
                'internal'
            )
        ),
    schema_version smallint NOT NULL DEFAULT 1
        CHECK (schema_version = 1),
    occurred_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    CHECK ((request_kind IS NULL) = (request_ref IS NULL)),
    CHECK ((before_version IS NULL) = (after_version IS NULL)),
    CHECK (
        before_version IS NULL
        OR after_version > before_version
    )
);

CREATE INDEX audit_events_target_idx
    ON armi.audit_events (
        target_kind,
        target_ref,
        occurred_at,
        audit_event_id
    );

CREATE INDEX audit_events_subject_idx
    ON armi.audit_events (subject_id, occurred_at, audit_event_id)
    WHERE subject_id IS NOT NULL;

CREATE INDEX audit_events_request_idx
    ON armi.audit_events (
        request_kind,
        request_ref,
        occurred_at,
        audit_event_id
    )
    WHERE request_ref IS NOT NULL;

CREATE INDEX audit_events_trace_idx
    ON armi.audit_events (trace_id, occurred_at, audit_event_id);

REVOKE ALL ON TABLE armi.audit_events
    FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.audit_events TO armi_runtime;

GRANT INSERT (
    audit_event_id,
    actor_kind,
    actor_ref,
    purpose,
    operation,
    target_kind,
    target_ref,
    result_status,
    trace_id,
    sensitivity,
    subject_id,
    request_kind,
    request_ref,
    before_version,
    after_version,
    request_digest,
    response_digest,
    artifact_digest,
    details_digest,
    policy_ref,
    grant_ref,
    bundle_digest,
    error_category,
    schema_version
) ON armi.audit_events TO armi_runtime;
