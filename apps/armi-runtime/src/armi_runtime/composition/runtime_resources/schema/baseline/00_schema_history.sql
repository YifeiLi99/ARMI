CREATE TABLE armi.schema_migrations (
    sequence_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    migration_id text PRIMARY KEY
        CHECK (migration_id ~ '^[0-9]{4}_[a-z0-9_]+$'),
    migration_kind text NOT NULL
        CHECK (migration_kind IN ('baseline', 'migration')),
    checksum text NOT NULL
        CHECK (checksum ~ '^sha256:[0-9a-f]{64}$'),
    applied_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (migration_kind = 'baseline' AND migration_id = '0001_baseline')
        OR (migration_kind = 'migration' AND migration_id <> '0001_baseline')
    )
);

CREATE UNIQUE INDEX schema_migrations_one_baseline_idx
    ON armi.schema_migrations (migration_kind)
    WHERE migration_kind = 'baseline';

REVOKE ALL ON TABLE armi.schema_migrations
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.schema_migrations
TO armi_runtime, armi_admin, armi_migrator;
