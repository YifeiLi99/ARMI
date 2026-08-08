-- Harden the authoritative relational contract after the frozen baseline.
-- The migration gateway executes this file in one transaction.

ALTER TABLE armi.interaction_scenes
    ADD COLUMN scene_version bigint DEFAULT 1 NOT NULL,
    ADD CONSTRAINT interaction_scenes_scene_version_check CHECK (scene_version > 0);

ALTER TABLE armi.effects ADD COLUMN action_intent_id uuid;

CREATE TABLE armi.runtime_recovery_metrics (
    recovery_run_id uuid NOT NULL,
    metric_kind text NOT NULL,
    metric_value integer NOT NULL,
    CONSTRAINT runtime_recovery_metrics_pkey PRIMARY KEY (recovery_run_id, metric_kind),
    CONSTRAINT runtime_recovery_metrics_run_fkey FOREIGN KEY (recovery_run_id)
        REFERENCES armi.runtime_recovery_runs(recovery_run_id) ON DELETE CASCADE,
    CONSTRAINT runtime_recovery_metrics_value_check CHECK (metric_value >= 0),
    CONSTRAINT runtime_recovery_metrics_kind_check CHECK (metric_kind = ANY (ARRAY[
        'requeued_work_count', 'terminal_work_count', 'requeued_outbox_count',
        'dead_outbox_count', 'resumable_work_count', 'resumable_outbox_count',
        'critical_artifact_count', 'resumable_opportunity_count',
        'resumable_cognitive_episode_count', 'resumable_model_attempt_count',
        'resumable_candidate_validation_count', 'resumable_subject_commit_count',
        'resumable_capability_request_count', 'resumable_response_operation_count',
        'resumable_effect_count', 'resumable_effect_outbox_count',
        'resumable_effect_attempt_count', 'reliable_effect_observation_count',
        'creator_response_delivery_count', 'resumable_web_observation_count',
        'unknown_web_observation_attempt_count', 'resumable_web_research_intent_count',
        'pending_web_evidence_acceptance_count', 'resumable_web_cognition_count',
        'resumable_admin_correction_work_count', 'resumable_codex_task_count',
        'resumable_codex_effect_count', 'pending_codex_result_acceptance_count'
    ]))
);

ALTER TABLE armi.runtime_recovery_metrics OWNER TO armi_owner;
REVOKE ALL ON TABLE armi.runtime_recovery_metrics FROM PUBLIC;
GRANT SELECT ON TABLE armi.runtime_recovery_metrics TO armi_admin;
GRANT SELECT, INSERT, UPDATE (metric_value) ON TABLE armi.runtime_recovery_metrics TO armi_runtime;

-- Deterministic historical normalization.
UPDATE armi.accepted_experiences AS experience
SET experience_kind = 'other_human_input',
    source_perspective = 'other_human_claim'
FROM armi.cognitive_episodes AS episode
WHERE episode.cognitive_episode_id = experience.cognitive_episode_id
  AND episode.purpose = 'consider_other_human_input';

UPDATE armi.action_intent_revisions
SET operation_class = 'send'
WHERE operation_class = 'deliver_local';

UPDATE armi.effects
SET operation_class = 'send'
WHERE operation_class = 'deliver_local';

UPDATE armi.external_evidence
SET interaction_id = NULL
WHERE source_kind IN ('web_search', 'codex_task_source', 'codex_result')
  AND interaction_id IS NOT NULL;

UPDATE armi.effects AS effect
SET action_intent_id = revision.action_intent_id
FROM armi.action_intent_revisions AS revision
WHERE revision.action_intent_revision_id = effect.action_intent_revision_id;

UPDATE armi.local_inbox_deliveries AS delivery
SET payload_bytes = effect.payload_bytes
FROM armi.effects AS effect
WHERE effect.effect_id = delivery.effect_id
  AND delivery.payload_bytes IS NULL;

UPDATE armi.dialogue_decisions AS decision
SET proposal_ref = revision.proposal_ref
FROM armi.action_intents AS intent
JOIN armi.action_intent_revisions AS revision
  ON revision.action_intent_revision_id = intent.current_revision_id
WHERE intent.action_intent_id = decision.action_intent_id
  AND decision.decision_kind = 'reply'
  AND decision.proposal_ref IS NULL;

UPDATE armi.dialogue_decisions AS decision
SET effect_id = operation.effect_id
FROM armi.action_operations AS operation
WHERE operation.dialogue_decision_id = decision.dialogue_decision_id
  AND operation.effect_id IS NOT NULL
  AND decision.effect_id IS NULL;

INSERT INTO armi.runtime_recovery_metrics (recovery_run_id, metric_kind, metric_value)
SELECT run.recovery_run_id, metric.metric_kind, metric.metric_value
FROM armi.runtime_recovery_runs AS run
CROSS JOIN LATERAL (VALUES
    ('requeued_work_count', run.requeued_work_count),
    ('terminal_work_count', run.terminal_work_count),
    ('requeued_outbox_count', run.requeued_outbox_count),
    ('dead_outbox_count', run.dead_outbox_count),
    ('resumable_work_count', run.resumable_work_count),
    ('resumable_outbox_count', run.resumable_outbox_count),
    ('critical_artifact_count', run.critical_artifact_count),
    ('resumable_opportunity_count', run.resumable_opportunity_count),
    ('resumable_cognitive_episode_count', run.resumable_cognitive_episode_count),
    ('resumable_model_attempt_count', run.resumable_model_attempt_count),
    ('resumable_candidate_validation_count', run.resumable_candidate_validation_count),
    ('resumable_subject_commit_count', run.resumable_subject_commit_count),
    ('resumable_capability_request_count', run.resumable_capability_request_count),
    ('resumable_response_operation_count', run.resumable_response_operation_count),
    ('resumable_effect_count', run.resumable_effect_count),
    ('resumable_effect_outbox_count', run.resumable_effect_outbox_count),
    ('resumable_effect_attempt_count', run.resumable_effect_attempt_count),
    ('reliable_effect_observation_count', run.reliable_effect_observation_count),
    ('creator_response_delivery_count', run.creator_response_delivery_count),
    ('resumable_web_observation_count', run.resumable_web_observation_count),
    ('unknown_web_observation_attempt_count', run.unknown_web_observation_attempt_count),
    ('resumable_web_research_intent_count', run.resumable_web_research_intent_count),
    ('pending_web_evidence_acceptance_count', run.pending_web_evidence_acceptance_count),
    ('resumable_web_cognition_count', run.resumable_web_cognition_count),
    ('resumable_admin_correction_work_count', run.resumable_admin_correction_work_count),
    ('resumable_codex_task_count', run.resumable_codex_task_count),
    ('resumable_codex_effect_count', run.resumable_codex_effect_count),
    ('pending_codex_result_acceptance_count', run.pending_codex_result_acceptance_count)
) AS metric(metric_kind, metric_value);

-- Refuse ambiguous or corrupt history instead of guessing.
DO $preflight$
BEGIN
    IF EXISTS (SELECT 1 FROM armi.effects WHERE action_intent_id IS NULL OR operation_id IS NULL) THEN
        RAISE EXCEPTION 'DB-MIGRATION-EFFECT-OWNER';
    END IF;
    IF EXISTS (SELECT 1 FROM armi.local_inbox_deliveries WHERE payload_bytes IS NULL) THEN
        RAISE EXCEPTION 'DB-MIGRATION-LOCAL-INBOX-PAYLOAD';
    END IF;
    IF EXISTS (
        SELECT 1 FROM armi.dialogue_decisions
        WHERE subject_id IS NULL OR scene_id IS NULL OR context_party_id IS NULL
           OR (decision_kind = 'reply' AND (proposal_ref IS NULL OR action_intent_id IS NULL))
           OR (decision_kind <> 'reply' AND (action_intent_id IS NOT NULL OR effect_id IS NOT NULL))
    ) THEN
        RAISE EXCEPTION 'DB-MIGRATION-DIALOGUE-SHAPE';
    END IF;
    IF EXISTS (
        SELECT 1 FROM armi.action_operations
        WHERE (operation_kind = 'codex_delegation' AND (action_intent_id IS NULL OR dialogue_decision_id IS NOT NULL))
           OR (operation_kind = 'party_response' AND dialogue_decision_id IS NULL)
           OR (action_intent_id IS NULL AND NOT (phase = 'terminal' AND outcome = 'no_action'))
           OR ((effect_id IS NULL)::integer + (effect_registration_digest IS NULL)::integer
               + (effect_registered_at IS NULL)::integer NOT IN (0, 3))
    ) THEN
        RAISE EXCEPTION 'DB-MIGRATION-OPERATION-SHAPE';
    END IF;
END
$preflight$;

ALTER TABLE armi.local_inbox_deliveries ALTER COLUMN payload_bytes SET NOT NULL;
ALTER TABLE armi.effects ALTER COLUMN action_intent_id SET NOT NULL;
ALTER TABLE armi.effects ALTER COLUMN operation_id SET NOT NULL;
ALTER TABLE armi.dialogue_decisions ALTER COLUMN subject_id SET NOT NULL;
ALTER TABLE armi.dialogue_decisions ALTER COLUMN scene_id SET NOT NULL;
ALTER TABLE armi.dialogue_decisions ALTER COLUMN context_party_id SET NOT NULL;

-- Replace NULL-leaky permission shapes with total boolean contracts.
ALTER TABLE armi.capability_requests DROP CONSTRAINT capability_requests_scope_chk;
ALTER TABLE armi.capability_requests ADD CONSTRAINT capability_requests_scope_chk CHECK (
    (capability_kind = 'creator.scene.reply'
     AND audience_scope IS NOT NULL AND audience_scope = 'creator'
     AND data_scope IS NOT NULL AND data_scope = 'creator_visible_response'
     AND purpose = 'respond_to_creator'
     AND workspace_scope IS NULL AND artifact_scope IS NULL AND network_access IS NULL
     AND requested_valid_for_seconds BETWEEN 60 AND 604800
     AND requested_max_uses BETWEEN 1 AND 16
     AND requested_max_payload_bytes IS NOT NULL
     AND requested_max_payload_bytes BETWEEN 1 AND 65536)
 OR (capability_kind = 'codex.delegated-work'
     AND audience_scope IS NULL AND data_scope IS NULL
     AND purpose = 'delegate_codex_work'
     AND workspace_scope IS NOT NULL AND workspace_scope = 'isolated_ephemeral'
     AND artifact_scope IS NOT NULL AND artifact_scope = 'explicit_only'
     AND network_access IS NOT NULL AND network_access = false
     AND requested_valid_for_seconds BETWEEN 60 AND 3600
     AND requested_max_uses = 1 AND requested_max_payload_bytes IS NULL)
);

ALTER TABLE armi.permission_grants DROP CONSTRAINT permission_grants_scope_chk;
ALTER TABLE armi.permission_grants ADD CONSTRAINT permission_grants_scope_chk CHECK (
    (operation_class = 'send'
     AND audience_scope IS NOT NULL AND audience_scope = 'creator'
     AND data_scope IS NOT NULL AND data_scope = 'creator_visible_response'
     AND purpose = 'respond_to_creator'
     AND workspace_scope IS NULL AND artifact_scope IS NULL AND network_access IS NULL
     AND valid_until > valid_from AND valid_until <= valid_from + interval '7 days'
     AND max_uses BETWEEN 1 AND 16 AND consumed_uses BETWEEN 0 AND max_uses
     AND max_payload_bytes IS NOT NULL AND max_payload_bytes BETWEEN 1 AND 65536)
 OR (operation_class = 'execute'
     AND audience_scope IS NULL AND data_scope IS NULL
     AND purpose = 'delegate_codex_work'
     AND workspace_scope IS NOT NULL AND workspace_scope = 'isolated_ephemeral'
     AND artifact_scope IS NOT NULL AND artifact_scope = 'explicit_only'
     AND network_access IS NOT NULL AND network_access = false
     AND valid_until > valid_from AND valid_until <= valid_from + interval '1 hour'
     AND max_uses = 1 AND consumed_uses BETWEEN 0 AND 1
     AND max_payload_bytes IS NULL)
);

ALTER TABLE armi.accepted_experiences
    DROP CONSTRAINT accepted_experiences_experience_kind_check,
    DROP CONSTRAINT accepted_experiences_source_perspective_check,
    DROP CONSTRAINT accepted_experiences_source_pair_check;
ALTER TABLE armi.accepted_experiences
    ADD CONSTRAINT accepted_experiences_experience_kind_check CHECK
        (experience_kind IN ('creator_input', 'web_observation', 'codex_observation', 'other_human_input')),
    ADD CONSTRAINT accepted_experiences_source_perspective_check CHECK
        (source_perspective IN ('creator_claim', 'web_claim', 'codex_observation', 'other_human_claim')),
    ADD CONSTRAINT accepted_experiences_source_pair_check CHECK (
        (experience_kind = 'creator_input' AND source_perspective = 'creator_claim')
     OR (experience_kind = 'web_observation' AND source_perspective = 'web_claim')
     OR (experience_kind = 'codex_observation' AND source_perspective = 'codex_observation')
     OR (experience_kind = 'other_human_input' AND source_perspective = 'other_human_claim')
    );

ALTER TABLE armi.action_intents DROP CONSTRAINT action_intents_shape_check;
ALTER TABLE armi.action_intents ADD CONSTRAINT action_intents_shape_check CHECK (
    (action_kind = 'party_response' AND purpose IN ('respond_to_creator', 'respond_to_other_human'))
 OR (action_kind = 'codex_delegation' AND purpose = 'delegate_codex_work')
);

ALTER TABLE armi.action_intent_revisions ADD CONSTRAINT action_intent_revisions_family_check CHECK (
    (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL AND response_bytes IS NOT NULL AND media_type IS NOT NULL
     AND capability_kind = 'creator.scene.reply' AND operation_class = 'send'
     AND audience_scope = 'creator' AND data_scope = 'creator_visible_response' AND purpose = 'respond_to_creator'
     AND codex_task_source_id IS NULL AND task_manifest_digest IS NULL AND validator_id IS NULL)
 OR (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL AND response_bytes IS NOT NULL AND media_type IS NOT NULL
     AND capability_kind = 'local.other-human-inbox.deliver' AND operation_class = 'send'
     AND audience_scope = 'other_human' AND data_scope = 'declared_party_response' AND purpose = 'respond_to_other_human'
     AND codex_task_source_id IS NULL AND task_manifest_digest IS NULL AND validator_id IS NULL)
 OR (response_artifact_id IS NULL AND response_digest IS NULL AND response_bytes IS NULL AND media_type IS NULL
     AND capability_kind = 'codex.delegated-work' AND operation_class = 'execute'
     AND audience_scope IS NULL AND data_scope IS NULL AND purpose = 'delegate_codex_work'
     AND codex_task_source_id IS NOT NULL AND task_manifest_digest IS NOT NULL
     AND task_manifest_digest ~ '^sha256:[0-9a-f]{64}$' AND validator_id IS NOT NULL)
);

ALTER TABLE armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_shape_check CHECK (
    (decision_kind = 'reply' AND proposal_ref IS NOT NULL AND action_intent_id IS NOT NULL)
 OR (decision_kind <> 'reply' AND action_intent_id IS NULL AND effect_id IS NULL)
);

ALTER TABLE armi.action_operations ADD CONSTRAINT action_operations_owner_shape_check CHECK (
    (operation_kind = 'codex_delegation' AND action_intent_id IS NOT NULL AND dialogue_decision_id IS NULL)
 OR (operation_kind = 'party_response' AND dialogue_decision_id IS NOT NULL
     AND (action_intent_id IS NOT NULL OR (phase = 'terminal' AND outcome = 'no_action')))
);
ALTER TABLE armi.action_operations ADD CONSTRAINT action_operations_effect_registration_check CHECK (
    (effect_id IS NULL AND effect_registration_digest IS NULL AND effect_registered_at IS NULL)
 OR (effect_id IS NOT NULL AND effect_registration_digest IS NOT NULL
     AND effect_registration_digest ~ '^sha256:[0-9a-f]{64}$' AND effect_registered_at IS NOT NULL)
);
ALTER TABLE armi.action_operations ADD CONSTRAINT action_operations_phase_effect_check CHECK (
    (phase IN ('admission_pending', 'admitted') AND effect_id IS NULL)
 OR (phase IN ('effect_registered', 'dispatching', 'result_pending') AND effect_id IS NOT NULL)
 OR phase = 'terminal'
);

ALTER TABLE armi.effects ADD CONSTRAINT effects_family_check CHECK (
    (effect_kind = 'creator_response' AND capability_kind = 'creator.scene.reply' AND operation_class = 'send'
     AND audience_scope = 'creator' AND data_scope = 'creator_visible_response' AND purpose = 'respond_to_creator'
     AND authorization_basis = 'creator_grant' AND destination_kind = 'creator_inbox'
     AND destination_party_id IS NOT NULL AND policy_decision_id IS NOT NULL)
 OR (effect_kind = 'local_inbox_delivery' AND capability_kind = 'local.other-human-inbox.deliver' AND operation_class = 'send'
     AND audience_scope = 'other_human' AND data_scope = 'declared_party_response' AND purpose = 'respond_to_other_human'
     AND authorization_basis = 'runtime_builtin' AND destination_kind = 'other_human_inbox'
     AND destination_party_id IS NOT NULL AND policy_decision_id IS NULL)
 OR (effect_kind = 'codex_delegation' AND capability_kind = 'codex.delegated-work' AND operation_class = 'execute'
     AND audience_scope IS NULL AND data_scope IS NULL AND purpose = 'delegate_codex_work'
     AND authorization_basis = 'creator_grant' AND destination_kind = 'codex_workspace'
     AND destination_party_id IS NOT NULL AND policy_decision_id IS NOT NULL)
);
ALTER TABLE armi.effects ADD CONSTRAINT effects_lifecycle_check CHECK (
    (status = 'registered' AND verification_status = 'not_started'
     AND current_attempt_id IS NULL AND current_observation_id IS NULL
     AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
 OR (status = 'dispatching' AND verification_status = 'pending'
     AND current_attempt_id IS NOT NULL AND current_observation_id IS NULL
     AND settlement_digest IS NULL AND settled_at IS NULL AND cancelled_at IS NULL)
 OR (status IN ('completed', 'failed') AND verification_status = 'verified'
     AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
     AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
 OR (status = 'unknown' AND verification_status = 'inconclusive'
     AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
     AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at IS NULL)
 OR (status = 'cancelled' AND verification_status = 'verified'
     AND current_attempt_id IS NOT NULL AND current_observation_id IS NOT NULL
     AND settlement_digest IS NOT NULL AND settled_at IS NOT NULL AND cancelled_at = settled_at)
);
ALTER TABLE armi.effects ADD CONSTRAINT effects_payload_bytes_check CHECK (payload_bytes BETWEEN 1 AND 65536);
ALTER TABLE armi.effects ADD CONSTRAINT effects_settlement_digest_check CHECK
    (settlement_digest IS NULL OR settlement_digest ~ '^sha256:[0-9a-f]{64}$');

ALTER TABLE armi.effect_attempts ADD CONSTRAINT effect_attempts_attempt_owner_key UNIQUE (effect_attempt_id, effect_id);
ALTER TABLE armi.effect_observations ADD CONSTRAINT effect_observations_owner_key UNIQUE
    (effect_observation_id, effect_id, effect_attempt_id);
ALTER TABLE armi.action_operations ADD CONSTRAINT action_operations_effect_owner_key UNIQUE
    (operation_id, action_intent_id, subject_id, scene_id, context_party_id);
ALTER TABLE armi.policy_decisions ADD CONSTRAINT policy_decisions_effect_owner_key UNIQUE
    (policy_decision_id, action_intent_revision_id, operation_id);
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_episode_owner_key UNIQUE (opportunity_id, subject_id);

ALTER TABLE armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_artifact_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id),
    ADD CONSTRAINT action_intent_revisions_candidate_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref),
    ADD CONSTRAINT action_intent_revisions_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id),
    ADD CONSTRAINT action_intent_revisions_codex_source_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);

ALTER TABLE armi.dialogue_decisions
    ADD CONSTRAINT dialogue_decisions_episode_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    ADD CONSTRAINT dialogue_decisions_candidate_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref),
    ADD CONSTRAINT dialogue_decisions_application_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    ADD CONSTRAINT dialogue_decisions_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id),
    ADD CONSTRAINT dialogue_decisions_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id),
    ADD CONSTRAINT dialogue_decisions_scene_owner_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id),
    ADD CONSTRAINT dialogue_decisions_intent_owner_fkey FOREIGN KEY (action_intent_id, subject_id, scene_id, context_party_id) REFERENCES armi.action_intents(action_intent_id, subject_id, scene_id, context_party_id),
    ADD CONSTRAINT dialogue_decisions_effect_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id);

ALTER TABLE armi.action_operations
    ADD CONSTRAINT action_operations_scene_owner_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id),
    ADD CONSTRAINT action_operations_intent_owner_fkey FOREIGN KEY (action_intent_id, subject_id, scene_id, context_party_id) REFERENCES armi.action_intents(action_intent_id, subject_id, scene_id, context_party_id),
    ADD CONSTRAINT action_operations_dialogue_fkey FOREIGN KEY (dialogue_decision_id) REFERENCES armi.dialogue_decisions(dialogue_decision_id),
    ADD CONSTRAINT action_operations_admission_work_fkey FOREIGN KEY (admission_work_id) REFERENCES armi.durable_work(work_id),
    ADD CONSTRAINT action_operations_registration_work_fkey FOREIGN KEY (registration_work_id) REFERENCES armi.durable_work(work_id),
    ADD CONSTRAINT action_operations_grant_fkey FOREIGN KEY (matched_grant_id) REFERENCES armi.permission_grants(grant_id),
    ADD CONSTRAINT action_operations_policy_fkey FOREIGN KEY (current_policy_decision_id) REFERENCES armi.policy_decisions(policy_decision_id),
    ADD CONSTRAINT action_operations_effect_fkey FOREIGN KEY (effect_id) REFERENCES armi.effects(effect_id),
    ADD CONSTRAINT action_operations_admission_work_key UNIQUE (admission_work_id),
    ADD CONSTRAINT action_operations_registration_work_key UNIQUE (registration_work_id);

ALTER TABLE armi.effects
    ADD CONSTRAINT effects_revision_owner_fkey FOREIGN KEY (action_intent_revision_id, action_intent_id) REFERENCES armi.action_intent_revisions(action_intent_revision_id, action_intent_id),
    ADD CONSTRAINT effects_operation_owner_fkey FOREIGN KEY (operation_id, action_intent_id, subject_id, scene_id, context_party_id) REFERENCES armi.action_operations(operation_id, action_intent_id, subject_id, scene_id, context_party_id),
    ADD CONSTRAINT effects_policy_owner_fkey FOREIGN KEY (policy_decision_id, action_intent_revision_id, operation_id) REFERENCES armi.policy_decisions(policy_decision_id, action_intent_revision_id, operation_id),
    ADD CONSTRAINT effects_payload_artifact_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id),
    ADD CONSTRAINT effects_current_attempt_fkey FOREIGN KEY (current_attempt_id, effect_id) REFERENCES armi.effect_attempts(effect_attempt_id, effect_id),
    ADD CONSTRAINT effects_current_observation_fkey FOREIGN KEY (current_observation_id, effect_id, current_attempt_id) REFERENCES armi.effect_observations(effect_observation_id, effect_id, effect_attempt_id);

ALTER TABLE armi.effect_observations
    DROP CONSTRAINT effect_observations_effect_attempt_id_fkey,
    ADD CONSTRAINT effect_observations_attempt_owner_fkey FOREIGN KEY (effect_attempt_id, effect_id) REFERENCES armi.effect_attempts(effect_attempt_id, effect_id);

ALTER TABLE armi.external_evidence DROP CONSTRAINT external_evidence_source_identity_check;
ALTER TABLE armi.external_evidence ADD CONSTRAINT external_evidence_source_identity_check CHECK (
    (source_kind IN ('creator_input', 'other_human_input') AND interaction_id IS NOT NULL
     AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL AND codex_task_source_id IS NULL AND codex_verification_id IS NULL)
 OR (source_kind = 'web_search' AND interaction_id IS NULL
     AND web_observation_request_id IS NOT NULL AND observation_attempt_id IS NOT NULL AND codex_task_source_id IS NULL AND codex_verification_id IS NULL)
 OR (source_kind = 'codex_task_source' AND interaction_id IS NULL
     AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL AND codex_task_source_id IS NOT NULL AND codex_verification_id IS NULL)
 OR (source_kind = 'codex_result' AND interaction_id IS NULL
     AND web_observation_request_id IS NULL AND observation_attempt_id IS NULL AND codex_task_source_id IS NULL AND codex_verification_id IS NOT NULL)
);
ALTER TABLE armi.external_evidence
    ADD CONSTRAINT external_evidence_web_request_fkey FOREIGN KEY (web_observation_request_id) REFERENCES armi.web_observation_requests(web_observation_request_id),
    ADD CONSTRAINT external_evidence_observation_attempt_fkey FOREIGN KEY (observation_attempt_id) REFERENCES armi.observation_attempts(observation_attempt_id),
    ADD CONSTRAINT external_evidence_codex_source_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id),
    ADD CONSTRAINT external_evidence_codex_verification_fkey FOREIGN KEY (codex_verification_id) REFERENCES armi.codex_verification_results(codex_verification_id);

ALTER TABLE armi.opportunities
    ADD CONSTRAINT opportunities_predecessor_fkey FOREIGN KEY (predecessor_opportunity_id) REFERENCES armi.opportunities(opportunity_id),
    ADD CONSTRAINT opportunities_scene_owner_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id),
    ADD CONSTRAINT opportunities_activity_owner_fkey FOREIGN KEY (activity_id, subject_id) REFERENCES armi.activities(activity_id, subject_id);

ALTER TABLE armi.cognitive_episodes
    ADD CONSTRAINT cognitive_episodes_opportunity_owner_fkey FOREIGN KEY (opportunity_id, subject_id) REFERENCES armi.opportunities(opportunity_id, subject_id),
    ADD CONSTRAINT cognitive_episodes_scene_owner_fkey FOREIGN KEY (scene_id, subject_id, context_party_id) REFERENCES armi.interaction_scenes(scene_id, subject_id, primary_party_id),
    ADD CONSTRAINT cognitive_episodes_bundle_fkey FOREIGN KEY (bundle_activation_id) REFERENCES armi.runtime_bundle_activations(bundle_activation_id),
    ADD CONSTRAINT cognitive_episodes_context_artifact_fkey FOREIGN KEY (context_manifest_artifact_id) REFERENCES armi.artifacts(artifact_id),
    ADD CONSTRAINT cognitive_episodes_compiled_artifact_fkey FOREIGN KEY (compiled_context_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE armi.activity_decisions
    ADD CONSTRAINT activity_decisions_opportunity_fkey FOREIGN KEY (opportunity_id) REFERENCES armi.opportunities(opportunity_id),
    ADD CONSTRAINT activity_decisions_episode_fkey FOREIGN KEY (cognitive_episode_id) REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    ADD CONSTRAINT activity_decisions_validation_fkey FOREIGN KEY (candidate_validation_id) REFERENCES armi.cognitive_candidate_validations(candidate_validation_id),
    ADD CONSTRAINT activity_decisions_application_fkey FOREIGN KEY (candidate_application_id) REFERENCES armi.cognitive_candidate_applications(candidate_application_id),
    ADD CONSTRAINT activity_decisions_expected_revision_fkey FOREIGN KEY (expected_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    ADD CONSTRAINT activity_decisions_result_revision_fkey FOREIGN KEY (result_revision_id, activity_id) REFERENCES armi.activity_revisions(activity_revision_id, activity_id),
    ADD CONSTRAINT activity_decisions_output_material_fkey FOREIGN KEY (output_material_id) REFERENCES armi.life_materials(life_material_id);

ALTER TABLE armi.local_inbox_deliveries
    ADD CONSTRAINT local_inbox_deliveries_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id),
    ADD CONSTRAINT local_inbox_deliveries_artifact_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);

ALTER TABLE armi.action_intent_revisions DROP CONSTRAINT action_intent_revisions_action_intent_revision_id_action_intent_id_key;
ALTER TABLE armi.activities DROP CONSTRAINT activities_activity_id_current_revision_id_key;
ALTER TABLE armi.life_materials DROP CONSTRAINT life_materials_life_material_id_current_revision_id_key;
ALTER TABLE armi.relationships DROP CONSTRAINT relationships_relationship_id_current_revision_id_key;

CREATE INDEX effect_outbox_items_ready_claim_idx
    ON armi.effect_outbox_items (available_at, effect_outbox_item_id) WHERE status = 'ready';
CREATE INDEX effect_outbox_items_claim_expiry_idx
    ON armi.effect_outbox_items (claim_expires_at, effect_outbox_item_id) WHERE status = 'claimed';
CREATE INDEX effects_unknown_settlement_idx
    ON armi.effects (settled_at, effect_id) WHERE status = 'unknown';
CREATE INDEX cognitive_episodes_subject_purpose_recent_idx
    ON armi.cognitive_episodes (subject_id, purpose, created_at DESC, cognitive_episode_id DESC);

-- Move recovery counters out of the parent after their values are copied.
ALTER TABLE armi.runtime_recovery_runs
    DROP COLUMN requeued_work_count,
    DROP COLUMN terminal_work_count,
    DROP COLUMN requeued_outbox_count,
    DROP COLUMN dead_outbox_count,
    DROP COLUMN resumable_work_count,
    DROP COLUMN resumable_outbox_count,
    DROP COLUMN critical_artifact_count,
    DROP COLUMN resumable_opportunity_count,
    DROP COLUMN resumable_cognitive_episode_count,
    DROP COLUMN resumable_model_attempt_count,
    DROP COLUMN resumable_candidate_validation_count,
    DROP COLUMN resumable_subject_commit_count,
    DROP COLUMN resumable_capability_request_count,
    DROP COLUMN resumable_response_operation_count,
    DROP COLUMN resumable_effect_count,
    DROP COLUMN resumable_effect_outbox_count,
    DROP COLUMN resumable_effect_attempt_count,
    DROP COLUMN reliable_effect_observation_count,
    DROP COLUMN creator_response_delivery_count,
    DROP COLUMN resumable_web_observation_count,
    DROP COLUMN unknown_web_observation_attempt_count,
    DROP COLUMN resumable_web_research_intent_count,
    DROP COLUMN pending_web_evidence_acceptance_count,
    DROP COLUMN resumable_web_cognition_count,
    DROP COLUMN resumable_admin_correction_work_count,
    DROP COLUMN resumable_codex_task_count,
    DROP COLUMN resumable_codex_effect_count,
    DROP COLUMN pending_codex_result_acceptance_count;

-- The fixed database-only integer version never carried compatibility semantics.
DO $drop_versions$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'armi' AND column_name = 'schema_version'
        ORDER BY table_name
    LOOP
        EXECUTE format('ALTER TABLE armi.%I DROP COLUMN schema_version', item.table_name);
    END LOOP;
END
$drop_versions$;

GRANT UPDATE (scene_version) ON TABLE armi.interaction_scenes TO armi_runtime;
GRANT INSERT (action_intent_id) ON TABLE armi.effects TO armi_runtime;
