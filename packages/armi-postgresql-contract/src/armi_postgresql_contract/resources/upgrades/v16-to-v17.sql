ALTER TABLE armi.schema_baseline_identity
    DROP CONSTRAINT schema_baseline_identity_value_check;
ALTER TABLE armi.schema_baseline_identity
    ADD CONSTRAINT schema_baseline_identity_value_check
    CHECK (baseline_identity = 'armi.schema-baseline.v17'::text) NOT VALID;
UPDATE armi.schema_baseline_identity
    SET baseline_identity = 'armi.schema-baseline.v17';
ALTER TABLE armi.schema_baseline_identity
    VALIDATE CONSTRAINT schema_baseline_identity_value_check;
