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
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.sleep-decision-candidate.v1'
        )
    );

CREATE TABLE armi.relationships (
    relationship_id uuid PRIMARY KEY CHECK (uuid_extract_version(relationship_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL REFERENCES armi.life_generations(life_generation_id),
    subject_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    other_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    scope text NOT NULL CHECK (scope = 'creator_social'),
    current_revision_id uuid NOT NULL CHECK (uuid_extract_version(current_revision_id) = 7),
    head_version bigint NOT NULL CHECK (head_version > 0),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (subject_id, other_party_id, scope),
    UNIQUE (relationship_id, current_revision_id),
    CHECK (subject_party_id <> other_party_id)
);

CREATE TABLE armi.relationship_revisions (
    relationship_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(relationship_revision_id) = 7),
    relationship_id uuid NOT NULL REFERENCES armi.relationships(relationship_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    facts jsonb NOT NULL CHECK (
        jsonb_typeof(facts) = 'array'
        AND jsonb_array_length(facts) BETWEEN 1 AND 64
    ),
    interpretation text NOT NULL CHECK (length(interpretation) BETWEEN 1 AND 1024),
    boundaries jsonb NOT NULL CHECK (
        jsonb_typeof(boundaries) = 'array'
        AND jsonb_array_length(boundaries) <= 16
    ),
    commitments jsonb NOT NULL CHECK (
        jsonb_typeof(commitments) = 'array'
        AND jsonb_array_length(commitments) <= 16
    ),
    open_issues jsonb NOT NULL CHECK (
        jsonb_typeof(open_issues) = 'array'
        AND jsonb_array_length(open_issues) <= 32
    ),
    commitment_event jsonb CHECK (
        commitment_event IS NULL OR jsonb_typeof(commitment_event) = 'object'
    ),
    relationship_status text NOT NULL CHECK (
        relationship_status IN ('active', 'ended')
    ),
    semantic_digest text NOT NULL CHECK (semantic_digest ~ '^sha256:[0-9a-f]{64}$'),
    mechanism_identity text NOT NULL CHECK (
        mechanism_identity = 'armi.relationship.contextual-v1'
    ),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (relationship_id, relationship_revision_id),
    UNIQUE (relationship_id, revision_no),
    UNIQUE (subject_commit_id, proposal_ref),
    CHECK (
        (revision_no = 1 AND previous_revision_id IS NULL)
        OR (revision_no > 1 AND previous_revision_id IS NOT NULL)
    )
);

ALTER TABLE armi.relationship_revisions
    ADD CONSTRAINT relationship_revisions_previous_fk
    FOREIGN KEY (relationship_id, previous_revision_id)
    REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE armi.relationships
    ADD CONSTRAINT relationships_current_revision_fk
    FOREIGN KEY (relationship_id, current_revision_id)
    REFERENCES armi.relationship_revisions(relationship_id, relationship_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE armi.relationship_experience_links (
    relationship_revision_id uuid NOT NULL
        REFERENCES armi.relationship_revisions(relationship_revision_id),
    experience_id uuid NOT NULL REFERENCES armi.accepted_experiences(experience_id),
    link_kind text NOT NULL CHECK (
        link_kind IN ('supports_relationship_change', 'supports_commitment_event')
    ),
    ordinal smallint NOT NULL CHECK (ordinal > 0),
    PRIMARY KEY (relationship_revision_id, experience_id, link_kind),
    UNIQUE (relationship_revision_id, ordinal)
);

CREATE INDEX relationships_subject_idx
    ON armi.relationships (subject_id, created_at DESC, relationship_id);
CREATE INDEX relationship_revisions_relationship_idx
    ON armi.relationship_revisions (relationship_id, revision_no DESC);

REVOKE ALL ON TABLE
    armi.relationships,
    armi.relationship_revisions,
    armi.relationship_experience_links
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT, INSERT ON TABLE
    armi.relationships,
    armi.relationship_revisions,
    armi.relationship_experience_links
TO armi_runtime;

GRANT UPDATE (current_revision_id, head_version)
ON armi.relationships TO armi_runtime;
