ALTER TABLE armi.subjects
    DROP CONSTRAINT subjects_subject_version_check,
    ADD CONSTRAINT subjects_subject_version_check
    CHECK (subject_version >= 0);

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_evidence_id_key,
    DROP CONSTRAINT opportunities_current_disposition_check,
    DROP CONSTRAINT opportunities_selection_state_check,
    ADD COLUMN root_opportunity_id uuid,
    ADD COLUMN predecessor_opportunity_id uuid,
    ADD COLUMN reconsideration_no smallint NOT NULL DEFAULT 0,
    ADD COLUMN resolved_at timestamptz(6),
    ADD CONSTRAINT opportunities_current_disposition_check
    CHECK (current_disposition IN ('open', 'selected', 'resolved', 'superseded')),
    ADD CONSTRAINT opportunities_reconsideration_check
    CHECK (reconsideration_no BETWEEN 0 AND 1),
    ADD CONSTRAINT opportunities_predecessor_fk
    FOREIGN KEY (predecessor_opportunity_id)
    REFERENCES armi.opportunities(opportunity_id),
    ADD CONSTRAINT opportunities_resolution_state_check
    CHECK (
        (current_disposition = 'open' AND selected_at IS NULL AND resolved_at IS NULL)
        OR (current_disposition = 'selected' AND selected_at IS NOT NULL AND resolved_at IS NULL)
        OR (current_disposition IN ('resolved', 'superseded') AND selected_at IS NOT NULL AND resolved_at IS NOT NULL)
    );

UPDATE armi.opportunities
SET root_opportunity_id = opportunity_id;

ALTER TABLE armi.opportunities
    ALTER COLUMN root_opportunity_id SET NOT NULL,
    ADD CONSTRAINT opportunities_root_fk
    FOREIGN KEY (root_opportunity_id)
    REFERENCES armi.opportunities(opportunity_id),
    ADD CONSTRAINT opportunities_lineage_check
    CHECK (
        (reconsideration_no = 0 AND root_opportunity_id = opportunity_id AND predecessor_opportunity_id IS NULL)
        OR (reconsideration_no = 1 AND root_opportunity_id <> opportunity_id AND predecessor_opportunity_id IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_evidence_reconsideration_unique
    UNIQUE (evidence_id, reconsideration_no),
    ADD CONSTRAINT opportunities_predecessor_unique
    UNIQUE (predecessor_opportunity_id);

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_status_check,
    DROP CONSTRAINT cognitive_episodes_state_check,
    ADD COLUMN application_resolution text CHECK (
        application_resolution IS NULL
        OR application_resolution IN (
            'applied', 'no_change', 'deferred', 'declined',
            'need_information', 'stale'
        )
    ),
    ADD COLUMN committed_at timestamptz(6),
    ADD CONSTRAINT cognitive_episodes_status_check
    CHECK (
        status IN (
            'preparing', 'prepared', 'calling_model', 'model_returned',
            'validating', 'candidate_validated', 'candidate_rejected',
            'committing', 'completed', 'stale', 'failed', 'cancelled'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_state_check
    CHECK (
        (status = 'preparing' AND context_digest IS NULL AND prepared_at IS NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('prepared', 'calling_model') AND context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('model_returned', 'validating') AND context_digest IS NOT NULL AND prepared_at IS NOT NULL AND model_returned_at IS NOT NULL AND validated_at IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status IN ('candidate_validated', 'committing') AND context_digest IS NOT NULL AND model_returned_at IS NOT NULL AND validated_at IS NOT NULL AND final_disposition IS NOT NULL AND failure_code IS NULL AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status = 'candidate_rejected' AND validated_at IS NOT NULL AND final_disposition IS NULL AND failure_code ~ '^CANDIDATE-[A-Z0-9-]+$' AND application_resolution IS NULL AND committed_at IS NULL)
        OR (status = 'completed' AND application_resolution IN ('applied', 'no_change', 'declined', 'deferred', 'need_information') AND committed_at IS NOT NULL)
        OR (status = 'stale' AND application_resolution = 'stale' AND committed_at IS NOT NULL)
        OR (status IN ('failed', 'cancelled') AND failure_code IS NOT NULL AND application_resolution IS NULL AND committed_at IS NULL)
    );

CREATE TABLE armi.subject_commits (
    subject_commit_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(subject_commit_id) = 7),
    candidate_validation_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    cognitive_episode_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    life_generation_id uuid NOT NULL
        REFERENCES armi.life_generations(life_generation_id),
    bundle_activation_id uuid NOT NULL
        REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    base_subject_version bigint NOT NULL CHECK (base_subject_version >= 0),
    new_subject_version bigint NOT NULL,
    base_state_epoch bigint NOT NULL CHECK (base_state_epoch >= 0),
    change_set_digest text NOT NULL
        CHECK (change_set_digest ~ '^sha256:[0-9a-f]{64}$'),
    commit_digest text NOT NULL
        CHECK (commit_digest ~ '^sha256:[0-9a-f]{64}$'),
    runtime_instance_id uuid NOT NULL
        REFERENCES armi.runtime_instances(runtime_instance_id),
    fence_token bigint NOT NULL CHECK (fence_token > 0),
    trace_id text NOT NULL CHECK (
        trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)
    ),
    committed_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, new_subject_version),
    CHECK (new_subject_version = base_subject_version + 1)
);

ALTER TABLE armi.subject_component_revisions
    DROP CONSTRAINT subject_component_revisions_component_version_check,
    DROP CONSTRAINT subject_component_revisions_origin_kind_check,
    DROP CONSTRAINT subject_component_revisions_previous_revision_id_check,
    DROP CONSTRAINT subject_component_revisions_subject_commit_id_check,
    ADD COLUMN proposal_ref text CHECK (
        proposal_ref IS NULL OR proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'
    ),
    ADD COLUMN semantic_digest text CHECK (
        semantic_digest IS NULL OR semantic_digest ~ '^sha256:[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT subject_component_revisions_component_version_check
    CHECK (component_version > 0),
    ADD CONSTRAINT subject_component_revisions_origin_kind_check
    CHECK (origin_kind IN ('bootstrap', 'subject_commit')),
    ADD CONSTRAINT subject_component_revisions_previous_fk
    FOREIGN KEY (previous_revision_id)
    REFERENCES armi.subject_component_revisions(component_revision_id),
    ADD CONSTRAINT subject_component_revisions_commit_fk
    FOREIGN KEY (subject_commit_id)
    REFERENCES armi.subject_commits(subject_commit_id),
    ADD CONSTRAINT subject_component_revisions_origin_check
    CHECK (
        (origin_kind = 'bootstrap' AND component_version = 1 AND previous_revision_id IS NULL AND subject_commit_id IS NULL AND proposal_ref IS NULL)
        OR (origin_kind = 'subject_commit' AND component_version > 1 AND previous_revision_id IS NOT NULL AND subject_commit_id IS NOT NULL AND proposal_ref IS NOT NULL AND semantic_digest IS NOT NULL)
    );

ALTER TABLE armi.subject_component_heads
    DROP CONSTRAINT subject_component_heads_component_version_check,
    ADD CONSTRAINT subject_component_heads_component_version_check
    CHECK (component_version > 0);

CREATE TABLE armi.accepted_experiences (
    experience_id uuid PRIMARY KEY CHECK (uuid_extract_version(experience_id) = 7),
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    cognitive_episode_id uuid NOT NULL REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    proposal_ref text NOT NULL CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    experience_kind text NOT NULL CHECK (experience_kind = 'creator_input'),
    fact_class text NOT NULL CHECK (fact_class = 'external_claim'),
    first_person_gist text NOT NULL CHECK (length(first_person_gist) BETWEEN 1 AND 1024),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    occurred_at timestamptz(6) NOT NULL,
    learned_at timestamptz(6) NOT NULL,
    accepted_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    source_perspective text NOT NULL CHECK (source_perspective = 'creator_claim'),
    uncertainty text CHECK (uncertainty IS NULL OR length(uncertainty) BETWEEN 1 AND 512),
    privacy_scope text NOT NULL CHECK (privacy_scope = 'private'),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_commit_id, proposal_ref)
);

CREATE TABLE armi.experience_evidence_links (
    experience_id uuid NOT NULL REFERENCES armi.accepted_experiences(experience_id),
    evidence_id uuid NOT NULL REFERENCES armi.external_evidence(evidence_id),
    context_item_id uuid NOT NULL REFERENCES armi.cognitive_context_items(context_item_id),
    link_kind text NOT NULL CHECK (link_kind = 'relied_on'),
    ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 8),
    PRIMARY KEY (experience_id, ordinal),
    UNIQUE (experience_id, evidence_id, context_item_id)
);

CREATE TABLE armi.cognitive_candidate_applications (
    candidate_application_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(candidate_application_id) = 7),
    candidate_validation_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    cognitive_episode_id uuid NOT NULL UNIQUE
        REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    work_id uuid NOT NULL UNIQUE REFERENCES armi.durable_work(work_id),
    resolution text NOT NULL CHECK (
        resolution IN ('applied', 'no_change', 'deferred', 'declined', 'need_information', 'stale')
    ),
    subject_commit_id uuid UNIQUE REFERENCES armi.subject_commits(subject_commit_id),
    successor_opportunity_id uuid UNIQUE REFERENCES armi.opportunities(opportunity_id),
    base_subject_version bigint NOT NULL CHECK (base_subject_version >= 0),
    observed_subject_version bigint NOT NULL CHECK (observed_subject_version >= 0),
    completion_digest text NOT NULL CHECK (completion_digest ~ '^sha256:[0-9a-f]{64}$'),
    runtime_instance_id uuid NOT NULL REFERENCES armi.runtime_instances(runtime_instance_id),
    fence_token bigint NOT NULL CHECK (fence_token > 0),
    resolved_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    CHECK ((resolution = 'applied') = (subject_commit_id IS NOT NULL)),
    CHECK (successor_opportunity_id IS NULL OR resolution = 'stale')
);

CREATE INDEX accepted_experiences_subject_idx
    ON armi.accepted_experiences (subject_commit_id, experience_id);
CREATE INDEX candidate_applications_resolution_idx
    ON armi.cognitive_candidate_applications (resolution, resolved_at, candidate_application_id);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_subject_commit_count integer NOT NULL DEFAULT 0
        CHECK (resumable_subject_commit_count >= 0);

REVOKE ALL ON TABLE
    armi.subject_commits,
    armi.accepted_experiences,
    armi.experience_evidence_links,
    armi.cognitive_candidate_applications
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE
    armi.subject_commits,
    armi.accepted_experiences,
    armi.experience_evidence_links,
    armi.cognitive_candidate_applications
TO armi_runtime;

GRANT INSERT ON TABLE
    armi.subject_commits,
    armi.accepted_experiences,
    armi.experience_evidence_links,
    armi.cognitive_candidate_applications
TO armi_runtime;

GRANT INSERT (
    component_revision_id, subject_id, component_kind, component_version,
    previous_revision_id, origin_kind, origin_ref, subject_commit_id,
    proposal_ref, semantic_digest, semantic_payload, privacy_scope
) ON armi.subject_component_revisions TO armi_runtime;

GRANT UPDATE (current_revision_id, component_version)
ON armi.subject_component_heads TO armi_runtime;
GRANT UPDATE (subject_version) ON armi.subjects TO armi_runtime;
GRANT UPDATE (
    current_disposition, selected_at, resolved_at
) ON armi.opportunities TO armi_runtime;
GRANT INSERT (
    opportunity_id, evidence_id, subject_id, scene_id, creator_party_id,
    purpose, eligibility_status, current_disposition,
    root_opportunity_id, predecessor_opportunity_id, reconsideration_no,
    schema_version
) ON armi.opportunities TO armi_runtime;
GRANT UPDATE (status, application_resolution, committed_at)
ON armi.cognitive_episodes TO armi_runtime;
GRANT INSERT (resumable_subject_commit_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_subject_commit_count)
ON armi.runtime_recovery_runs TO armi_runtime;
