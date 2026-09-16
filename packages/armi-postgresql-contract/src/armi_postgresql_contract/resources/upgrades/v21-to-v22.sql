-- Exact v21 -> v22; append a migration revision, never relabel old Mind facts.
WITH migrated AS (
  INSERT INTO armi.subject_component_revisions (
    component_revision_id,subject_id,component_kind,component_version,
    previous_revision_id,origin_kind,origin_ref,semantic_payload,privacy_scope)
  SELECT uuidv7(),head.subject_id,'mind',head.component_version+1,
         head.current_revision_id,'module_migration',uuidv7(),
         jsonb_set(revision.semantic_payload,'{schema_version}','"armi.mind.v3"')
           || '{"concerns":[]}'::jsonb,'private'
  FROM armi.subject_component_heads head
  JOIN armi.subject_component_revisions revision
    ON revision.component_revision_id=head.current_revision_id
  WHERE head.component_kind='mind'
    AND revision.semantic_payload->>'schema_version'='armi.mind.v2'
  RETURNING subject_id,component_revision_id,component_version
) UPDATE armi.subject_component_heads head
  SET current_revision_id=migrated.component_revision_id,
      component_version=migrated.component_version
  FROM migrated WHERE head.subject_id=migrated.subject_id AND head.component_kind='mind';

DO $$
DECLARE target record; definition text; old_version text; new_version text;
BEGIN
  FOR target IN
    SELECT conrelid::regclass AS relation,conname FROM pg_constraint
    WHERE connamespace='armi'::regnamespace AND contype='c'
      AND pg_get_constraintdef(oid) LIKE '%armi.autonomous-activity-candidate.v7%'
  LOOP
    SELECT pg_get_constraintdef(oid) INTO STRICT definition FROM pg_constraint
      WHERE conrelid=target.relation AND conname=target.conname;
    FOR old_version,new_version IN VALUES
      ('armi.autonomous-activity-candidate.v7','armi.autonomous-activity-candidate.v8'),
      ('armi.creator-cognitive-act-candidate.v4','armi.creator-cognitive-act-candidate.v5'),
      ('armi.creator-voice-act-candidate.v4','armi.creator-voice-act-candidate.v5')
      ,('armi.cognition-candidate.v14','armi.cognition-candidate.v15')
      ,('armi.visual-observation-candidate.v2','armi.visual-observation-candidate.v3')
    LOOP
      definition=replace(definition,quote_literal(old_version)||'::text',
        quote_literal(old_version)||'::text, '||quote_literal(new_version)||'::text');
    END LOOP;
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',target.relation,target.conname);
    EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',target.relation,target.conname,definition);
  END LOOP;
END $$;
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v22';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v22');
