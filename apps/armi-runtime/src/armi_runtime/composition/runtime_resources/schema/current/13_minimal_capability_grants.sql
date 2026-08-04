ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check
    CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check
    CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3'
        )
    );

CREATE TABLE armi.capabilities (
    capability_id uuid PRIMARY KEY,
    capability_kind text NOT NULL UNIQUE,
    adapter_kind text NOT NULL,
    operation_class text NOT NULL,
    scope_schema text NOT NULL,
    availability_status text NOT NULL,
    verification_capability text NOT NULL,
    configuration_version bigint NOT NULL,
    configuration_digest text NOT NULL,
    CONSTRAINT capabilities_id_v7_chk CHECK (substring(capability_id::text, 15, 1) = '7'),
    CONSTRAINT capabilities_kind_chk CHECK (capability_kind IN ('creator.scene.reply', 'codex.delegated-work')),
    CONSTRAINT capabilities_operation_chk CHECK (
        (capability_kind = 'creator.scene.reply' AND operation_class = 'send') OR
        (capability_kind = 'codex.delegated-work' AND operation_class = 'execute')
    ),
    CONSTRAINT capabilities_availability_chk CHECK (availability_status IN ('available', 'unavailable')),
    CONSTRAINT capabilities_version_chk CHECK (configuration_version > 0),
    CONSTRAINT capabilities_digest_chk CHECK (configuration_digest ~ '^sha256:[0-9a-f]{64}$')
);

INSERT INTO armi.capabilities (
    capability_id, capability_kind, adapter_kind, operation_class,
    scope_schema, availability_status, verification_capability,
    configuration_version, configuration_digest
) VALUES
    ('01985d00-0000-7000-8000-000000000027', 'creator.scene.reply',
     'creator-interface', 'send', 'armi.creator-scene-reply-scope.v1',
     'available', 'creator_response_receipt', 1,
     'sha256:4c13c64439fd4c2df3c6daa43e1ebc2f8c58e7e65de22fe9eb5bc1ee9297b657'),
    ('01985d00-0000-7000-8000-000000000038', 'codex.delegated-work',
     'codex-runner', 'execute', 'armi.codex-delegated-work-scope.v1',
     'unavailable', 'runner_not_implemented', 1,
     'sha256:fb48604d55ce7f5d054d960cbd54a1a05dc5e25dfb61cf11620ec4c3314f27d9');

CREATE TABLE armi.capability_requests (
    capability_request_id uuid PRIMARY KEY,
    subject_commit_id uuid NOT NULL REFERENCES armi.subject_commits(subject_commit_id),
    proposal_ref text NOT NULL,
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    capability_id uuid NOT NULL REFERENCES armi.capabilities(capability_id),
    capability_kind text NOT NULL,
    operation_class text NOT NULL,
    audience_scope text,
    data_scope text,
    purpose text NOT NULL,
    workspace_scope text,
    artifact_scope text,
    network_access boolean,
    requested_valid_for_seconds integer NOT NULL,
    requested_max_uses integer NOT NULL,
    requested_max_payload_bytes integer,
    request_digest text NOT NULL,
    current_status text NOT NULL DEFAULT 'pending',
    request_version bigint NOT NULL DEFAULT 1,
    resolved_by_party_id uuid REFERENCES armi.parties(party_id),
    resolution_reason_class text,
    resolved_at timestamptz(6),
    created_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1,
    UNIQUE (subject_commit_id, proposal_ref),
    CONSTRAINT capability_requests_id_v7_chk CHECK (substring(capability_request_id::text, 15, 1) = '7'),
    CONSTRAINT capability_requests_proposal_chk CHECK (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'),
    CONSTRAINT capability_requests_kind_chk CHECK (capability_kind IN ('creator.scene.reply', 'codex.delegated-work')),
    CONSTRAINT capability_requests_operation_chk CHECK (
        (capability_kind = 'creator.scene.reply' AND operation_class = 'send') OR
        (capability_kind = 'codex.delegated-work' AND operation_class = 'execute')
    ),
    CONSTRAINT capability_requests_scope_chk CHECK (
        (capability_kind = 'creator.scene.reply' AND audience_scope = 'creator'
         AND data_scope = 'creator_visible_response' AND purpose = 'respond_to_creator'
         AND workspace_scope IS NULL AND artifact_scope IS NULL AND network_access IS NULL
         AND requested_valid_for_seconds BETWEEN 60 AND 604800
         AND requested_max_uses BETWEEN 1 AND 16
         AND requested_max_payload_bytes BETWEEN 1 AND 65536)
        OR
        (capability_kind = 'codex.delegated-work' AND audience_scope IS NULL
         AND data_scope IS NULL AND purpose = 'delegate_codex_work'
         AND workspace_scope = 'isolated_ephemeral' AND artifact_scope = 'explicit_only'
         AND network_access = false AND requested_valid_for_seconds BETWEEN 60 AND 3600
         AND requested_max_uses = 1 AND requested_max_payload_bytes IS NULL)
    ),
    CONSTRAINT capability_requests_digest_chk CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT capability_requests_status_chk CHECK (current_status IN ('pending', 'granted', 'limited', 'denied', 'revoked', 'expired')),
    CONSTRAINT capability_requests_version_chk CHECK (request_version > 0),
    CONSTRAINT capability_requests_resolution_chk CHECK (
        (current_status = 'pending' AND request_version = 1 AND resolved_by_party_id IS NULL AND resolution_reason_class IS NULL AND resolved_at IS NULL)
        OR
        (current_status <> 'pending' AND request_version > 1 AND resolved_by_party_id IS NOT NULL AND resolved_at IS NOT NULL)
    ),
    CONSTRAINT capability_requests_schema_chk CHECK (schema_version = 1)
);

CREATE INDEX capability_requests_creator_page_idx
    ON armi.capability_requests (creator_party_id, created_at DESC, capability_request_id DESC);
CREATE INDEX capability_requests_pending_idx
    ON armi.capability_requests (current_status, created_at, capability_request_id);

CREATE TABLE armi.capability_request_basis_links (
    capability_request_id uuid NOT NULL REFERENCES armi.capability_requests(capability_request_id),
    context_item_id uuid NOT NULL REFERENCES armi.cognitive_context_items(context_item_id),
    ordinal smallint NOT NULL,
    PRIMARY KEY (capability_request_id, ordinal),
    UNIQUE (capability_request_id, context_item_id),
    CONSTRAINT capability_request_basis_ordinal_chk CHECK (ordinal BETWEEN 1 AND 8)
);

CREATE TABLE armi.capability_request_decisions (
    capability_decision_id uuid PRIMARY KEY,
    capability_request_id uuid NOT NULL REFERENCES armi.capability_requests(capability_request_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    expected_request_version bigint NOT NULL,
    resulting_request_version bigint NOT NULL,
    decision_kind text NOT NULL,
    command_digest text NOT NULL,
    scope_digest text,
    reason_code text,
    decided_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1,
    UNIQUE (capability_request_id, resulting_request_version),
    CONSTRAINT capability_decisions_id_v7_chk CHECK (substring(capability_decision_id::text, 15, 1) = '7'),
    CONSTRAINT capability_decisions_version_chk CHECK (expected_request_version > 0 AND resulting_request_version = expected_request_version + 1),
    CONSTRAINT capability_decisions_kind_chk CHECK (decision_kind IN ('grant', 'limit', 'deny', 'revoke', 'expire')),
    CONSTRAINT capability_decisions_digest_chk CHECK (command_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT capability_decisions_scope_chk CHECK (scope_digest IS NULL OR scope_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT capability_decisions_schema_chk CHECK (schema_version = 1)
);

CREATE TABLE armi.permission_grants (
    grant_id uuid PRIMARY KEY,
    capability_request_id uuid NOT NULL UNIQUE REFERENCES armi.capability_requests(capability_request_id),
    creator_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    capability_id uuid NOT NULL REFERENCES armi.capabilities(capability_id),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    interaction_scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    operation_class text NOT NULL,
    audience_scope text NOT NULL,
    data_scope text NOT NULL,
    purpose text NOT NULL,
    valid_from timestamptz(6) NOT NULL,
    valid_until timestamptz(6) NOT NULL,
    max_uses integer NOT NULL,
    consumed_uses integer NOT NULL DEFAULT 0,
    max_payload_bytes integer NOT NULL,
    scope_digest text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    revoked_at timestamptz(6),
    schema_version smallint NOT NULL DEFAULT 1,
    CONSTRAINT permission_grants_id_v7_chk CHECK (substring(grant_id::text, 15, 1) = '7'),
    CONSTRAINT permission_grants_scope_chk CHECK (
        operation_class = 'send' AND audience_scope = 'creator'
        AND data_scope = 'creator_visible_response' AND purpose = 'respond_to_creator'
        AND valid_until > valid_from AND valid_until <= valid_from + interval '7 days'
        AND max_uses BETWEEN 1 AND 16 AND consumed_uses BETWEEN 0 AND max_uses
        AND max_payload_bytes BETWEEN 1 AND 65536
    ),
    CONSTRAINT permission_grants_digest_chk CHECK (scope_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT permission_grants_status_chk CHECK (status IN ('active', 'revoked', 'expired')),
    CONSTRAINT permission_grants_revoked_chk CHECK (
        (status = 'active' AND revoked_at IS NULL) OR
        (status IN ('revoked', 'expired') AND revoked_at IS NOT NULL)
    ),
    CONSTRAINT permission_grants_schema_chk CHECK (schema_version = 1)
);

ALTER TABLE armi.runtime_recovery_runs
    ADD COLUMN resumable_capability_request_count integer NOT NULL DEFAULT 0
        CHECK (resumable_capability_request_count >= 0);

REVOKE ALL ON TABLE armi.capabilities, armi.capability_requests,
    armi.capability_request_basis_links, armi.capability_request_decisions,
    armi.permission_grants FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.capabilities, armi.capability_requests,
    armi.capability_request_basis_links, armi.capability_request_decisions,
    armi.permission_grants TO armi_runtime;
GRANT INSERT (capability_request_id, subject_commit_id, proposal_ref, subject_id,
    interaction_scene_id, creator_party_id, capability_id, capability_kind,
    operation_class, audience_scope, data_scope, purpose, workspace_scope,
    artifact_scope, network_access, requested_valid_for_seconds,
    requested_max_uses, requested_max_payload_bytes, request_digest, schema_version)
ON armi.capability_requests TO armi_runtime;
GRANT UPDATE (current_status, request_version, resolved_by_party_id,
    resolution_reason_class, resolved_at) ON armi.capability_requests TO armi_runtime;
GRANT INSERT (capability_request_id, context_item_id, ordinal)
ON armi.capability_request_basis_links TO armi_runtime;
GRANT INSERT (capability_decision_id, capability_request_id, creator_party_id,
    expected_request_version, resulting_request_version, decision_kind,
    command_digest, scope_digest, reason_code, schema_version)
ON armi.capability_request_decisions TO armi_runtime;
GRANT INSERT (grant_id, capability_request_id, creator_party_id, capability_id,
    subject_id, interaction_scene_id, operation_class, audience_scope, data_scope,
    purpose, valid_from, valid_until, max_uses, max_payload_bytes, scope_digest,
    schema_version) ON armi.permission_grants TO armi_runtime;
GRANT UPDATE (status, revoked_at) ON armi.permission_grants TO armi_runtime;
GRANT INSERT (resumable_capability_request_count)
ON armi.runtime_recovery_runs TO armi_runtime;
GRANT UPDATE (resumable_capability_request_count)
ON armi.runtime_recovery_runs TO armi_runtime;
