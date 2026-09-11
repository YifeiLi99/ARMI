ALTER TABLE armi.schema_baseline_identity
    DROP CONSTRAINT schema_baseline_identity_value_check;
ALTER TABLE armi.schema_baseline_identity
    ADD CONSTRAINT schema_baseline_identity_value_check
    CHECK (baseline_identity = 'armi.schema-baseline.v17'::text) NOT VALID;
UPDATE armi.schema_baseline_identity
    SET baseline_identity = 'armi.schema-baseline.v17';
ALTER TABLE armi.schema_baseline_identity
    VALIDATE CONSTRAINT schema_baseline_identity_value_check;

ALTER TABLE armi.subjective_memory_revisions ALTER COLUMN subject_commit_id DROP NOT NULL;
ALTER TABLE armi.subjective_memory_revisions ALTER COLUMN candidate_validation_id DROP NOT NULL;
ALTER TABLE armi.subjective_memory_revisions ALTER COLUMN proposal_ref DROP NOT NULL;
ALTER TABLE armi.subjective_memory_revisions ALTER COLUMN source_experience_id DROP NOT NULL;
ALTER TABLE armi.subjective_memory_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.subjective_memory_revisions DROP CONSTRAINT subjective_memory_revisions_check;
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_check CHECK ((admin_change_id IS NOT NULL AND mechanism_identity='armi.memory.admin-v1' AND mechanism_config_identity='admin-v1' AND ((revision_no=1 AND previous_revision_id IS NULL AND revision_kind='formed') OR (revision_no>1 AND previous_revision_id IS NOT NULL AND revision_kind<>'formed'))) OR (((revision_no = 1) AND (previous_revision_id IS NULL) AND (revision_kind = 'formed'::text) AND (accessibility = 'available'::text) AND (mechanism_identity = 'armi.memory-formation.contextual-v1'::text) AND (mechanism_config_identity = 'formation-v1'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL) AND (revision_kind <> 'formed'::text) AND (mechanism_identity = 'armi.memory-revision.contextual-v1'::text) AND (mechanism_config_identity = ANY (ARRAY['natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text])))));
ALTER TABLE armi.subjective_memory_revisions DROP CONSTRAINT subjective_memory_revisions_check2;
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_check2 CHECK ((((source_kind = 'administrator'::text) AND (source_fact_class = 'external_claim'::text)) OR ((source_kind = 'reported'::text) AND (source_fact_class = 'external_claim'::text)) OR ((source_kind = 'inferred'::text) AND (source_fact_class = 'inference'::text)) OR ((source_kind = 'queried'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text]))) OR ((source_kind = 'unknown'::text) AND (source_fact_class = 'unknown'::text)) OR ((source_kind = 'experienced'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'subjective_understanding'::text])))));
ALTER TABLE armi.subjective_memory_revisions DROP CONSTRAINT subjective_memory_revisions_mechanism_config_identity_check;
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_mechanism_config_identity_check CHECK ((mechanism_config_identity = ANY (ARRAY['admin-v1'::text, 'formation-v1'::text, 'natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text])));
ALTER TABLE armi.subjective_memory_revisions DROP CONSTRAINT subjective_memory_revisions_mechanism_identity_check;
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_mechanism_identity_check CHECK ((mechanism_identity = ANY (ARRAY['armi.memory.admin-v1'::text, 'armi.memory-formation.contextual-v1'::text, 'armi.memory-revision.contextual-v1'::text])));
ALTER TABLE armi.subjective_memory_revisions DROP CONSTRAINT subjective_memory_revisions_source_kind_check;
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_source_kind_check CHECK ((source_kind = ANY (ARRAY['administrator'::text, 'experienced'::text, 'reported'::text, 'inferred'::text, 'queried'::text, 'unknown'::text])));
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_admin_provenance CHECK (((admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL) OR (admin_change_id IS NULL AND subject_commit_id IS NOT NULL AND candidate_validation_id IS NOT NULL AND proposal_ref IS NOT NULL)));
ALTER TABLE armi.relationship_revisions ALTER COLUMN subject_commit_id DROP NOT NULL;
ALTER TABLE armi.relationship_revisions ALTER COLUMN candidate_validation_id DROP NOT NULL;
ALTER TABLE armi.relationship_revisions ALTER COLUMN proposal_ref DROP NOT NULL;
ALTER TABLE armi.relationship_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.relationship_revisions DROP CONSTRAINT relationship_revisions_mechanism_identity_check;
ALTER TABLE armi.relationship_revisions ADD CONSTRAINT relationship_revisions_mechanism_identity_check CHECK ((mechanism_identity = ANY (ARRAY['armi.relationship.admin-v1'::text, 'armi.relationship.contextual-v1'::text, 'armi.relationship.lifecycle-v2'::text])));
ALTER TABLE armi.relationship_revisions ADD CONSTRAINT relationship_revisions_admin_provenance CHECK (((admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL) OR (admin_change_id IS NULL AND subject_commit_id IS NOT NULL AND candidate_validation_id IS NOT NULL AND proposal_ref IS NOT NULL)));
ALTER TABLE armi.life_material_revisions ALTER COLUMN subject_commit_id DROP NOT NULL;
ALTER TABLE armi.life_material_revisions ALTER COLUMN candidate_validation_id DROP NOT NULL;
ALTER TABLE armi.life_material_revisions ALTER COLUMN proposal_ref DROP NOT NULL;
ALTER TABLE armi.life_material_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.life_material_revisions DROP CONSTRAINT life_material_revisions_source_kind_check;
ALTER TABLE armi.life_material_revisions ADD CONSTRAINT life_material_revisions_source_kind_check CHECK ((source_kind IN ('subject_cognition','administrator')));
ALTER TABLE armi.life_material_revisions ADD CONSTRAINT life_material_revisions_admin_provenance CHECK (((admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL) OR (admin_change_id IS NULL AND subject_commit_id IS NOT NULL AND candidate_validation_id IS NOT NULL AND proposal_ref IS NOT NULL)));
ALTER TABLE armi.subject_component_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.mood_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.prompt_revisions ALTER COLUMN author_party_id DROP NOT NULL;
ALTER TABLE armi.prompt_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.prompt_revisions ADD CONSTRAINT prompt_revisions_admin_provenance CHECK (((admin_change_id IS NULL AND author_party_id IS NOT NULL) OR (admin_change_id IS NOT NULL AND author_party_id IS NULL AND subject_commit_id IS NULL)));
ALTER TABLE armi.activities ALTER COLUMN origin_opportunity_id DROP NOT NULL;
ALTER TABLE armi.activities ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.activities ADD CONSTRAINT activities_admin_provenance CHECK (((admin_change_id IS NULL AND origin_opportunity_id IS NOT NULL) OR (admin_change_id IS NOT NULL AND origin_opportunity_id IS NULL)));
ALTER TABLE armi.activity_revisions ADD COLUMN admin_change_id uuid;
ALTER TABLE armi.activity_revisions DROP CONSTRAINT activity_revisions_provenance_check;
ALTER TABLE armi.activity_revisions ADD CONSTRAINT activity_revisions_provenance_check CHECK ((admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL) OR (((transition_kind = ANY (ARRAY['system_pause'::text,'data_rights'::text])) AND (subject_commit_id IS NULL) AND (candidate_validation_id IS NULL) AND (proposal_ref IS NULL)) OR ((transition_kind <> ALL (ARRAY['system_pause'::text,'data_rights'::text])) AND (subject_commit_id IS NOT NULL) AND (candidate_validation_id IS NOT NULL) AND (proposal_ref IS NOT NULL))));
ALTER TABLE armi.activity_revisions DROP CONSTRAINT activity_revisions_transition_kind_check;
ALTER TABLE armi.activity_revisions ADD CONSTRAINT activity_revisions_transition_kind_check CHECK ((transition_kind = ANY (ARRAY['admin_update'::text, 'admin_delete'::text, 'created'::text, 'engage'::text, 'progress'::text, 'wait'::text, 'pause'::text, 'resume'::text, 'complete'::text, 'abandon'::text, 'system_fail'::text, 'system_pause'::text, 'data_rights'::text])));
ALTER TABLE armi.activity_revisions DROP CONSTRAINT activity_revisions_transition_state_check;
ALTER TABLE armi.activity_revisions ADD CONSTRAINT activity_revisions_transition_state_check CHECK ((admin_change_id IS NOT NULL AND ((transition_kind='admin_update' AND status IN ('ready','paused','waiting')) OR (transition_kind='admin_delete' AND status='abandoned'))) OR (((transition_kind = 'created'::text) AND (revision_no = 1) AND (status = 'ready'::text)) OR ((transition_kind = 'engage'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'progress'::text) AND (status = 'in_progress'::text)) OR ((transition_kind = 'wait'::text) AND (status = 'waiting'::text)) OR ((transition_kind = ANY (ARRAY['pause'::text, 'system_pause'::text])) AND (status = 'paused'::text)) OR ((transition_kind = 'resume'::text) AND (status = 'resuming'::text)) OR ((transition_kind = 'complete'::text) AND (status = 'completed'::text)) OR ((transition_kind = ANY (ARRAY['abandon'::text,'data_rights'::text])) AND (status = 'abandoned'::text)) OR ((transition_kind = 'system_fail'::text) AND (status = 'failed'::text))));
ALTER TABLE armi.subjective_memory_revisions ADD CONSTRAINT subjective_memory_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.relationship_revisions ADD CONSTRAINT relationship_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.life_material_revisions ADD CONSTRAINT life_material_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.subject_component_revisions ADD CONSTRAINT subject_component_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.mood_revisions ADD CONSTRAINT mood_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.prompt_revisions ADD CONSTRAINT prompt_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.activities ADD CONSTRAINT activities_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.activity_revisions ADD CONSTRAINT activity_revisions_admin_change_fk FOREIGN KEY (admin_change_id) REFERENCES armi.admin_data_changes(admin_change_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE armi.subject_component_revisions ADD CONSTRAINT subject_component_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction');
ALTER TABLE armi.mood_revisions ADD CONSTRAINT mood_revisions_admin_provenance CHECK (admin_change_id IS NULL OR origin_kind='admin_correction');
ALTER TABLE armi.activity_revisions ADD CONSTRAINT activity_revisions_admin_provenance CHECK ((admin_change_id IS NULL AND transition_kind NOT IN ('admin_update','admin_delete')) OR (admin_change_id IS NOT NULL AND subject_commit_id IS NULL AND candidate_validation_id IS NULL AND proposal_ref IS NULL AND transition_kind IN ('created','admin_update','admin_delete')));
