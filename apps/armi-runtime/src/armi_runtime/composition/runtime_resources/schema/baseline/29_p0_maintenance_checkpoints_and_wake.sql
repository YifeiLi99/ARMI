ALTER TABLE armi.maintenance_sessions
    ADD COLUMN wake_request_id uuid UNIQUE
        CHECK (wake_request_id IS NULL OR uuid_extract_version(wake_request_id) = 7),
    ADD COLUMN wake_requested_at timestamptz(6),
    ADD COLUMN quiet_until timestamptz(6),
    ADD CONSTRAINT maintenance_sessions_wake_request_shape CHECK (
        (wake_request_id IS NULL) = (wake_requested_at IS NULL)
    ),
    ADD CONSTRAINT maintenance_sessions_quiet_window CHECK (
        quiet_until IS NULL OR quiet_until >= started_at
    );

GRANT UPDATE (
    current_revision_id, head_version, finished_at,
    wake_request_id, wake_requested_at, quiet_until
) ON armi.maintenance_sessions TO armi_runtime;
