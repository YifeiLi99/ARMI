CREATE TABLE armi.deletion_items (
    deletion_item_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(deletion_item_id) = 7),
    deletion_order_id uuid NOT NULL
        REFERENCES armi.deletion_orders(deletion_order_id),
    target_kind text NOT NULL CHECK (target_kind IN (
        'interaction', 'evidence', 'experience', 'memory', 'relationship',
        'scene', 'artifact', 'effect'
    )),
    target_ref uuid NOT NULL CHECK (uuid_extract_version(target_ref) = 7),
    required_action text NOT NULL CHECK (
        required_action IN ('delete', 'tombstone', 'retain')
    ),
    result_status text NOT NULL CHECK (
        result_status IN ('pending', 'completed', 'partial', 'too_late', 'unknown')
    ),
    remaining_location text CHECK (
        remaining_location IS NULL OR remaining_location IN (
            'shared_local_reference', 'objective_history', 'local_artifact_store'
        )
    ),
    execution_digest text CHECK (
        execution_digest IS NULL OR execution_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (deletion_order_id, target_kind, target_ref),
    CHECK (
        (result_status = 'pending' AND completed_at IS NULL
            AND execution_digest IS NULL)
        OR (result_status <> 'pending' AND completed_at IS NOT NULL
            AND execution_digest IS NOT NULL)
    )
);

CREATE INDEX deletion_items_order_status_idx
    ON armi.deletion_items (deletion_order_id, result_status, target_kind);
CREATE INDEX deletion_items_active_target_idx
    ON armi.deletion_items (target_kind, target_ref)
    WHERE result_status IN ('completed', 'partial');

REVOKE ALL ON TABLE armi.deletion_items
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT, INSERT ON TABLE armi.deletion_items TO armi_runtime;
GRANT UPDATE (
    result_status, remaining_location, execution_digest, completed_at
) ON armi.deletion_items TO armi_runtime;
GRANT UPDATE (state_epoch) ON armi.subjects TO armi_runtime;
