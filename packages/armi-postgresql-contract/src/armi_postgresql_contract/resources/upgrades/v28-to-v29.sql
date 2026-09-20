-- Preserve historical attempts; active provider selection belongs to Cognition.
ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
UPDATE armi.schema_baseline_identity SET baseline_identity='armi.schema-baseline.v29';
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity='armi.schema-baseline.v29');
ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_credential_identity_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_credential_identity_check CHECK (credential_identity IN ('armi.model.ark-api-key.v1', 'armi.model.qwen-api-key.v1', 'armi.model.deepseek-api-key.v1'));
ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_model_id_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_model_id_check CHECK (model_id ~ '^[a-z0-9][a-z0-9._-]{0,127}$');
ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_pricing_snapshot_id_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_pricing_snapshot_id_check CHECK (pricing_snapshot_id IS NULL OR length(pricing_snapshot_id) > 0);
ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_provider_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_provider_check CHECK (provider IN ('volcengine_ark', 'qwen', 'deepseek'));
ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_provider_model_id_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_provider_model_id_check CHECK (provider_model_id IS NULL OR provider_model_id ~ '^[a-z0-9][a-z0-9._-]{0,127}$');
