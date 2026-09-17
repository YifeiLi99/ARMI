-- Accept the current autonomous candidate; preserve all historical records.
DO $$
DECLARE target record; definition text;
BEGIN
  FOR target IN
    SELECT conrelid::regclass AS relation,conname FROM pg_constraint
    WHERE connamespace='armi'::regnamespace AND contype='c'
      AND conname IN ('cognitive_attempts_candidate_schema_version_check',
                      'cognitive_candidate_validation_candidate_contract_version_check')
  LOOP
    SELECT pg_get_constraintdef(oid) INTO STRICT definition FROM pg_constraint
      WHERE conrelid=target.relation AND conname=target.conname;
    definition=replace(definition,quote_literal('armi.autonomous-activity-candidate.v8')||'::text',
      quote_literal('armi.autonomous-activity-candidate.v8')||'::text, '||quote_literal('armi.autonomous-activity-candidate.v9')||'::text');
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',target.relation,target.conname);
    EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',target.relation,target.conname,definition);
  END LOOP;
END $$;
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v25';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v25');
