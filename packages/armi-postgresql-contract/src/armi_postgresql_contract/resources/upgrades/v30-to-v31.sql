-- Merge the single committed intent revision without rewriting effects or artifacts.
-- Unexpected historical revisions are refused transactionally, never discarded.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM armi.action_intents i
        LEFT JOIN armi.action_intent_revisions r ON r.action_intent_id=i.action_intent_id
        GROUP BY i.action_intent_id
        HAVING count(r.action_intent_revision_id) <> 1
            OR bool_or(r.action_intent_revision_id IS DISTINCT FROM i.current_revision_id)
            OR bool_or(r.revision_no <> 1 OR r.purpose IS DISTINCT FROM i.purpose)
    ) THEN
        RAISE EXCEPTION 'DB-UPGRADE-ACTION-INTENT-HISTORY';
    END IF;
END $$;
ALTER TABLE armi.action_intents ADD COLUMN response_artifact_id uuid;
ALTER TABLE armi.action_intents ADD COLUMN response_digest text;
ALTER TABLE armi.action_intents ADD COLUMN response_bytes integer;
ALTER TABLE armi.action_intents ADD COLUMN media_type text;
ALTER TABLE armi.action_intents ADD COLUMN capability_kind text;
ALTER TABLE armi.action_intents ADD COLUMN operation_class text;
ALTER TABLE armi.action_intents ADD COLUMN audience_scope text;
ALTER TABLE armi.action_intents ADD COLUMN data_scope text;
ALTER TABLE armi.action_intents ADD COLUMN candidate_validation_id uuid;
ALTER TABLE armi.action_intents ADD COLUMN proposal_ref text;
ALTER TABLE armi.action_intents ADD COLUMN subject_commit_id uuid;
ALTER TABLE armi.action_intents ADD COLUMN codex_task_source_id uuid;
ALTER TABLE armi.action_intents ADD COLUMN task_manifest_digest text;
UPDATE armi.action_intents i SET
    response_artifact_id=r.response_artifact_id,
    response_digest=r.response_digest,
    response_bytes=r.response_bytes,
    media_type=r.media_type,
    capability_kind=r.capability_kind,
    operation_class=r.operation_class,
    audience_scope=r.audience_scope,
    data_scope=r.data_scope,
    candidate_validation_id=r.candidate_validation_id,
    proposal_ref=r.proposal_ref,
    subject_commit_id=r.subject_commit_id,
    codex_task_source_id=r.codex_task_source_id,
    task_manifest_digest=r.task_manifest_digest
FROM armi.action_intent_revisions r WHERE r.action_intent_id=i.action_intent_id;
ALTER TABLE armi.action_intents ALTER COLUMN capability_kind SET NOT NULL;
ALTER TABLE armi.action_intents ALTER COLUMN operation_class SET NOT NULL;
ALTER TABLE armi.action_intents ALTER COLUMN candidate_validation_id SET NOT NULL;
ALTER TABLE armi.action_intents ALTER COLUMN proposal_ref SET NOT NULL;
ALTER TABLE armi.action_intents ALTER COLUMN subject_commit_id SET NOT NULL;
ALTER TABLE armi.action_intents DROP CONSTRAINT action_intents_current_revision_fkey;
ALTER TABLE armi.action_intents DROP COLUMN current_revision_id;
ALTER TABLE armi.effects DROP CONSTRAINT effects_revision_fkey;
ALTER TABLE armi.effects DROP CONSTRAINT effects_revision_owner_fkey;
ALTER TABLE armi.effects DROP CONSTRAINT effects_revision_key;
ALTER TABLE armi.effects DROP CONSTRAINT effects_origin_check;
ALTER TABLE armi.effects DROP COLUMN action_intent_revision_id;
DROP TABLE armi.action_intent_revisions;
ALTER TABLE armi.action_intents ADD CONSTRAINT action_intents_bytes_check CHECK (((response_bytes IS NULL) OR ((response_bytes >= 1) AND (response_bytes <= 65536))));
ALTER TABLE armi.action_intents ADD CONSTRAINT action_intents_digest_check CHECK (((response_digest IS NULL) OR (response_digest ~ '^sha256:[0-9a-f]{64}$'::text)));
ALTER TABLE armi.action_intents ADD CONSTRAINT action_intents_family_check CHECK ((((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'local.other-human-inbox.deliver'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'external.group.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'social_group'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL)) OR ((response_artifact_id IS NOT NULL) AND (response_digest IS NOT NULL) AND (response_bytes IS NOT NULL) AND (media_type IS NOT NULL) AND (capability_kind = 'external.private.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (codex_task_source_id IS NULL) AND (task_manifest_digest IS NULL)) OR ((response_artifact_id IS NULL) AND (response_digest IS NULL) AND (response_bytes IS NULL) AND (media_type IS NULL) AND (capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (codex_task_source_id IS NOT NULL) AND (task_manifest_digest IS NOT NULL) AND (task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'::text))));
ALTER TABLE armi.action_intents ADD CONSTRAINT action_intents_response_shape_check CHECK ((((response_artifact_id IS NULL) = (response_digest IS NULL)) AND ((response_digest IS NULL) = (response_bytes IS NULL)) AND ((response_bytes IS NULL) = (media_type IS NULL))));
ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_artifact_fkey FOREIGN KEY (response_artifact_id) REFERENCES armi.artifacts(artifact_id);
ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_candidate_fkey FOREIGN KEY (candidate_validation_id, proposal_ref) REFERENCES armi.cognitive_candidate_validation_items(candidate_validation_id, proposal_ref);
ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_codex_source_fkey FOREIGN KEY (codex_task_source_id) REFERENCES armi.codex_task_sources(codex_task_source_id);
ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_codex_source_key UNIQUE (codex_task_source_id);
ALTER TABLE ONLY armi.action_intents
    ADD CONSTRAINT action_intents_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);
ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_action_intent_key UNIQUE (action_intent_id);
ALTER TABLE armi.effects ADD CONSTRAINT effects_origin_check CHECK ((system_notification_id IS NOT NULL AND action_intent_id IS NULL) OR (system_notification_id IS NULL AND action_intent_id IS NOT NULL));
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v31';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v31');
REVOKE UPDATE ON armi.action_intents FROM armi_runtime;
