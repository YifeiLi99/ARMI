CREATE TABLE armi.creator_exports (
    creator_export_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(creator_export_id) = 7),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    directory_name text NOT NULL
        CHECK (
            directory_name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
            AND directory_name NOT IN ('.', '..')
        ),
    idempotency_key text NOT NULL
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    destination_path text NOT NULL,
    manifest_digest text CHECK (
        manifest_digest IS NULL OR manifest_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    table_count integer NOT NULL DEFAULT 0 CHECK (table_count >= 0),
    row_count bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    artifact_count bigint NOT NULL DEFAULT 0 CHECK (artifact_count >= 0),
    missing_artifacts jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(missing_artifacts) = 'array'),
    error_code text,
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (creator_party_id, idempotency_key),
    UNIQUE (creator_party_id, directory_name),
    CHECK (
        (status = 'running' AND completed_at IS NULL)
        OR (status <> 'running' AND completed_at IS NOT NULL)
    )
);

REVOKE ALL ON TABLE armi.creator_exports
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT, INSERT ON TABLE armi.creator_exports TO armi_runtime;
GRANT UPDATE (
    status, manifest_digest, table_count, row_count, artifact_count,
    missing_artifacts, error_code, completed_at
) ON TABLE armi.creator_exports TO armi_runtime;
