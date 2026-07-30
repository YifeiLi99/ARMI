CREATE TABLE armi.runtime_recovery_runs (
    recovery_run_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(recovery_run_id) = 7),
    runtime_instance_id uuid NOT NULL UNIQUE
        REFERENCES armi.runtime_instances(runtime_instance_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL
        REFERENCES armi.life_generations(life_generation_id),
    bundle_activation_id uuid NOT NULL
        REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    fence_token bigint NOT NULL CHECK (fence_token > 0),
    status text NOT NULL
        CHECK (status IN ('running', 'safe', 'blocked', 'abandoned')),
    started_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz(6),
    requeued_work_count integer NOT NULL DEFAULT 0
        CHECK (requeued_work_count >= 0),
    terminal_work_count integer NOT NULL DEFAULT 0
        CHECK (terminal_work_count >= 0),
    requeued_outbox_count integer NOT NULL DEFAULT 0
        CHECK (requeued_outbox_count >= 0),
    dead_outbox_count integer NOT NULL DEFAULT 0
        CHECK (dead_outbox_count >= 0),
    resumable_work_count integer NOT NULL DEFAULT 0
        CHECK (resumable_work_count >= 0),
    resumable_outbox_count integer NOT NULL DEFAULT 0
        CHECK (resumable_outbox_count >= 0),
    critical_artifact_count integer NOT NULL DEFAULT 0
        CHECK (critical_artifact_count >= 0),
    blocker_count integer NOT NULL DEFAULT 0
        CHECK (blocker_count >= 0),
    summary_digest text
        CHECK (
            summary_digest IS NULL
            OR summary_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    schema_version smallint NOT NULL DEFAULT 1
        CHECK (schema_version = 1),
    CHECK (
        (
            status = 'running'
            AND completed_at IS NULL
            AND summary_digest IS NULL
        )
        OR (
            status IN ('safe', 'blocked', 'abandoned')
            AND completed_at IS NOT NULL
            AND summary_digest IS NOT NULL
        )
    ),
    CHECK (status <> 'safe' OR blocker_count = 0),
    CHECK (status <> 'blocked' OR blocker_count > 0)
);

CREATE INDEX runtime_recovery_runs_status_idx
    ON armi.runtime_recovery_runs (status, started_at, recovery_run_id);

REVOKE ALL ON TABLE armi.runtime_recovery_runs
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.runtime_recovery_runs TO armi_runtime;

GRANT INSERT (
    recovery_run_id,
    runtime_instance_id,
    subject_id,
    life_generation_id,
    bundle_activation_id,
    fence_token,
    status,
    requeued_work_count,
    terminal_work_count,
    requeued_outbox_count,
    dead_outbox_count,
    resumable_work_count,
    resumable_outbox_count,
    critical_artifact_count,
    blocker_count,
    schema_version
) ON armi.runtime_recovery_runs TO armi_runtime;

GRANT UPDATE (
    status,
    completed_at,
    requeued_work_count,
    terminal_work_count,
    requeued_outbox_count,
    dead_outbox_count,
    resumable_work_count,
    resumable_outbox_count,
    critical_artifact_count,
    blocker_count,
    summary_digest
) ON armi.runtime_recovery_runs TO armi_runtime;
