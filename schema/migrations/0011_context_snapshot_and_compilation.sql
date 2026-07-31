ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_current_disposition_check,
    ADD COLUMN selected_at timestamptz(6),
    ADD CONSTRAINT opportunities_current_disposition_check
    CHECK (current_disposition IN ('open', 'selected')),
    ADD CONSTRAINT opportunities_selection_state_check
    CHECK (
        (current_disposition = 'open' AND selected_at IS NULL)
        OR (current_disposition = 'selected' AND selected_at IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_context_identity_unique
    UNIQUE (opportunity_id, subject_id, scene_id, creator_party_id);

CREATE TABLE armi.cognitive_episodes (
    cognitive_episode_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(cognitive_episode_id) = 7),
    opportunity_id uuid NOT NULL UNIQUE,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    purpose text NOT NULL CHECK (purpose = 'consider_creator_input'),
    status text NOT NULL
        CHECK (status IN ('preparing', 'prepared', 'failed', 'cancelled')),
    base_subject_version bigint NOT NULL CHECK (base_subject_version >= 0),
    base_state_epoch bigint NOT NULL CHECK (base_state_epoch >= 0),
    bundle_activation_id uuid NOT NULL
        REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    policy_digest text NOT NULL
        CHECK (policy_digest ~ '^sha256:[0-9a-f]{64}$'),
    mechanism_identity text NOT NULL
        CHECK (
            mechanism_identity = 'armi.context-compiler.deterministic-v1'
        ),
    mechanism_config_digest text NOT NULL
        CHECK (mechanism_config_digest ~ '^sha256:[0-9a-f]{64}$'),
    context_manifest_artifact_id uuid
        REFERENCES armi.artifacts(artifact_id),
    compiled_context_artifact_id uuid
        REFERENCES armi.artifacts(artifact_id),
    context_digest text
        CHECK (
            context_digest IS NULL
            OR context_digest ~ '^sha256:[0-9a-f]{64}$'
        ),
    failure_code text
        CHECK (
            failure_code IS NULL
            OR failure_code ~ '^CTX-[A-Z0-9-]+$'
        ),
    trace_id text NOT NULL
        CHECK (
            trace_id ~ '^[0-9a-f]{32}$'
            AND trace_id <> repeat('0', 32)
        ),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    prepared_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (
        opportunity_id,
        subject_id,
        scene_id,
        creator_party_id
    ) REFERENCES armi.opportunities (
        opportunity_id,
        subject_id,
        scene_id,
        creator_party_id
    ),
    CHECK (
        (
            status = 'preparing'
            AND context_manifest_artifact_id IS NULL
            AND compiled_context_artifact_id IS NULL
            AND context_digest IS NULL
            AND failure_code IS NULL
            AND prepared_at IS NULL
        )
        OR (
            status = 'prepared'
            AND context_manifest_artifact_id IS NOT NULL
            AND compiled_context_artifact_id IS NOT NULL
            AND context_digest IS NOT NULL
            AND failure_code IS NULL
            AND prepared_at IS NOT NULL
        )
        OR (
            status IN ('failed', 'cancelled')
            AND context_manifest_artifact_id IS NULL
            AND compiled_context_artifact_id IS NULL
            AND context_digest IS NULL
            AND failure_code IS NOT NULL
            AND prepared_at IS NULL
        )
    )
);

CREATE INDEX cognitive_episodes_status_idx
    ON armi.cognitive_episodes (status, created_at, cognitive_episode_id);

CREATE TABLE armi.cognitive_context_items (
    context_item_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(context_item_id) = 7),
    cognitive_episode_id uuid NOT NULL
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    ordinal smallint NOT NULL CHECK (ordinal > 0),
    section text NOT NULL
        CHECK (
            section IN (
                'runtime_truth',
                'purpose',
                'self',
                'mind',
                'life_mode',
                'scene',
                'relationship',
                'memory',
                'evidence',
                'capability',
                'prompt'
            )
        ),
    item_kind text NOT NULL
        CHECK (item_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    source_kind text NOT NULL
        CHECK (source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    source_ref uuid CHECK (
        source_ref IS NULL OR uuid_extract_version(source_ref) = 7
    ),
    source_version bigint CHECK (source_version IS NULL OR source_version >= 0),
    source_digest text CHECK (
        source_digest IS NULL OR source_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    trust_class text NOT NULL
        CHECK (
            trust_class IN (
                'runtime_authority',
                'subjective_state',
                'external_claim',
                'policy'
            )
        ),
    privacy_scope text NOT NULL
        CHECK (privacy_scope IN ('internal', 'private', 'restricted')),
    disposition text NOT NULL
        CHECK (
            disposition IN (
                'included',
                'excluded_policy',
                'excluded_budget',
                'unavailable',
                'read_failed'
            )
        ),
    reason_code text CHECK (
        reason_code IS NULL OR reason_code ~ '^CTX-[A-Z0-9-]+$'
    ),
    content_bytes integer NOT NULL CHECK (content_bytes >= 0),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (cognitive_episode_id, ordinal),
    CHECK (
        (source_ref IS NULL AND source_version IS NULL AND source_digest IS NULL)
        OR (
            source_ref IS NOT NULL
            AND source_version IS NOT NULL
            AND source_digest IS NOT NULL
        )
    ),
    CHECK (
        (disposition IN ('included', 'excluded_policy') AND reason_code IS NULL)
        OR (
            disposition IN (
                'excluded_budget',
                'unavailable',
                'read_failed'
            )
            AND reason_code IS NOT NULL
        )
    )
);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_cognitive_episode_count integer NOT NULL DEFAULT 0
        CHECK (resumable_cognitive_episode_count >= 0);

REVOKE ALL ON TABLE
    armi.cognitive_episodes,
    armi.cognitive_context_items
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.cognitive_episodes,
    armi.cognitive_context_items
TO armi_runtime;

GRANT UPDATE (current_disposition, selected_at)
ON armi.opportunities TO armi_runtime;

GRANT INSERT (
    cognitive_episode_id,
    opportunity_id,
    subject_id,
    scene_id,
    creator_party_id,
    purpose,
    status,
    base_subject_version,
    base_state_epoch,
    bundle_activation_id,
    policy_digest,
    mechanism_identity,
    mechanism_config_digest,
    trace_id,
    schema_version
) ON armi.cognitive_episodes TO armi_runtime;

GRANT UPDATE (
    status,
    context_manifest_artifact_id,
    compiled_context_artifact_id,
    context_digest,
    failure_code,
    prepared_at
) ON armi.cognitive_episodes TO armi_runtime;

GRANT INSERT (
    context_item_id,
    cognitive_episode_id,
    ordinal,
    section,
    item_kind,
    source_kind,
    source_ref,
    source_version,
    source_digest,
    trust_class,
    privacy_scope,
    disposition,
    reason_code,
    content_bytes,
    schema_version
) ON armi.cognitive_context_items TO armi_runtime;

GRANT INSERT (resumable_cognitive_episode_count)
ON armi.runtime_recovery_runs TO armi_runtime;

GRANT UPDATE (resumable_cognitive_episode_count)
ON armi.runtime_recovery_runs TO armi_runtime;
