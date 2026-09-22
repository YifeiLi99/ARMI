-- Read projection over owner facts. This view is not a second ledger.
CREATE OR REPLACE VIEW armi.provider_usage_calls AS
WITH parents AS (
    SELECT 'cognition'::text AS owner, a.model_attempt_id AS attempt_id,
           COALESCE(effect.root_opportunity_id,o.root_opportunity_id) AS operation_id, 'episode'::text AS reference_kind,
           a.cognitive_episode_id AS reference_id, a.result_status AS business_result,
           a.settled_at, a.provider_calls
    FROM armi.cognitive_attempts a
    JOIN armi.cognitive_episodes e USING (cognitive_episode_id)
    JOIN armi.opportunities o USING (opportunity_id)
    LEFT JOIN armi.external_evidence evidence ON evidence.evidence_id=o.evidence_id
    LEFT JOIN armi.codex_task_sources verification
      ON verification.codex_verification_id=evidence.codex_verification_id
    LEFT JOIN armi.effects effect ON effect.effect_id=verification.effect_id
    UNION ALL
    SELECT 'cognition', m.event_appraisal_id, o.root_opportunity_id, 'episode',
           m.cognitive_episode_id, m.status, m.completed_at, m.provider_calls
    FROM armi.event_appraisals m
    JOIN armi.cognitive_episodes e USING (cognitive_episode_id)
    JOIN armi.opportunities o USING (opportunity_id)
    UNION ALL
    SELECT 'interaction', p.external_message_part_id, origin.operation_id, 'interaction',
           p.interaction_id, p.processing_status, p.settled_at,
           p.provider_calls
    FROM armi.external_message_parts p
    LEFT JOIN LATERAL (
        SELECT o.root_opportunity_id AS operation_id
        FROM armi.external_evidence e JOIN armi.opportunities o USING (evidence_id)
        WHERE e.interaction_id = p.interaction_id
        ORDER BY o.available_after, o.opportunity_id LIMIT 1
    ) origin ON true
    UNION ALL
    SELECT 'live-vision', v.observation_id, o.root_opportunity_id, 'visual_observation',
           v.observation_id, v.status, v.settled_at, v.provider_calls
    FROM armi.live_vision_observations v
    LEFT JOIN armi.cognitive_episodes e ON e.cognitive_episode_id = v.origin_episode_id
    LEFT JOIN armi.opportunities o ON o.opportunity_id = e.opportunity_id
    UNION ALL
    SELECT 'live-voice', t.turn_id, t.root_opportunity_id, 'voice_turn',
           t.turn_id, t.result_status, t.completed_at, t.provider_calls
    FROM armi.live_voice_turns t
    UNION ALL
    SELECT 'live-voice', s.scene_id, NULL::uuid, 'voice_scene',
           s.scene_id, 'recorded'::text, NULL::timestamptz, s.voice_provider_calls
    FROM armi.interaction_scenes s

)
SELECT p.owner, p.attempt_id, p.operation_id, p.reference_kind, p.reference_id,
       p.business_result,
       CASE WHEN c.value->>'outcome' = 'pending' AND p.settled_at IS NOT NULL
            THEN c.value || jsonb_build_object(
                'outcome', 'unknown', 'finished_at', p.settled_at,
                'error_code', 'USAGE-OWNER-INTERRUPTED')
            ELSE c.value END AS receipt
FROM parents p CROSS JOIN LATERAL jsonb_each(p.provider_calls) c;
