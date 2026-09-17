-- Exact forward upgrade; historical opportunities retain NULL (not recorded).
ALTER TABLE armi.opportunities ADD COLUMN consideration_signals jsonb;
ALTER TABLE armi.opportunities ADD CONSTRAINT opportunities_consideration_signals_check CHECK ((consideration_signals IS NULL) OR (
    jsonb_typeof(consideration_signals)='object'
    AND consideration_signals->>'schema_version'='armi.consideration-signals.v1'
    AND jsonb_typeof(consideration_signals->'signals')='array'
    AND consideration_signals ? 'frozen_at'
));
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v23';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v23');
