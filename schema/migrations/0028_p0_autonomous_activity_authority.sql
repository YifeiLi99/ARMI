ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_expires_at_check,
    DROP CONSTRAINT opportunities_current_disposition_check,
    DROP CONSTRAINT opportunities_resolution_state_check,
    ALTER COLUMN evidence_id DROP NOT NULL,
    ALTER COLUMN scene_id DROP NOT NULL,
    ALTER COLUMN creator_party_id DROP NOT NULL,
    ADD COLUMN source_kind text,
    ADD COLUMN source_ref uuid,
    ADD COLUMN source_version bigint,
    ADD COLUMN source_digest text,
    ADD COLUMN activity_id uuid,
    ADD CONSTRAINT opportunities_current_disposition_check CHECK (
        current_disposition IN (
            'open', 'selected', 'resolved', 'superseded', 'cancelled'
        )
    ),
    ADD CONSTRAINT opportunities_resolution_state_check CHECK (
        (current_disposition = 'open'
            AND selected_at IS NULL AND resolved_at IS NULL)
        OR (current_disposition = 'selected'
            AND selected_at IS NOT NULL AND resolved_at IS NULL)
        OR (current_disposition IN ('resolved', 'superseded')
            AND selected_at IS NOT NULL AND resolved_at IS NOT NULL)
        OR (current_disposition = 'cancelled' AND resolved_at IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_expiry_check CHECK (
        expires_at IS NULL OR expires_at > available_after
    );

UPDATE armi.opportunities AS opportunity
SET source_kind = 'external_evidence',
    source_ref = opportunity.evidence_id,
    source_version = 1,
    source_digest = artifact.content_digest
FROM armi.external_evidence AS evidence
JOIN armi.artifacts AS artifact
  ON artifact.artifact_id = evidence.artifact_id
WHERE evidence.evidence_id = opportunity.evidence_id;

ALTER TABLE armi.opportunities
    ALTER COLUMN source_kind SET NOT NULL,
    ALTER COLUMN source_ref SET NOT NULL,
    ALTER COLUMN source_version SET NOT NULL,
    ALTER COLUMN source_digest SET NOT NULL,
    ADD CONSTRAINT opportunities_source_kind_check CHECK (
        source_kind IN (
            'external_evidence',
            'life_generation_available',
            'subject_component_revision',
            'activity_revision'
        )
    ),
    ADD CONSTRAINT opportunities_source_version_check CHECK (
        source_version > 0
    ),
    ADD CONSTRAINT opportunities_source_digest_check CHECK (
        source_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref
            AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL
            AND activity_id IS NULL)
        OR (source_kind IN (
                'life_generation_available',
                'subject_component_revision'
            )
            AND evidence_id IS NULL
            AND scene_id IS NULL
            AND creator_party_id IS NULL
            AND activity_id IS NULL)
        OR (source_kind = 'activity_revision'
            AND evidence_id IS NULL
            AND scene_id IS NULL
            AND creator_party_id IS NULL
            AND activity_id IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_source_reconsideration_unique UNIQUE (
        subject_id,
        source_kind,
        source_ref,
        source_version,
        purpose,
        reconsideration_no
    );

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input',
            'consider_web_evidence',
            'consider_codex_task',
            'consider_codex_result',
            'consider_autonomous_life'
        )
    );

ALTER TABLE armi.cognitive_episodes
    ALTER COLUMN scene_id DROP NOT NULL,
    ALTER COLUMN creator_party_id DROP NOT NULL,
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input',
            'consider_web_evidence',
            'consider_codex_task',
            'consider_codex_result',
            'consider_autonomous_life'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose = 'consider_autonomous_life'
            AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose <> 'consider_autonomous_life'
            AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_context_items
    DROP CONSTRAINT cognitive_context_items_section_check,
    ADD CONSTRAINT cognitive_context_items_section_check CHECK (
        section IN (
            'runtime_truth', 'purpose', 'self', 'mind', 'life_mode',
            'scene', 'relationship', 'memory', 'activity', 'evidence',
            'capability', 'prompt'
        )
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition',
            'creator_dialogue',
            'autonomous_activity'
        )
    ),
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1',
            'armi.autonomous-activity-candidate.v1'
        )
    );

CREATE TABLE armi.activities (
    activity_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(activity_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    activity_kind text NOT NULL CHECK (activity_kind = 'self_directed'),
    origin_opportunity_id uuid NOT NULL UNIQUE
        REFERENCES armi.opportunities(opportunity_id),
    current_revision_id uuid,
    head_version bigint NOT NULL DEFAULT 0 CHECK (head_version >= 0),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (activity_id, subject_id),
    UNIQUE (activity_id, current_revision_id)
);

CREATE TABLE armi.activity_revisions (
    activity_revision_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(activity_revision_id) = 7),
    activity_id uuid NOT NULL REFERENCES armi.activities(activity_id),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL
        REFERENCES armi.subject_commits(subject_commit_id),
    candidate_validation_id uuid NOT NULL
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    proposal_ref text NOT NULL
        CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    goal text NOT NULL CHECK (
        octet_length(goal) BETWEEN 1 AND 8192
    ),
    progress_summary text,
    waiting_condition text,
    resumption_cue text,
    next_safe_step text NOT NULL CHECK (
        octet_length(next_safe_step) BETWEEN 1 AND 4096
    ),
    status text NOT NULL CHECK (
        status IN (
            'considering', 'ready', 'in_progress', 'waiting', 'paused',
            'resuming', 'completed', 'abandoned', 'failed'
        )
    ),
    terminal_reason text,
    related_scene_id uuid REFERENCES armi.interaction_scenes(scene_id),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (activity_id, revision_no),
    UNIQUE (activity_revision_id, activity_id),
    UNIQUE (candidate_validation_id, proposal_ref),
    FOREIGN KEY (previous_revision_id, activity_id)
        REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    CHECK (
        (revision_no = 1 AND previous_revision_id IS NULL)
        OR (revision_no > 1 AND previous_revision_id IS NOT NULL)
    ),
    CHECK (
        (status IN ('completed', 'abandoned', 'failed'))
            = (terminal_reason IS NOT NULL)
    )
);

ALTER TABLE armi.activities
    ADD CONSTRAINT activities_current_revision_fk
    FOREIGN KEY (current_revision_id, activity_id)
    REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    ADD CONSTRAINT activities_current_revision_state_check CHECK (
        (head_version = 0 AND current_revision_id IS NULL)
        OR (head_version > 0 AND current_revision_id IS NOT NULL)
    );

ALTER TABLE armi.opportunities
    ADD CONSTRAINT opportunities_activity_fk
    FOREIGN KEY (activity_id, subject_id)
    REFERENCES armi.activities(activity_id, subject_id);

REVOKE ALL ON TABLE
    armi.activities,
    armi.activity_revisions
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.activities,
    armi.activity_revisions
TO armi_runtime;

GRANT SELECT ON TABLE
    armi.activities,
    armi.activity_revisions
TO armi_admin;

GRANT INSERT (
    activity_id,
    subject_id,
    activity_kind,
    origin_opportunity_id,
    current_revision_id,
    head_version,
    privacy_scope,
    schema_version
) ON armi.activities TO armi_runtime;

GRANT UPDATE (
    current_revision_id,
    head_version
) ON armi.activities TO armi_runtime;

GRANT INSERT (
    activity_revision_id,
    activity_id,
    revision_no,
    previous_revision_id,
    subject_commit_id,
    candidate_validation_id,
    proposal_ref,
    goal,
    progress_summary,
    waiting_condition,
    resumption_cue,
    next_safe_step,
    status,
    terminal_reason,
    related_scene_id,
    schema_version
) ON armi.activity_revisions TO armi_runtime;

GRANT INSERT (
    opportunity_id,
    evidence_id,
    subject_id,
    scene_id,
    creator_party_id,
    purpose,
    eligibility_status,
    current_disposition,
    root_opportunity_id,
    predecessor_opportunity_id,
    reconsideration_no,
    source_kind,
    source_ref,
    source_version,
    source_digest,
    activity_id,
    schema_version
) ON armi.opportunities TO armi_runtime;
