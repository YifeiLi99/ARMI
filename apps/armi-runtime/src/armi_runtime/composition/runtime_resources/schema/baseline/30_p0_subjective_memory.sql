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
    head_version bigint NOT NULL CHECK (head_version > 0),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE armi.subjective_memory_revisions (
    memory_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(memory_revision_id) = 7),
    memory_id uuid NOT NULL REFERENCES armi.subjective_memories(memory_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL
        REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL
        CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    source_experience_id uuid NOT NULL
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
    revision_kind text NOT NULL CHECK (
        revision_kind IN (
            'formed', 'recalled', 'faded', 'forgotten', 'reinterpreted'
        )
    ),
    accessibility text NOT NULL CHECK (
        accessibility IN ('available', 'faded', 'forgotten')
    ),
    mechanism_identity text NOT NULL CHECK (
        mechanism_identity IN (
            'armi.memory-formation.contextual-v1',
            'armi.memory-revision.contextual-v1'
        )
    ),
    mechanism_config_identity text NOT NULL CHECK (
        mechanism_config_identity IN (
            'formation-v1', 'natural-dialogue-v1', 'sleep-maintenance-v1'
        )
    ),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (memory_id, memory_revision_id),
    UNIQUE (memory_id, revision_no),
    UNIQUE (subject_commit_id, proposal_ref),
    CHECK (
        (revision_no = 1
            AND previous_revision_id IS NULL
            AND revision_kind = 'formed'
            AND accessibility = 'available'
            AND mechanism_identity = 'armi.memory-formation.contextual-v1'
            AND mechanism_config_identity = 'formation-v1')
        OR
        (revision_no > 1
            AND previous_revision_id IS NOT NULL
            AND revision_kind <> 'formed'
            AND mechanism_identity = 'armi.memory-revision.contextual-v1'
            AND mechanism_config_identity IN (
                'natural-dialogue-v1', 'sleep-maintenance-v1'
            ))
    ),
    CHECK (
        (revision_kind IN ('formed', 'recalled') AND accessibility = 'available')
        OR (revision_kind = 'faded' AND accessibility = 'faded')
        OR (revision_kind = 'forgotten' AND accessibility = 'forgotten')
        OR (revision_kind = 'reinterpreted'
            AND accessibility IN ('available', 'faded'))
    ),
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

ALTER TABLE armi.subjective_memory_revisions
    ADD CONSTRAINT subjective_memory_revisions_previous_fk
    FOREIGN KEY (memory_id, previous_revision_id)
    REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE armi.subjective_memories
    ADD CONSTRAINT subjective_memories_current_revision_fk
    FOREIGN KEY (memory_id, current_revision_id)
    REFERENCES armi.subjective_memory_revisions(memory_id, memory_revision_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX subjective_memories_subject_idx
    ON armi.subjective_memories (subject_id, created_at DESC, memory_id);
CREATE INDEX subjective_memory_revisions_memory_idx
    ON armi.subjective_memory_revisions (memory_id, revision_no DESC);
CREATE UNIQUE INDEX subjective_memory_revisions_source_formation_idx
    ON armi.subjective_memory_revisions (source_experience_id)
    WHERE revision_no = 1;

CREATE TABLE armi.memory_relations (
    memory_relation_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(memory_relation_id) = 7),
    from_memory_id uuid NOT NULL REFERENCES armi.subjective_memories(memory_id),
    from_memory_revision_id uuid NOT NULL,
    to_memory_id uuid NOT NULL REFERENCES armi.subjective_memories(memory_id),
    relation_kind text NOT NULL CHECK (
        relation_kind IN ('supports', 'contradicts', 'reinterprets')
    ),
    subject_commit_id uuid NOT NULL
        REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL
        CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (from_memory_id, from_memory_revision_id)
        REFERENCES armi.subjective_memory_revisions(
            memory_id, memory_revision_id
        ),
    UNIQUE (subject_commit_id, proposal_ref),
    CHECK (from_memory_id <> to_memory_id)
);

CREATE INDEX memory_relations_from_idx
    ON armi.memory_relations (from_memory_id, created_at DESC);
CREATE INDEX memory_relations_to_idx
    ON armi.memory_relations (to_memory_id, created_at DESC);

REVOKE ALL ON TABLE
    armi.subjective_memories,
    armi.subjective_memory_revisions,
    armi.memory_relations
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT, INSERT ON TABLE
    armi.subjective_memories,
    armi.subjective_memory_revisions,
    armi.memory_relations
TO armi_runtime;

GRANT UPDATE (current_revision_id, head_version)
ON armi.subjective_memories TO armi_runtime;
