-- Transfer Mind ownership without inventing revisions or rewriting historical facts.
CREATE TABLE armi.mind_heads (
    subject_id uuid NOT NULL,
    current_revision_id uuid NOT NULL,
    mind_version bigint NOT NULL,
    CONSTRAINT mind_heads_mind_version_check CHECK ((mind_version > 0))
);

CREATE TABLE armi.mind_revisions (
    mind_revision_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    mind_version bigint NOT NULL,
    previous_revision_id uuid,
    origin_kind text NOT NULL,
    origin_ref uuid NOT NULL,
    subject_commit_id uuid,
    semantic_payload jsonb NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT clock_timestamp() NOT NULL,
    proposal_ref text,
    data_rights_redacted_at timestamp(6) with time zone,
    admin_change_id uuid,
    CONSTRAINT mind_revisions_mind_revision_id_check CHECK ((uuid_extract_version(mind_revision_id) = 7)),
    CONSTRAINT mind_revisions_mind_version_check CHECK ((mind_version > 0)),
    CONSTRAINT mind_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction'),
    CONSTRAINT mind_revisions_origin_check CHECK ((((origin_kind = 'bootstrap'::text) AND (mind_version = 1) AND (previous_revision_id IS NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)) OR ((origin_kind = 'subject_commit'::text) AND (mind_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NOT NULL) AND (proposal_ref IS NOT NULL)) OR ((origin_kind = ANY (ARRAY['admin_correction'::text,'module_migration'::text,'data_rights'::text])) AND (mind_version > 1) AND (previous_revision_id IS NOT NULL) AND (subject_commit_id IS NULL) AND (proposal_ref IS NULL)))),
    CONSTRAINT mind_revisions_origin_kind_check CHECK ((origin_kind = ANY (ARRAY['bootstrap'::text, 'subject_commit'::text, 'admin_correction'::text, 'module_migration'::text, 'data_rights'::text]))),
    CONSTRAINT mind_revisions_origin_ref_check CHECK ((uuid_extract_version(origin_ref) = 7)),
    CONSTRAINT mind_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT mind_revisions_proposal_ref_check CHECK (((proposal_ref IS NULL) OR (proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text))),
    CONSTRAINT mind_revisions_semantic_payload_check CHECK ((jsonb_typeof(semantic_payload) = 'object'::text))
);

ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_pkey PRIMARY KEY (mind_revision_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_owner_key UNIQUE (mind_revision_id,subject_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_version_key UNIQUE (subject_id,mind_version);
ALTER TABLE armi.mind_heads ADD CONSTRAINT mind_heads_pkey PRIMARY KEY (subject_id);
ALTER TABLE armi.mind_heads ADD CONSTRAINT mind_heads_revision_fkey FOREIGN KEY (current_revision_id,subject_id) REFERENCES armi.mind_revisions(mind_revision_id,subject_id);
ALTER TABLE armi.mind_heads ADD CONSTRAINT mind_heads_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_previous_fkey FOREIGN KEY (previous_revision_id,subject_id) REFERENCES armi.mind_revisions(mind_revision_id,subject_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_commit_fkey FOREIGN KEY (subject_commit_id) REFERENCES armi.subject_commits(subject_commit_id);
ALTER TABLE armi.mind_revisions ADD CONSTRAINT mind_revisions_admin_change_fkey FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX mind_revisions_payload_trgm_idx ON armi.mind_revisions USING gin ((semantic_payload::text) armi_extensions.gin_trgm_ops);

INSERT INTO armi.mind_revisions (mind_revision_id,subject_id,mind_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,semantic_payload,privacy_scope,created_at,proposal_ref,data_rights_redacted_at,admin_change_id)
SELECT component_revision_id,subject_id,component_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,semantic_payload,privacy_scope,created_at,proposal_ref,data_rights_redacted_at,admin_change_id FROM armi.subject_component_revisions WHERE component_kind='mind';
INSERT INTO armi.mind_heads (subject_id,current_revision_id,mind_version)
SELECT subject_id,current_revision_id,component_version FROM armi.subject_component_heads WHERE component_kind='mind';
DO $migration$
BEGIN
  IF EXISTS ((SELECT component_revision_id,subject_id,component_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,semantic_payload,privacy_scope,created_at,proposal_ref,data_rights_redacted_at,admin_change_id FROM armi.subject_component_revisions WHERE component_kind='mind')
             EXCEPT (SELECT mind_revision_id,subject_id,mind_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,semantic_payload,privacy_scope,created_at,proposal_ref,data_rights_redacted_at,admin_change_id FROM armi.mind_revisions))
     OR EXISTS ((SELECT subject_id,current_revision_id,component_version FROM armi.subject_component_heads WHERE component_kind='mind')
                EXCEPT (SELECT subject_id,current_revision_id,mind_version FROM armi.mind_heads)) THEN
    RAISE EXCEPTION 'DB-UPGRADE-MIND-CONTINUITY';
  END IF;
END
$migration$;
DELETE FROM armi.subject_component_heads WHERE component_kind='mind';
DELETE FROM armi.subject_component_revisions WHERE component_kind='mind';
SET CONSTRAINTS armi.subject_component_revisions_admin_change_fk IMMEDIATE;
ALTER TABLE armi.subject_component_heads DROP CONSTRAINT subject_component_heads_component_kind_check;
ALTER TABLE armi.subject_component_heads ADD CONSTRAINT subject_component_heads_component_kind_check CHECK (component_kind IN ('self','life_mode'));
ALTER TABLE armi.subject_component_revisions DROP CONSTRAINT subject_component_revisions_component_kind_check;
ALTER TABLE armi.subject_component_revisions ADD CONSTRAINT subject_component_revisions_component_kind_check CHECK (component_kind IN ('self','life_mode'));
SET CONSTRAINTS armi.subject_component_revisions_admin_change_fk DEFERRED;
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v24';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v24');
