ALTER TABLE armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_input_identity_unique
    UNIQUE (scene_id, subject_id, primary_party_id);

CREATE TABLE armi.creator_input_interactions (
    creator_interaction_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(creator_interaction_id) = 7),
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    purpose text NOT NULL CHECK (purpose = 'creator_message'),
    idempotency_key text NOT NULL
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    request_digest text NOT NULL
        CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    content_digest text NOT NULL
        CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    received_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (creator_party_id, scene_id, purpose, idempotency_key),
    UNIQUE (
        creator_interaction_id,
        subject_id,
        scene_id,
        creator_party_id
    ),
    FOREIGN KEY (
        scene_id,
        subject_id,
        creator_party_id
    ) REFERENCES armi.interaction_scenes (
        scene_id,
        subject_id,
        primary_party_id
    )
);

CREATE TABLE armi.external_evidence (
    evidence_id uuid PRIMARY KEY CHECK (uuid_extract_version(evidence_id) = 7),
    creator_interaction_id uuid NOT NULL UNIQUE,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    source_kind text NOT NULL CHECK (source_kind = 'creator_input'),
    trust_status text NOT NULL CHECK (trust_status = 'external_claim'),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'creator_visible'),
    acceptance_status text NOT NULL CHECK (acceptance_status = 'accepted'),
    received_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (
        creator_interaction_id,
        subject_id,
        scene_id,
        creator_party_id
    ) REFERENCES armi.creator_input_interactions (
        creator_interaction_id,
        subject_id,
        scene_id,
        creator_party_id
    ),
    UNIQUE (evidence_id, subject_id, scene_id, creator_party_id)
);

CREATE TABLE armi.opportunities (
    opportunity_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(opportunity_id) = 7),
    evidence_id uuid NOT NULL UNIQUE,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    creator_party_id uuid NOT NULL,
    purpose text NOT NULL CHECK (purpose = 'consider_creator_input'),
    eligibility_status text NOT NULL CHECK (eligibility_status = 'eligible'),
    current_disposition text NOT NULL CHECK (current_disposition = 'open'),
    available_after timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    expires_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    FOREIGN KEY (
        evidence_id,
        subject_id,
        scene_id,
        creator_party_id
    ) REFERENCES armi.external_evidence (
        evidence_id,
        subject_id,
        scene_id,
        creator_party_id
    ),
    CHECK (expires_at IS NULL)
);

CREATE INDEX opportunities_recovery_idx
    ON armi.opportunities (
        current_disposition,
        eligibility_status,
        available_after,
        opportunity_id
    );

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_opportunity_count integer NOT NULL DEFAULT 0
        CHECK (resumable_opportunity_count >= 0);

REVOKE ALL ON TABLE
    armi.creator_input_interactions,
    armi.external_evidence,
    armi.opportunities
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.creator_input_interactions,
    armi.external_evidence,
    armi.opportunities
TO armi_runtime;

GRANT INSERT (
    creator_interaction_id,
    subject_id,
    scene_id,
    creator_party_id,
    purpose,
    idempotency_key,
    request_digest,
    content_digest,
    trace_id,
    schema_version
) ON armi.creator_input_interactions TO armi_runtime;

GRANT INSERT (
    evidence_id,
    creator_interaction_id,
    subject_id,
    scene_id,
    creator_party_id,
    artifact_id,
    source_kind,
    trust_status,
    privacy_scope,
    acceptance_status,
    schema_version
) ON armi.external_evidence TO armi_runtime;

GRANT INSERT (
    opportunity_id,
    evidence_id,
    subject_id,
    scene_id,
    creator_party_id,
    purpose,
    eligibility_status,
    current_disposition,
    schema_version
) ON armi.opportunities TO armi_runtime;

GRANT INSERT (
    timeline_item_id,
    scene_id,
    source_kind,
    source_ref,
    source_event_no,
    result_status,
    occurred_at,
    schema_version
) ON armi.scene_timeline_items TO armi_runtime;

GRANT INSERT (resumable_opportunity_count)
ON armi.runtime_recovery_runs TO armi_runtime;

GRANT UPDATE (resumable_opportunity_count)
ON armi.runtime_recovery_runs TO armi_runtime;
