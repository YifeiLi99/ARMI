ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
REVOKE INSERT, UPDATE, DELETE ON armi.cognitive_attempts, armi.visual_recognition_attempts, armi.live_voice_provider_attempts, armi.observation_attempts FROM armi_admin;
REVOKE INSERT, UPDATE ON armi.external_content_recognition_attempts FROM armi_admin;
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity = 'armi.schema-baseline.v20'::text) NOT VALID;
UPDATE armi.schema_baseline_identity SET baseline_identity = 'armi.schema-baseline.v20';
ALTER TABLE armi.schema_baseline_identity VALIDATE CONSTRAINT schema_baseline_identity_value_check;

ALTER TABLE armi.cognitive_attempts ADD COLUMN usage_contract_version smallint DEFAULT 0 NOT NULL CHECK (usage_contract_version IN (0, 1));
ALTER TABLE armi.cognitive_attempts ALTER COLUMN usage_contract_version SET DEFAULT 1;
ALTER TABLE armi.cognitive_attempts ADD COLUMN provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object');

ALTER TABLE armi.external_content_recognition_attempts ADD COLUMN usage_contract_version smallint DEFAULT 0 NOT NULL CHECK (usage_contract_version IN (0, 1));
ALTER TABLE armi.external_content_recognition_attempts ALTER COLUMN usage_contract_version SET DEFAULT 1;
ALTER TABLE armi.external_content_recognition_attempts ADD COLUMN provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object');

ALTER TABLE armi.visual_recognition_attempts ADD COLUMN usage_contract_version smallint DEFAULT 0 NOT NULL CHECK (usage_contract_version IN (0, 1));
ALTER TABLE armi.visual_recognition_attempts ALTER COLUMN usage_contract_version SET DEFAULT 1;
ALTER TABLE armi.visual_recognition_attempts ADD COLUMN provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object');

ALTER TABLE armi.live_voice_provider_attempts ADD COLUMN usage_contract_version smallint DEFAULT 0 NOT NULL CHECK (usage_contract_version IN (0, 1));
ALTER TABLE armi.live_voice_provider_attempts ALTER COLUMN usage_contract_version SET DEFAULT 1;
ALTER TABLE armi.live_voice_provider_attempts ADD COLUMN provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object');

ALTER TABLE armi.observation_attempts ADD COLUMN usage_contract_version smallint DEFAULT 0 NOT NULL CHECK (usage_contract_version IN (0, 1));
ALTER TABLE armi.observation_attempts ALTER COLUMN usage_contract_version SET DEFAULT 1;
ALTER TABLE armi.observation_attempts ADD COLUMN provider_calls jsonb DEFAULT '{}'::jsonb NOT NULL CHECK (jsonb_typeof(provider_calls) = 'object');

ALTER TABLE armi.cognitive_attempts ALTER COLUMN request_artifact_id DROP NOT NULL;
ALTER TABLE armi.cognitive_attempts ALTER COLUMN pricing_snapshot_id DROP NOT NULL;
ALTER TABLE armi.live_voice_provider_attempts ALTER COLUMN turn_id DROP NOT NULL;
ALTER TABLE armi.live_voice_provider_attempts ADD COLUMN session_id uuid;
ALTER TABLE armi.live_voice_provider_attempts ADD CONSTRAINT live_voice_provider_parent_check CHECK ((turn_id IS NULL) <> (session_id IS NULL));
ALTER TABLE armi.live_voice_provider_attempts ADD CONSTRAINT live_voice_provider_attempts_session_id_fkey FOREIGN KEY (session_id) REFERENCES armi.live_voice_sessions(session_id);

ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_check CHECK ((((dispatch_status = 'prepared'::text) AND (dispatched_at IS NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (response_artifact_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL) AND (estimated_cost_microyuan IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'dispatched'::text) AND (dispatched_at IS NOT NULL) AND (settled_at IS NULL) AND (result_status IS NULL) AND (response_artifact_id IS NULL) AND (error_code IS NULL)) OR ((dispatch_status = 'settled'::text) AND (settled_at IS NOT NULL) AND (result_status IS NOT NULL) AND (((result_status = 'succeeded'::text) AND (dispatched_at IS NOT NULL) AND (provider_request_id IS NOT NULL) AND (provider_model_id IS NOT NULL) AND (response_artifact_id IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (cached_input_tokens IS NOT NULL) AND (error_code IS NULL)) OR ((result_status <> 'succeeded'::text) AND (response_artifact_id IS NULL) AND (error_code IS NOT NULL) AND ((dispatched_at IS NOT NULL) OR ((result_status = 'cancelled'::text) AND (provider_request_id IS NULL) AND (provider_model_id IS NULL) AND (input_tokens IS NULL) AND (output_tokens IS NULL) AND (cached_input_tokens IS NULL) AND (estimated_cost_microyuan IS NULL))))))));

ALTER TABLE armi.observation_attempts DROP CONSTRAINT observation_attempts_check1;
ALTER TABLE armi.observation_attempts ADD CONSTRAINT observation_attempts_check1 CHECK ((((result_status = 'succeeded'::text) AND (provider_model_id IS NOT NULL) AND (result_artifact_id IS NOT NULL) AND (input_tokens IS NOT NULL) AND (output_tokens IS NOT NULL) AND (web_search_calls IS NOT NULL) AND (citation_count IS NOT NULL) AND (error_code IS NULL)) OR ((result_status = ANY (ARRAY['failed'::text, 'outcome_unknown'::text])) AND (error_code IS NOT NULL) AND (result_artifact_id IS NULL)) OR (result_status IS NULL) OR ((result_status = 'cancelled'::text) AND (result_artifact_id IS NULL))));

ALTER TABLE armi.observation_attempts DROP CONSTRAINT observation_attempts_estimated_cost_microyuan_check;
ALTER TABLE armi.observation_attempts ADD CONSTRAINT observation_attempts_estimated_cost_microyuan_check CHECK (((estimated_cost_microyuan IS NULL) OR ((estimated_cost_microyuan >= 0))));
