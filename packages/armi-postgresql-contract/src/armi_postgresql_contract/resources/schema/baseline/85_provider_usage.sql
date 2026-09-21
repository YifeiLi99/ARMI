-- Read projection over owner facts. This view is not a second ledger.
CREATE OR REPLACE VIEW armi.provider_usage_calls AS
WITH parents AS (
    SELECT 'cognition'::text AS owner, a.model_attempt_id AS attempt_id,
           COALESCE(effect.root_opportunity_id,o.root_opportunity_id) AS operation_id, 'episode'::text AS reference_kind,
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
    LEFT JOIN armi.codex_task_sources verification
      ON verification.codex_verification_id=evidence.codex_verification_id
    LEFT JOIN armi.effects effect ON effect.effect_id=verification.effect_id
    WHERE e.purpose <> 'reflect_mood'
    UNION ALL
    SELECT 'interaction', p.external_message_part_id, origin.operation_id, 'interaction',
           p.interaction_id, p.processing_status, p.settled_at,
           p.provider_calls, 1, NULL::text, NULL::text,
           NULL::text, 'external_content_recognition', p.created_at,
           NULL::text, NULL::text, NULL::integer, NULL::integer,
           NULL::integer, NULL::integer, NULL::bigint, p.failure_code
    FROM armi.external_message_parts p
    LEFT JOIN LATERAL (
        SELECT o.root_opportunity_id AS operation_id
        FROM armi.external_evidence e JOIN armi.opportunities o USING (evidence_id)
        WHERE e.interaction_id = p.interaction_id
        ORDER BY o.available_after, o.opportunity_id LIMIT 1
    ) origin ON true
    UNION ALL
    SELECT 'live-vision', v.observation_id, o.root_opportunity_id, 'visual_observation',
           v.observation_id, v.status, v.settled_at, v.provider_calls,
           1, v.provider, v.model_id, 'generation',
           'visual_observation', v.registered_at, v.provider_request_id, NULL::text,
           v.input_tokens, v.output_tokens, NULL::integer, NULL::integer,
           NULL::bigint, v.error_code
    FROM armi.live_vision_observations v
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
