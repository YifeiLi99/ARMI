CREATE SCHEMA armi;

CREATE TABLE armi.schema_migrations (
    version bigint PRIMARY KEY CHECK (version > 0),
    name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{0,63}$'),
    sha256 text NOT NULL CHECK (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    applied_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    application_version text NOT NULL
);
