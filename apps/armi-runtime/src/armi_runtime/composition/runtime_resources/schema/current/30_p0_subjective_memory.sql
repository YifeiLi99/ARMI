ALTER TABLE armi.accepted_experiences
    DROP CONSTRAINT accepted_experiences_fact_class_check,
    ADD CONSTRAINT accepted_experiences_fact_class_check CHECK (
        fact_class IN (
            'objective_fact',
            'external_claim',
            'subjective_understanding',
            'inference',
            'unknown'
        )
    );

CREATE TABLE armi.subjective_memories (
    memory_id uuid PRIMARY KEY CHECK (uuid_extract_version(memory_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL
        REFERENCES armi.life_generations(life_generation_id),
    current_revision_id uuid NOT NULL
        CHECK (uuid_extract_version(current_revision_id) = 7),
    head_version bigint NOT NULL CHECK (head_version = 1),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE armi.subjective_memory_revisions (
    memory_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(memory_revision_id) = 7),
    memory_id uuid NOT NULL REFERENCES armi.subjective_memories(memory_id),
    revision_no bigint NOT NULL CHECK (revision_no = 1),
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL
        REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL
        CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    source_experience_id uuid NOT NULL UNIQUE
        REFERENCES armi.accepted_experiences(experience_id),
    source_kind text NOT NULL CHECK (
        source_kind IN ('experienced', 'reported', 'inferred', 'queried', 'unknown')
    ),
    source_fact_class text NOT NULL CHECK (
        source_fact_class IN (
            'objective_fact',
            'external_claim',
            'subjective_understanding',
            'inference',
            'unknown'
        )
    ),
    summary text NOT NULL CHECK (length(summary) BETWEEN 1 AND 512),
    uncertainty text CHECK (
        uncertainty IS NULL OR length(uncertainty) BETWEEN 1 AND 512
    ),
    mechanism_identity text NOT NULL CHECK (
        mechanism_identity = 'armi.memory-formation.contextual-v1'
    ),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (memory_id, memory_revision_id),
    UNIQUE (memory_id, revision_no),
    UNIQUE (subject_commit_id, proposal_ref),
    CHECK (previous_revision_id IS NULL),
    CHECK (
        (source_kind = 'reported' AND source_fact_class = 'external_claim')
        OR (source_kind = 'inferred' AND source_fact_class = 'inference')
        OR (source_kind = 'queried' AND source_fact_class IN (
            'objective_fact', 'external_claim', 'subjective_understanding'
        ))
        OR (source_kind = 'unknown' AND source_fact_class = 'unknown')
        OR (source_kind = 'experienced' AND source_fact_class IN (
            'objective_fact', 'subjective_understanding'
        ))
    )
);

ALTER TABLE armi.subjective_memories
    ADD CONSTRAINT subjective_memories_current_revision_fk
    FOREIGN KEY (memory_id, current_revision_id)
    REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX subjective_memories_subject_idx
    ON armi.subjective_memories (subject_id, created_at DESC, memory_id);
CREATE INDEX subjective_memory_revisions_memory_idx
    ON armi.subjective_memory_revisions (memory_id, revision_no DESC);

REVOKE ALL ON TABLE
    armi.subjective_memories,
    armi.subjective_memory_revisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT, INSERT ON TABLE
    armi.subjective_memories,
    armi.subjective_memory_revisions
TO armi_runtime;

GRANT UPDATE (current_revision_id, head_version)
ON armi.subjective_memories TO armi_runtime;
