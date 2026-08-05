ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK (
        owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action',
            'web_research', 'codex_delegation', 'sleep', 'material'
        )
    );

ALTER TABLE armi.parties
    ADD CONSTRAINT parties_party_subject_unique
    UNIQUE (party_id, represented_subject_id);

CREATE TABLE armi.life_materials (
    life_material_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(life_material_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL REFERENCES armi.life_generations(life_generation_id),
    material_kind text NOT NULL CHECK (
        material_kind IN ('diary', 'work', 'collection', 'draft')
    ),
    owner_party_id uuid NOT NULL,
    current_revision_id uuid NOT NULL
        CHECK (uuid_extract_version(current_revision_id) = 7),
    head_version bigint NOT NULL CHECK (head_version > 0),
    deleted_at timestamptz(6),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (life_material_id, current_revision_id),
    FOREIGN KEY (owner_party_id, subject_id)
        REFERENCES armi.parties(party_id, represented_subject_id)
);

CREATE TABLE armi.life_material_revisions (
    life_material_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(life_material_revision_id) = 7),
    life_material_id uuid NOT NULL
        REFERENCES armi.life_materials(life_material_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    body_digest text NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 256),
    metadata jsonb NOT NULL CHECK (
        jsonb_typeof(metadata) = 'object'
        AND jsonb_object_length(metadata) <= 32
    ),
    revision_kind text NOT NULL CHECK (
        revision_kind IN ('created', 'updated', 'privacy_changed', 'deleted')
    ),
    privacy_status text NOT NULL CHECK (
        privacy_status IN ('creator_visible', 'private', 'shared', 'restricted')
    ),
    material_status text NOT NULL CHECK (material_status IN ('active', 'archived')),
    source_kind text NOT NULL CHECK (source_kind = 'subject_cognition'),
    semantic_digest text NOT NULL CHECK (semantic_digest ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (life_material_id, life_material_revision_id),
    UNIQUE (life_material_id, revision_no),
    UNIQUE (subject_commit_id, proposal_ref),
    CHECK (
        (revision_no = 1 AND previous_revision_id IS NULL AND revision_kind = 'created')
        OR (
            revision_no > 1 AND previous_revision_id IS NOT NULL
            AND revision_kind IN ('updated', 'privacy_changed', 'deleted')
        )
    ),
    CHECK (
        (revision_kind = 'created' AND privacy_status = 'creator_visible')
        OR (
            revision_kind = 'updated'
            AND privacy_status IN ('creator_visible', 'private')
        )
        OR (
            revision_kind = 'privacy_changed'
            AND privacy_status IN ('creator_visible', 'private')
        )
        OR (revision_kind = 'deleted' AND privacy_status = 'restricted')
    )
);

ALTER TABLE armi.life_material_revisions
    ADD CONSTRAINT life_material_revisions_previous_fk
    FOREIGN KEY (life_material_id, previous_revision_id)
    REFERENCES armi.life_material_revisions(
        life_material_id, life_material_revision_id
    )
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE armi.life_materials
    ADD CONSTRAINT life_materials_current_revision_fk
    FOREIGN KEY (life_material_id, current_revision_id)
    REFERENCES armi.life_material_revisions(
        life_material_id, life_material_revision_id
    )
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX life_materials_subject_current_idx
    ON armi.life_materials (
        subject_id, updated_at DESC, life_material_id
    ) WHERE deleted_at IS NULL;
CREATE INDEX life_material_revisions_material_idx
    ON armi.life_material_revisions (life_material_id, revision_no DESC);

REVOKE ALL ON TABLE
    armi.life_materials,
    armi.life_material_revisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT, INSERT ON TABLE
    armi.life_materials,
    armi.life_material_revisions
TO armi_runtime;

GRANT UPDATE (current_revision_id, head_version, deleted_at, updated_at)
ON armi.life_materials TO armi_runtime;
