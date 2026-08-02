CREATE TABLE armi.web_research_intents (
    web_research_intent_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(web_research_intent_id) = 7),
    subject_commit_id uuid NOT NULL UNIQUE
        REFERENCES armi.subject_commits(subject_commit_id),
    source_opportunity_id uuid NOT NULL UNIQUE
        REFERENCES armi.opportunities(opportunity_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    proposal_ref text NOT NULL CHECK (
        proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'
    ),
    purpose text NOT NULL CHECK (purpose = 'public_web_research'),
    operation_class text NOT NULL CHECK (operation_class = 'search_read_public'),
    query_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    query_digest text NOT NULL CHECK (query_digest ~ '^sha256:[0-9a-f]{64}$'),
    idempotency_key text NOT NULL CHECK (
        octet_length(idempotency_key) BETWEEN 1 AND 128
        AND idempotency_key ~ '^[A-Za-z0-9._:-]+$'
    ),
    admission_work_id uuid NOT NULL UNIQUE REFERENCES armi.durable_work(work_id),
    web_observation_request_id uuid UNIQUE
        REFERENCES armi.web_observation_requests(web_observation_request_id),
    status text NOT NULL CHECK (
        status IN ('pending', 'admitted', 'succeeded', 'failed', 'unknown', 'cancelled')
    ),
    trace_id text NOT NULL CHECK (
        trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)
    ),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, source_opportunity_id, proposal_ref),
    CHECK (
        (status = 'pending' AND web_observation_request_id IS NULL AND completed_at IS NULL)
        OR (status = 'admitted' AND web_observation_request_id IS NOT NULL AND completed_at IS NULL)
        OR (status IN ('succeeded', 'failed', 'unknown', 'cancelled')
            AND web_observation_request_id IS NOT NULL AND completed_at IS NOT NULL)
    )
);

ALTER TABLE armi.web_observation_requests
    ADD COLUMN web_research_intent_id uuid UNIQUE
        REFERENCES armi.web_research_intents(web_research_intent_id);

ALTER TABLE armi.external_evidence
    ALTER COLUMN creator_interaction_id DROP NOT NULL,
    DROP CONSTRAINT external_evidence_source_kind_check,
    DROP CONSTRAINT external_evidence_privacy_scope_check,
    ADD COLUMN web_observation_request_id uuid UNIQUE
        REFERENCES armi.web_observation_requests(web_observation_request_id),
    ADD COLUMN observation_attempt_id uuid UNIQUE
        REFERENCES armi.observation_attempts(observation_attempt_id),
    ADD CONSTRAINT external_evidence_source_kind_check
        CHECK (source_kind IN ('creator_input', 'web_search')),
    ADD CONSTRAINT external_evidence_privacy_scope_check
        CHECK (privacy_scope IN ('creator_visible', 'private')),
    ADD CONSTRAINT external_evidence_source_identity_check CHECK (
        (source_kind = 'creator_input'
            AND creator_interaction_id IS NOT NULL
            AND web_observation_request_id IS NULL
            AND observation_attempt_id IS NULL
            AND privacy_scope = 'creator_visible')
        OR (source_kind = 'web_search'
            AND creator_interaction_id IS NULL
            AND web_observation_request_id IS NOT NULL
            AND observation_attempt_id IS NOT NULL
            AND privacy_scope = 'private')
    );

CREATE TABLE armi.web_evidence_sources (
    web_evidence_source_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(web_evidence_source_id) = 7),
    evidence_id uuid NOT NULL REFERENCES armi.external_evidence(evidence_id),
    observation_attempt_id uuid NOT NULL
        REFERENCES armi.observation_attempts(observation_attempt_id),
    citation_no smallint NOT NULL CHECK (citation_no BETWEEN 1 AND 128),
    source_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
    canonical_url_digest text NOT NULL
        CHECK (canonical_url_digest ~ '^sha256:[0-9a-f]{64}$'),
    title_digest text NOT NULL CHECK (title_digest ~ '^sha256:[0-9a-f]{64}$'),
    citation_digest text NOT NULL CHECK (citation_digest ~ '^sha256:[0-9a-f]{64}$'),
    acquisition_kind text NOT NULL CHECK (acquisition_kind = 'provider_synthesis_citation'),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (evidence_id, citation_no),
    UNIQUE (evidence_id, canonical_url_digest),
    UNIQUE (observation_attempt_id, citation_no)
);

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_purpose_check
        CHECK (purpose IN ('consider_creator_input', 'consider_web_evidence'));

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check
        CHECK (purpose IN ('consider_creator_input', 'consider_web_evidence'));

ALTER TABLE armi.accepted_experiences
    DROP CONSTRAINT accepted_experiences_experience_kind_check,
    DROP CONSTRAINT accepted_experiences_source_perspective_check,
    ADD CONSTRAINT accepted_experiences_experience_kind_check
        CHECK (experience_kind IN ('creator_input', 'web_observation')),
    ADD CONSTRAINT accepted_experiences_source_perspective_check
        CHECK (source_perspective IN ('creator_claim', 'web_claim')),
    ADD CONSTRAINT accepted_experiences_source_pair_check CHECK (
        (experience_kind = 'creator_input' AND source_perspective = 'creator_claim')
        OR (experience_kind = 'web_observation' AND source_perspective = 'web_claim')
    );

ALTER TABLE armi.cognitive_candidate_validation_items
    DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
    ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check
        CHECK (owner_kind IN (
            'experience', 'self', 'mind', 'life_mode', 'memory',
            'relationship', 'activity', 'capability', 'action', 'web_research'
        ));

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_web_research_intent_count integer NOT NULL DEFAULT 0
        CHECK (resumable_web_research_intent_count >= 0),
    ADD COLUMN pending_web_evidence_acceptance_count integer NOT NULL DEFAULT 0
        CHECK (pending_web_evidence_acceptance_count >= 0),
    ADD COLUMN resumable_web_cognition_count integer NOT NULL DEFAULT 0
        CHECK (resumable_web_cognition_count >= 0);

REVOKE ALL ON TABLE armi.web_research_intents, armi.web_evidence_sources
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.web_research_intents, armi.web_evidence_sources
TO armi_runtime;
GRANT INSERT (
    web_research_intent_id, subject_commit_id, source_opportunity_id,
    subject_id, scene_id, creator_party_id, proposal_ref, purpose,
    operation_class, query_artifact_id, query_digest, idempotency_key,
    admission_work_id, status, trace_id, schema_version
) ON armi.web_research_intents TO armi_runtime;
GRANT UPDATE (web_observation_request_id, status, completed_at)
ON armi.web_research_intents TO armi_runtime;
GRANT UPDATE (web_research_intent_id)
ON armi.web_observation_requests TO armi_runtime;
GRANT INSERT (
    web_evidence_source_id, evidence_id, observation_attempt_id, citation_no,
    source_artifact_id, canonical_url_digest, title_digest, citation_digest,
    acquisition_kind, schema_version
) ON armi.web_evidence_sources TO armi_runtime;
GRANT INSERT (
    evidence_id, creator_interaction_id, subject_id, scene_id,
    creator_party_id, artifact_id, source_kind, trust_status,
    privacy_scope, acceptance_status, web_observation_request_id,
    observation_attempt_id, schema_version
) ON armi.external_evidence TO armi_runtime;
GRANT INSERT (
    resumable_web_research_intent_count,
    pending_web_evidence_acceptance_count,
    resumable_web_cognition_count
) ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (
    resumable_web_research_intent_count,
    pending_web_evidence_acceptance_count,
    resumable_web_cognition_count
) ON armi.runtime_recovery_runs TO armi_runtime;
