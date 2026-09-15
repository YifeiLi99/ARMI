ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity = 'armi.schema-baseline.v19'::text) NOT VALID;
UPDATE armi.schema_baseline_identity SET baseline_identity = 'armi.schema-baseline.v19';
ALTER TABLE armi.schema_baseline_identity VALIDATE CONSTRAINT schema_baseline_identity_value_check;

ALTER TABLE armi.opportunities DROP CONSTRAINT opportunities_lineage_check;
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_lineage_check CHECK ((((reconsideration_no = 0) AND (root_opportunity_id = opportunity_id) AND (predecessor_opportunity_id IS NULL)) OR ((reconsideration_no > 0) AND (root_opportunity_id <> opportunity_id) AND (predecessor_opportunity_id IS NOT NULL))));
ALTER TABLE armi.opportunities DROP CONSTRAINT opportunities_reconsideration_check;
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_reconsideration_check CHECK (((reconsideration_no >= 0) AND ((reconsideration_no <= 1) OR ((purpose = 'consider_autonomous_life'::text) AND (source_kind = 'life_generation_available'::text)))));
