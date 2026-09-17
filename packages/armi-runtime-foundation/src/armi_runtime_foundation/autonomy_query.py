"""One read contract for the autonomous plan and paginated opportunity history."""

from typing import Literal, cast

from .admin_transactions import PostgreSQLAdminParameter


def autonomy_statement(
    mode: Literal["status", "history"],
    limit: int = 25,
    offset: int = 0,
    *,
    sleeping: bool = False,
) -> tuple[str, tuple[PostgreSQLAdminParameter, ...]]:
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or offset < 0
    ):
        raise ValueError("LIFE-AUTONOMY-QUERY")
    if mode == "status":
        return (
            """
        WITH current AS (
          SELECT p.*, o.current_disposition,
            (SELECT count(*) FROM armi.autonomy_request_admissions a
             WHERE a.subject_id=p.subject_id
               AND a.quota_date=(statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::date) AS used,
            EXISTS(SELECT 1 FROM armi.runtime_instances r WHERE r.subject_id=p.subject_id
                   AND r.status='active' AND r.lease_expires_at>statement_timestamp()) AS running,
            EXISTS(SELECT 1 FROM armi.cognitive_episodes e WHERE e.subject_id=p.subject_id
                   AND e.status IN ('preparing','prepared','calling_model','finalizing')) AS busy
          FROM armi.autonomy_plans p
          LEFT JOIN armi.opportunities o USING(opportunity_id)
        )
        SELECT COALESCE((SELECT jsonb_build_object(
          'state', CASE WHEN NOT (policy->>'enabled')::boolean THEN 'disabled'
                   WHEN NOT running THEN 'runtime_stopped'
                   WHEN %s THEN 'sleeping'
                   WHEN used >= (policy->>'daily_request_limit')::integer THEN 'quota_exhausted'
                   WHEN current_disposition='selected' THEN 'thinking'
                   WHEN busy THEN 'resource_busy'
                   WHEN next_consideration_at>statement_timestamp() THEN 'scheduled'
                   ELSE 'ready' END,
          'plan_version',plan_version,'next_consideration_at',next_consideration_at,
          'source_episode_id',source_episode_id,'opportunity_id',opportunity_id,
          'observed_at',statement_timestamp(),
          'last_considered_at',(SELECT max(resolved_at) FROM armi.opportunities o
            WHERE o.subject_id=current.subject_id AND o.purpose='consider_autonomous_life'),
          'consumed_signal_keys',COALESCE((
             SELECT jsonb_agg(jsonb_build_array(entry->>'owner',entry->>'object_ref',entry->>'condition_version'))
             FROM armi.opportunities o,LATERAL jsonb_array_elements(o.consideration_signals->'signals') entry
             WHERE o.subject_id=current.subject_id AND o.consideration_signals->>'frozen_at' IS NOT NULL
          ),'[]'::jsonb),
          'policy',policy,'used_requests',used,
          'outlet_state',CASE WHEN running THEN outlet_state ELSE 'unavailable' END,
          'outlet_reason_code',CASE WHEN running THEN outlet_reason_code ELSE 'LIFE-RUNTIME-STOPPED' END,
          'outlet_observed_at',outlet_observed_at,
          'remaining_requests',GREATEST(0,(policy->>'daily_request_limit')::integer-used),
          'quota_resets_at',((statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::date + 1)::timestamp
                             AT TIME ZONE 'Asia/Shanghai',
          'timezone','Asia/Shanghai') FROM current LIMIT 1),
          jsonb_build_object('state','not_initialized'))
        """,
            (sleeping,),
        )
    if mode != "history":
        raise ValueError("LIFE-AUTONOMY-QUERY")
    return (
        """
      WITH page AS (
        SELECT o.opportunity_id AS operation_id,o.available_after,o.current_disposition,
               o.consideration_signals,
               o.resolution_reason_code,e.cognitive_episode_id AS episode_id,e.status AS cognition_status,
               e.final_disposition,e.failure_code,delivery.effect_id,delivery.status AS effect_status
        FROM armi.opportunities o
        LEFT JOIN LATERAL (
          SELECT cognitive_episode_id,status,final_disposition,failure_code FROM armi.cognitive_episodes
          WHERE opportunity_id=o.opportunity_id ORDER BY created_at DESC LIMIT 1
        ) e ON true
        LEFT JOIN LATERAL (
          SELECT effect.effect_id,effect.status FROM armi.action_intents intent
          JOIN armi.effects effect USING(action_intent_id)
          WHERE intent.root_opportunity_id=o.opportunity_id AND intent.action_kind='party_response'
          ORDER BY effect.registered_at DESC,effect.effect_id DESC LIMIT 1
        ) delivery ON true
        WHERE o.source_kind='autonomy_plan'
        ORDER BY o.available_after DESC,o.opportunity_id DESC LIMIT %s OFFSET %s
      )
      SELECT jsonb_build_object('items',COALESCE((SELECT jsonb_agg(to_jsonb(page) ORDER BY available_after DESC,operation_id DESC) FROM page),'[]'::jsonb),
        'total',(SELECT count(*) FROM armi.opportunities WHERE source_kind='autonomy_plan'),
        'limit',%s,'offset',%s)
    """,
        (limit, offset, limit, offset),
    )


def autonomy_result(row: tuple[object, ...] | None) -> dict[str, object]:
    if row is None or not isinstance(row[0], dict):
        raise ValueError("LIFE-AUTONOMY-QUERY")
    return cast(dict[str, object], row[0])


__all__ = ("autonomy_result", "autonomy_statement")
