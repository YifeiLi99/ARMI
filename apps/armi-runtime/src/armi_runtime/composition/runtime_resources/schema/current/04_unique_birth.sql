CREATE TABLE armi.subjects (
    subject_id uuid PRIMARY KEY CHECK (uuid_extract_version(subject_id) = 7),
    singleton_key smallint NOT NULL UNIQUE CHECK (singleton_key = 1),
    birth_request_id uuid NOT NULL UNIQUE
        CHECK (uuid_extract_version(birth_request_id) = 7),
    birth_idempotency_key text NOT NULL UNIQUE
        CHECK (
            length(birth_idempotency_key) BETWEEN 1 AND 128
            AND birth_idempotency_key ~ '^[A-Za-z0-9._:-]+$'
        ),
    birth_manifest_digest text NOT NULL
        CHECK (birth_manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
    current_generation_id uuid NOT NULL
        CHECK (uuid_extract_version(current_generation_id) = 7),
    current_bundle_activation_id uuid NOT NULL
        CHECK (uuid_extract_version(current_bundle_activation_id) = 7),
    subject_version bigint NOT NULL DEFAULT 0 CHECK (subject_version = 0),
    state_epoch bigint NOT NULL DEFAULT 0 CHECK (state_epoch = 0),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'blocked', 'deceased')),
    born_at timestamptz(6) NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE armi.life_generations (
    life_generation_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(life_generation_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    generation_no bigint NOT NULL CHECK (generation_no = 1),
    status text NOT NULL CHECK (status IN ('active', 'fenced', 'preparing')),
    opened_subject_version bigint NOT NULL CHECK (opened_subject_version = 0),
    closed_subject_version bigint,
    activation_reason text NOT NULL CHECK (activation_reason = 'birth'),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (subject_id, generation_no),
    CHECK (closed_subject_version IS NULL)
);

CREATE UNIQUE INDEX life_generations_one_active_idx
    ON armi.life_generations (subject_id)
    WHERE status = 'active';

CREATE TABLE armi.parties (
    party_id uuid PRIMARY KEY CHECK (uuid_extract_version(party_id) = 7),
    party_kind text NOT NULL CHECK (party_kind IN ('subject', 'creator')),
    represented_subject_id uuid REFERENCES armi.subjects(subject_id),
    display_label text,
    creator_role text,
    status text NOT NULL DEFAULT 'active' CHECK (status = 'active'),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (
            party_kind = 'subject'
            AND represented_subject_id IS NOT NULL
            AND creator_role IS NULL
        )
        OR (
            party_kind = 'creator'
            AND represented_subject_id IS NULL
            AND creator_role = 'unique_primary_creator'
        )
    ),
    CHECK (display_label IS NULL)
);

CREATE UNIQUE INDEX parties_one_subject_party_idx
    ON armi.parties (represented_subject_id)
    WHERE party_kind = 'subject';

CREATE UNIQUE INDEX parties_one_creator_idx
    ON armi.parties (creator_role)
    WHERE party_kind = 'creator';

CREATE TABLE armi.runtime_bundle_activations (
    bundle_activation_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(bundle_activation_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    bundle_version text NOT NULL CHECK (bundle_version = '0.0.0'),
    bundle_digest text NOT NULL
        CHECK (bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
    manifest_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    fixed_policy_digest text NOT NULL
        CHECK (fixed_policy_digest ~ '^sha256:[0-9a-f]{64}$'),
    fixed_prompt_set_digest text NOT NULL
        CHECK (fixed_prompt_set_digest ~ '^sha256:[0-9a-f]{64}$'),
    creator_asset_digest text NOT NULL
        CHECK (creator_asset_digest ~ '^sha256:[0-9a-f]{64}$'),
    model_binding text,
    status text NOT NULL CHECK (status IN ('current', 'superseded')),
    activated_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    deactivated_at timestamptz(6),
    activated_by_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    CHECK (model_binding IS NULL),
    CHECK (
        (status = 'current' AND deactivated_at IS NULL)
        OR (status = 'superseded' AND deactivated_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX runtime_bundle_one_current_idx
    ON armi.runtime_bundle_activations (subject_id)
    WHERE status = 'current';

CREATE TABLE armi.prompt_documents (
    prompt_document_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(prompt_document_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    prompt_kind text NOT NULL
        CHECK (
            prompt_kind IN (
                'personality_anchor',
                'creator_guidance',
                'subject_guidance'
            )
        ),
    write_authority text NOT NULL
        CHECK (write_authority IN ('fixed', 'creator', 'subject')),
    current_revision_id uuid,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (subject_id, prompt_kind),
    CHECK (
        (prompt_kind = 'personality_anchor' AND write_authority = 'fixed')
        OR (prompt_kind = 'creator_guidance' AND write_authority = 'creator')
        OR (prompt_kind = 'subject_guidance' AND write_authority = 'subject')
    ),
    CHECK (
        (
            prompt_kind = 'personality_anchor'
            AND status = 'active'
            AND current_revision_id IS NOT NULL
        )
        OR prompt_kind <> 'personality_anchor'
    ),
    CHECK (status = 'active' OR current_revision_id IS NOT NULL)
);

CREATE TABLE armi.prompt_revisions (
    prompt_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(prompt_revision_id) = 7),
    prompt_document_id uuid NOT NULL
        REFERENCES armi.prompt_documents(prompt_document_id),
    revision_no bigint NOT NULL CHECK (revision_no >= 1),
    previous_revision_id uuid REFERENCES armi.prompt_revisions(prompt_revision_id),
    content_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    content_digest text NOT NULL
        CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    author_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    subject_commit_id uuid,
    change_reason text NOT NULL
        CHECK (change_reason IN ('birth', 'created', 'revised', 'deactivated')),
    activated_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (prompt_document_id, revision_no),
    CHECK (
        (revision_no = 1 AND previous_revision_id IS NULL)
        OR (revision_no > 1 AND previous_revision_id IS NOT NULL)
    ),
    CHECK (
        (change_reason = 'birth' AND revision_no = 1)
        OR change_reason <> 'birth'
    ),
    CHECK (subject_commit_id IS NULL)
);

CREATE TABLE armi.subject_component_revisions (
    component_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(component_revision_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    component_kind text NOT NULL CHECK (component_kind IN ('self', 'mind', 'life_mode')),
    component_version bigint NOT NULL CHECK (component_version = 1),
    previous_revision_id uuid,
    origin_kind text NOT NULL CHECK (origin_kind = 'bootstrap'),
    origin_ref uuid NOT NULL CHECK (uuid_extract_version(origin_ref) = 7),
    subject_commit_id uuid,
    semantic_payload jsonb NOT NULL CHECK (jsonb_typeof(semantic_payload) = 'object'),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    created_at timestamptz(6) NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (subject_id, component_kind, component_version),
    CHECK (previous_revision_id IS NULL),
    CHECK (subject_commit_id IS NULL)
);

CREATE TABLE armi.subject_component_heads (
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    component_kind text NOT NULL CHECK (component_kind IN ('self', 'mind', 'life_mode')),
    current_revision_id uuid NOT NULL
        REFERENCES armi.subject_component_revisions(component_revision_id),
    component_version bigint NOT NULL CHECK (component_version = 1),
    PRIMARY KEY (subject_id, component_kind)
);

ALTER TABLE armi.subjects
    ADD CONSTRAINT subjects_current_generation_fk
    FOREIGN KEY (current_generation_id)
    REFERENCES armi.life_generations(life_generation_id)
    DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT subjects_current_activation_fk
    FOREIGN KEY (current_bundle_activation_id)
    REFERENCES armi.runtime_bundle_activations(bundle_activation_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE armi.prompt_documents
    ADD CONSTRAINT prompt_documents_current_revision_fk
    FOREIGN KEY (current_revision_id)
    REFERENCES armi.prompt_revisions(prompt_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE armi.durable_work
    ADD CONSTRAINT durable_work_subject_fk
    FOREIGN KEY (subject_id)
    REFERENCES armi.subjects(subject_id)
    ON DELETE RESTRICT;

REVOKE ALL ON TABLE
    armi.subjects,
    armi.life_generations,
    armi.runtime_bundle_activations,
    armi.parties,
    armi.prompt_documents,
    armi.prompt_revisions,
    armi.subject_component_heads,
    armi.subject_component_revisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.subjects,
    armi.life_generations,
    armi.runtime_bundle_activations,
    armi.parties,
    armi.prompt_documents,
    armi.prompt_revisions,
    armi.subject_component_heads,
    armi.subject_component_revisions
TO armi_runtime;

GRANT INSERT (
    subject_id,
    singleton_key,
    birth_request_id,
    birth_idempotency_key,
    birth_manifest_digest,
    current_generation_id,
    current_bundle_activation_id
) ON armi.subjects TO armi_runtime;

GRANT INSERT (
    life_generation_id,
    subject_id,
    generation_no,
    status,
    opened_subject_version,
    activation_reason
) ON armi.life_generations TO armi_runtime;

GRANT INSERT (
    bundle_activation_id,
    subject_id,
    bundle_version,
    bundle_digest,
    manifest_artifact_id,
    fixed_policy_digest,
    fixed_prompt_set_digest,
    creator_asset_digest,
    status,
    activated_by_party_id
) ON armi.runtime_bundle_activations TO armi_runtime;

GRANT INSERT (
    party_id,
    party_kind,
    represented_subject_id,
    creator_role
) ON armi.parties TO armi_runtime;

GRANT INSERT (
    prompt_document_id,
    subject_id,
    prompt_kind,
    write_authority,
    current_revision_id
) ON armi.prompt_documents TO armi_runtime;

GRANT INSERT (
    prompt_revision_id,
    prompt_document_id,
    revision_no,
    previous_revision_id,
    content_artifact_id,
    content_digest,
    author_party_id,
    change_reason
) ON armi.prompt_revisions TO armi_runtime;

GRANT UPDATE (current_revision_id, status)
ON armi.prompt_documents TO armi_runtime;

GRANT INSERT (
    subject_id,
    component_kind,
    current_revision_id,
    component_version
) ON armi.subject_component_heads TO armi_runtime;

GRANT INSERT (
    component_revision_id,
    subject_id,
    component_kind,
    component_version,
    origin_kind,
    origin_ref,
    semantic_payload,
    privacy_scope
) ON armi.subject_component_revisions TO armi_runtime;
