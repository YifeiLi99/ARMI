-- Exact v20 to v21 forward conversion; historical rows remain unchanged.
-- Retired queued rounds cannot execute against the new purpose registry.
UPDATE armi.opportunities SET current_disposition='cancelled',resolved_at=statement_timestamp(),
    resolution_reason_code='REC-AUTONOMY-MECHANISM-REPLACED'
WHERE purpose IN ('consider_creator_outreach','consider_activity_attention','consider_activity_internal_work')
  AND current_disposition IN ('open','selected');
ALTER TABLE armi.codex_task_sources ADD COLUMN origin_subject_commit_id uuid REFERENCES armi.subject_commits(subject_commit_id);
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v21';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v21');
-- Preserve the exact historical contract labels accepted by the supported source.
-- Only extend the append-only history constraints with the new candidate version.
DO $upgrade$
DECLARE
    target record;
    definition text;
    previous_version text;
BEGIN
    FOR target IN SELECT * FROM (VALUES
        ('cognitive_attempts','cognitive_attempts_candidate_schema_version_check'),
        ('cognitive_candidate_validations','cognitive_candidate_validation_candidate_contract_version_check')
    ) AS names(table_name,constraint_name)
    LOOP
        SELECT pg_get_constraintdef(oid) INTO STRICT definition FROM pg_constraint
        WHERE conrelid=format('armi.%I',target.table_name)::regclass
          AND conname=target.constraint_name;
        SELECT matches[1] INTO STRICT previous_version
        FROM regexp_matches(definition, $pattern$'armi.autonomous-activity-candidate.v[0-9]+'::text$pattern$, 'g')
             WITH ORDINALITY AS versions(matches,position)
        ORDER BY position DESC LIMIT 1;
        definition := replace(definition, previous_version,
                              previous_version || ', ''armi.autonomous-activity-candidate.v7''::text');
        EXECUTE format('ALTER TABLE armi.%I DROP CONSTRAINT %I',target.table_name,target.constraint_name);
        EXECUTE format('ALTER TABLE armi.%I ADD CONSTRAINT %I %s',target.table_name,target.constraint_name,definition);
    END LOOP;
END
$upgrade$;
ALTER TABLE armi.cognitive_episodes DROP CONSTRAINT cognitive_episodes_scene_shape_check;
ALTER TABLE armi.cognitive_episodes ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (((purpose = 'consider_autonomous_life' AND ((scene_id IS NULL) = (context_party_id IS NULL))) OR ((purpose = ANY (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text])) AND (scene_id IS NULL) AND (context_party_id IS NULL)) OR ((purpose <> ALL (ARRAY['consider_autonomous_life'::text, 'consider_activity_attention'::text, 'consider_activity_internal_work'::text, 'consider_sleep'::text, 'maintain_subjective_memory'::text, 'perform_subject_self_check'::text, 'consider_visual_observation'::text, 'reflect_self'::text, 'reflect_mind'::text, 'reflect_mood'::text, 'reflect_prompt'::text])) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL))));
ALTER TABLE armi.opportunities DROP CONSTRAINT opportunities_source_kind_check;
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_source_kind_check CHECK ((source_kind = ANY (ARRAY['autonomy_plan'::text, 'external_evidence'::text, 'life_generation_available'::text, 'subject_component_revision'::text, 'activity_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text, 'life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_activity'::text, 'creator_outreach_relationship'::text])));
ALTER TABLE armi.opportunities DROP CONSTRAINT opportunities_source_shape_check;
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_source_shape_check CHECK (((source_kind = 'autonomy_plan' AND evidence_id IS NULL AND ((scene_id IS NULL) = (context_party_id IS NULL))) OR ((source_kind = 'external_evidence'::text) AND (evidence_id = source_ref) AND (activity_id IS NULL) AND (((purpose = 'consider_visual_observation'::text) AND (scene_id IS NULL) AND (context_party_id IS NULL)) OR ((purpose <> 'consider_visual_observation'::text) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL)))) OR ((source_kind = ANY (ARRAY['life_generation_available'::text, 'subject_component_revision'::text, 'maintenance_window'::text, 'maintenance_phase_revision'::text, 'life_material_revision'::text])) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NULL)) OR ((source_kind = 'activity_revision'::text) AND (evidence_id IS NULL) AND (scene_id IS NULL) AND (context_party_id IS NULL) AND (activity_id IS NOT NULL)) OR ((source_kind = ANY (ARRAY['life_query_result'::text, 'creator_outreach_absence'::text, 'creator_outreach_relationship'::text])) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NULL)) OR ((source_kind = 'creator_outreach_activity'::text) AND (evidence_id IS NULL) AND (scene_id IS NOT NULL) AND (context_party_id IS NOT NULL) AND (activity_id IS NOT NULL))));
