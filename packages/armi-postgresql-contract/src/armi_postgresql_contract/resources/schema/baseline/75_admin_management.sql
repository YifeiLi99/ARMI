-- Durable receipts for explicit administrator changes. These are not cognition.
CREATE TABLE armi.admin_data_changes (
    admin_change_id uuid PRIMARY KEY,
    environment_id uuid NOT NULL,
    environment_incarnation bigint NOT NULL,
    operator_id text NOT NULL,
    operation_name text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    execution_mode text NOT NULL,
    reason text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT admin_data_changes_id_check CHECK (uuid_extract_version(admin_change_id) = 7),
    CONSTRAINT admin_data_changes_environment_check CHECK (uuid_extract_version(environment_id) = 7 AND environment_incarnation > 0),
    CONSTRAINT admin_data_changes_operator_check CHECK (length(operator_id) BETWEEN 1 AND 128),
    CONSTRAINT admin_data_changes_operation_check CHECK (operation_name ~ '^[a-z][a-z0-9_]{0,63}$'),
    CONSTRAINT admin_data_changes_key_check CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
    CONSTRAINT admin_data_changes_digest_check CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT admin_data_changes_mode_check CHECK (execution_mode IN ('maintenance', 'online')),
    CONSTRAINT admin_data_changes_reason_check CHECK (length(reason) BETWEEN 1 AND 1024),
    CONSTRAINT admin_data_changes_result_check CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT admin_data_changes_invocation_key UNIQUE (environment_id, environment_incarnation, operator_id, operation_name, idempotency_key)
);
