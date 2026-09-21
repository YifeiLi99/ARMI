-- Read projection over owner facts. This view is not a second ledger.
CREATE OR REPLACE VIEW armi.provider_usage_calls AS
WITH parents AS (
    SELECT 'cognition'::text AS owner, a.model_attempt_id AS attempt_id,
           COALESCE(codex_origin.root_opportunity_id,o.root_opportunity_id) AS operation_id, 'episode'::text AS reference_kind,
           a.cognitive_episode_id AS reference_id, a.result_status AS business_result,
           a.settled_at, a.provider_calls, a.usage_contract_version,
           a.provider, a.model_id AS model, 'generation'::text AS service, e.purpose,
           a.dispatched_at AS started_at, a.provider_request_id, a.provider_model_id,
           a.input_tokens, a.output_tokens, a.cached_input_tokens,
           NULL::integer AS web_search_calls, a.estimated_cost_microyuan,
           a.error_code
    FROM armi.cognitive_attempts a
    JOIN armi.cognitive_episodes e USING (cognitive_episode_id)
    JOIN armi.opportunities o USING (opportunity_id)
    LEFT JOIN armi.external_evidence evidence ON evidence.evidence_id=o.evidence_id
    LEFT JOIN armi.codex_verification_results verification
      ON verification.codex_verification_id=evidence.codex_verification_id
    LEFT JOIN armi.effects effect ON effect.effect_id=verification.effect_id
    LEFT JOIN armi.action_intents codex_origin ON codex_origin.action_intent_id=effect.action_intent_id
    WHERE e.purpose <> 'reflect_mood'
    UNION ALL
    SELECT 'perception', a.recognition_attempt_id, origin.operation_id, 'interaction',
           a.interaction_id, a.result_status, a.settled_at,
           a.provider_calls, a.usage_contract_version, a.provider, a.model_id,
           CASE WHEN a.provider = 'volcengine_doubao_speech' THEN 'asr' ELSE 'generation' END,
           'external_content_recognition', a.dispatched_at,
           a.provider_request_id, a.provider_model_id, a.input_tokens, a.output_tokens,
           NULL::integer, NULL::integer, a.estimated_cost_microyuan, a.error_code
    FROM armi.external_content_recognition_attempts a
    LEFT JOIN LATERAL (
        SELECT o.root_opportunity_id AS operation_id
        FROM armi.external_evidence e JOIN armi.opportunities o USING (evidence_id)
        WHERE e.interaction_id = a.interaction_id
        ORDER BY o.available_after, o.opportunity_id LIMIT 1
    ) origin ON true
    UNION ALL
    SELECT 'perception', a.visual_attempt_id, o.root_opportunity_id, 'visual_observation',
           a.observation_id, a.status, a.settled_at, a.provider_calls,
           a.usage_contract_version, a.provider, a.model_id, 'generation',
           'visual_observation', a.dispatched_at, a.provider_request_id, NULL::text,
           a.input_tokens, a.output_tokens, NULL::integer, NULL::integer,
           NULL::bigint, a.error_code
    FROM armi.visual_recognition_attempts a
    JOIN armi.live_vision_observations v USING (observation_id)
    LEFT JOIN armi.cognitive_episodes e ON e.cognitive_episode_id = v.origin_episode_id
    LEFT JOIN armi.opportunities o ON o.opportunity_id = e.opportunity_id
    UNION ALL
    SELECT 'live-voice', t.turn_id, t.root_opportunity_id, 'voice_turn',
           t.turn_id, t.result_status, t.completed_at, t.provider_calls, 1,
           NULL::text, NULL::text, NULL::text, 'live_voice', t.created_at,
           NULL::text, NULL::text, NULL::integer, NULL::integer,
           NULL::integer, NULL::integer, NULL::bigint, t.error_code
    FROM armi.live_voice_turns t
    UNION ALL
    SELECT 'live-voice', s.session_id, NULL::uuid, 'voice_session',
           s.session_id, s.state, s.ended_at, s.provider_calls, 1,
           NULL::text, NULL::text, NULL::text, 'live_voice', s.started_at,
           NULL::text, NULL::text, NULL::integer, NULL::integer,
           NULL::integer, NULL::integer, NULL::bigint, s.error_code
    FROM armi.live_voice_sessions s
    UNION ALL
    SELECT 'web-observation', a.observation_attempt_id, o.root_opportunity_id,
           'web_observation', a.web_observation_request_id, a.result_status,
           a.settled_at, a.provider_calls, a.usage_contract_version,
           'volcengine_ark', 'doubao-seed-evolving', 'web_search', 'public_web_research',
           a.dispatched_at, NULL::text, a.provider_model_id, a.input_tokens,
           a.output_tokens, NULL::integer, a.web_search_calls,
           a.estimated_cost_microyuan, a.error_code
    FROM armi.observation_attempts a
    JOIN armi.web_observation_requests r USING (web_observation_request_id)
    LEFT JOIN armi.web_research_intents i USING (web_research_intent_id)
    LEFT JOIN armi.opportunities o ON o.opportunity_id = i.source_opportunity_id
)
SELECT p.owner, p.attempt_id, p.operation_id, p.reference_kind, p.reference_id,
       p.business_result, false AS legacy,
       CASE WHEN c.value->>'outcome' = 'pending' AND p.settled_at IS NOT NULL
            THEN c.value || jsonb_build_object(
                'outcome', 'unknown', 'finished_at', p.settled_at,
                'error_code', 'USAGE-OWNER-INTERRUPTED')
            ELSE c.value END AS receipt
FROM parents p CROSS JOIN LATERAL jsonb_each(p.provider_calls) c
UNION ALL
SELECT p.owner, p.attempt_id, p.operation_id, p.reference_kind, p.reference_id,
       p.business_result, true,
       jsonb_build_object(
           'schema_version', 'armi.provider-call.legacy',
           'call_id', p.attempt_id, 'provider', p.provider, 'model', p.model,
           'service', p.service, 'purpose', p.purpose, 'started_at', p.started_at,
           'finished_at', p.settled_at, 'billable', true,
           'outcome', CASE WHEN p.business_result IN ('succeeded', 'completed') THEN 'returned' ELSE 'unknown' END,
           'provider_request_id', p.provider_request_id, 'response_model', p.provider_model_id,
           'error_code', p.error_code, 'price', NULL,
           'quantities', (
               SELECT COALESCE(jsonb_agg(jsonb_build_object(
                   'unit', u.unit, 'quantity', u.quantity, 'source', 'provider')), '[]'::jsonb)
               FROM (VALUES ('input_tokens', p.input_tokens),
                            ('output_tokens', p.output_tokens),
                            ('cached_input_tokens', p.cached_input_tokens),
                            ('web_search_calls', p.web_search_calls)) u(unit, quantity)
               WHERE u.quantity IS NOT NULL
           ),
           'cost', jsonb_build_object(
               'status', 'legacy', 'known_microyuan', p.estimated_cost_microyuan,
               'currency', 'CNY', 'components', '[]'::jsonb,
               'missing_usage', '[]'::jsonb, 'missing_prices', '[]'::jsonb,
               'snapshot_id', NULL, 'rounding', 'legacy'),
           'raw_usage', NULL)
FROM parents p
WHERE p.usage_contract_version = 0 AND p.started_at IS NOT NULL;
