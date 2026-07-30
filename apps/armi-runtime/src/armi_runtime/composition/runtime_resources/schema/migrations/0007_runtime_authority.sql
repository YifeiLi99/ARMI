CREATE TABLE armi.runtime_instances (
    runtime_instance_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(runtime_instance_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL
        REFERENCES armi.life_generations(life_generation_id),
    bundle_activation_id uuid NOT NULL
        REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    fence_token bigint NOT NULL CHECK (fence_token > 0),
    status text NOT NULL CHECK (status IN ('active', 'fenced', 'stopped')),
    started_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    last_heartbeat_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    lease_expires_at timestamptz(6) NOT NULL,
    stopped_at timestamptz(6),
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (life_generation_id, fence_token),
    CHECK (lease_expires_at > last_heartbeat_at),
    CHECK (
        (status = 'active' AND stopped_at IS NULL)
        OR (status IN ('fenced', 'stopped') AND stopped_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX runtime_instances_one_active_generation_idx
    ON armi.runtime_instances (life_generation_id)
    WHERE status = 'active';

REVOKE ALL ON TABLE armi.runtime_instances
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.runtime_instances TO armi_runtime;

GRANT INSERT (
    runtime_instance_id,
    subject_id,
    life_generation_id,
    bundle_activation_id,
    fence_token,
    status,
    lease_expires_at,
    schema_version
) ON armi.runtime_instances TO armi_runtime;

GRANT UPDATE (
    status,
    last_heartbeat_at,
    lease_expires_at,
    stopped_at
) ON armi.runtime_instances TO armi_runtime;
