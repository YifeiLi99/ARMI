CREATE TABLE armi.artifacts (
    artifact_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(artifact_id) = 7),
    content_digest text NOT NULL UNIQUE
        CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    media_type text NOT NULL
        CHECK (
            length(media_type) <= 127
            AND media_type ~
                '^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$'
        ),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    storage_locator text NOT NULL UNIQUE,
    logical_kind text NOT NULL
        CHECK (logical_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    producer_kind text NOT NULL
        CHECK (producer_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    producer_trace_id text NOT NULL
        CHECK (
            producer_trace_id ~ '^[0-9a-f]{32}$'
            AND producer_trace_id <> repeat('0', 32)
        ),
    privacy_scope text NOT NULL
        CHECK (
            privacy_scope IN (
                'creator_visible',
                'private',
                'shared',
                'restricted'
            )
        ),
    integrity_status text NOT NULL DEFAULT 'verified'
        CHECK (integrity_status IN ('verified', 'missing', 'corrupt')),
    retention_status text NOT NULL DEFAULT 'retained'
        CHECK (retention_status IN ('retained', 'deleted')),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (retention_status = 'retained' AND deleted_at IS NULL)
        OR (retention_status = 'deleted' AND deleted_at IS NOT NULL)
    ),
    CHECK (
        storage_locator =
            'objects/sha256/'
            || substring(content_digest FROM 8 FOR 2)
            || '/'
            || substring(content_digest FROM 10 FOR 2)
            || '/'
            || substring(content_digest FROM 8)
    )
);

REVOKE ALL ON TABLE armi.artifacts
    FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.artifacts TO armi_runtime;

GRANT INSERT (
    artifact_id,
    content_digest,
    media_type,
    byte_size,
    storage_locator,
    logical_kind,
    producer_kind,
    producer_trace_id,
    privacy_scope,
    schema_version
) ON armi.artifacts TO armi_runtime;

GRANT UPDATE (integrity_status) ON armi.artifacts TO armi_runtime;
GRANT UPDATE (retention_status, deleted_at) ON armi.artifacts TO armi_runtime;
