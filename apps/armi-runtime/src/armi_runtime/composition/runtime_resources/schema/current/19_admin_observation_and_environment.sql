CREATE TABLE armi.deployment_environments (
    singleton_key boolean PRIMARY KEY DEFAULT true CHECK (singleton_key),
    environment_id uuid NOT NULL UNIQUE
        CHECK (uuid_extract_version(environment_id) = 7),
    environment_kind text NOT NULL CHECK (
        environment_kind IN (
            'development', 'system_test', 'acceptance',
            'active', 'restore_quarantine'
        )
    ),
    incarnation bigint NOT NULL CHECK (incarnation > 0),
    resettable boolean NOT NULL,
    test_controls_enabled boolean NOT NULL,
    bundle_digest text NOT NULL CHECK (bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
    config_digest text NOT NULL CHECK (config_digest ~ '^sha256:[0-9a-f]{64}$'),
    template_digest text NOT NULL CHECK (template_digest ~ '^sha256:[0-9a-f]{64}$'),
    data_root_identity_digest text NOT NULL
        CHECK (data_root_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
    database_identity_digest text NOT NULL
        CHECK (database_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
    registered_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK (
        (environment_kind IN ('development', 'system_test', 'acceptance'))
        OR (NOT resettable AND NOT test_controls_enabled)
    ),
    CHECK (
        NOT test_controls_enabled
        OR environment_kind IN ('system_test', 'acceptance')
    )
);

REVOKE ALL ON TABLE armi.deployment_environments
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.deployment_environments TO armi_runtime, armi_admin;
GRANT INSERT (
    singleton_key, environment_id, environment_kind, incarnation,
    resettable, test_controls_enabled, bundle_digest, config_digest,
    template_digest, data_root_identity_digest, database_identity_digest,
    schema_version
) ON armi.deployment_environments TO armi_admin;

GRANT SELECT ON ALL TABLES IN SCHEMA armi TO armi_admin;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON ALL TABLES IN SCHEMA armi FROM armi_admin;
GRANT INSERT (
    singleton_key, environment_id, environment_kind, incarnation,
    resettable, test_controls_enabled, bundle_digest, config_digest,
    template_digest, data_root_identity_digest, database_identity_digest,
    schema_version
) ON armi.deployment_environments TO armi_admin;
