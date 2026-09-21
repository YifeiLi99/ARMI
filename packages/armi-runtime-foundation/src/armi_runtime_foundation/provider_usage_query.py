"""SQL for the shared usage projection; never writes another owner's facts."""

import json
from typing import cast

from armi_kernel.application import UsageQuery

from .admin_transactions import PostgreSQLAdminParameter

_BASE = """
WITH calls AS (
    SELECT owner, attempt_id::text, operation_id::text, reference_kind,
           reference_id::text, business_result, receipt
    FROM armi.provider_usage_calls
    UNION ALL
    SELECT 'admin', verification_id, NULL, 'credential_verification',
           verification_id, NULL, call
    FROM jsonb_to_recordset(%s::jsonb)
        AS r(verification_id text, call jsonb)
), filtered AS (
    SELECT *, (receipt->>'started_at')::timestamptz AS started_at,
        (receipt->'cost'->>'known_microyuan')::bigint AS known_microyuan,
        receipt->'cost'->>'status' AS cost_status,
        COALESCE((receipt->>'billable')::boolean, true) AS billable
    FROM calls WHERE {where}
)
"""

_UNITS = """
SELECT COALESCE(jsonb_object_agg(unit, quantity), '{{}}'::jsonb)
FROM (SELECT q->>'unit' AS unit, sum((q->>'quantity')::bigint) AS quantity
      FROM {source} c CROSS JOIN LATERAL jsonb_array_elements(c.receipt->'quantities') q
      WHERE c.billable GROUP BY q->>'unit') u
"""

_TOTALS = """
jsonb_build_object(
    'billable_calls', count(*) FILTER (WHERE billable),
    'auxiliary_requests', count(*) FILTER (WHERE NOT billable),
    'known_microyuan', sum(known_microyuan) FILTER (WHERE billable),
    'incomplete_calls', count(*) FILTER (WHERE billable AND (cost_status <> 'estimated' OR receipt->>'outcome' IN ('pending', 'unknown'))),
    'usage_unconfirmed_calls', count(*) FILTER (WHERE billable AND (
        receipt->>'outcome' IN ('pending', 'unknown') OR cost_status = 'usage_unknown'
        OR jsonb_array_length(COALESCE(receipt->'cost'->'missing_usage', '[]'::jsonb)) > 0)),
    'unpriced_calls', count(*) FILTER (WHERE billable AND (
        cost_status = 'unpriced' OR jsonb_array_length(COALESCE(
            receipt->'cost'->'missing_prices', '[]'::jsonb)) > 0))
)
"""

_ROW = """jsonb_build_object(
    'owner', owner, 'attempt_id', attempt_id, 'operation_id', operation_id,
    'reference_kind', reference_kind, 'reference_id', reference_id,
    'business_result', business_result, 'receipt', receipt)"""


def usage_statement(
    query: UsageQuery, admin_receipts: tuple[dict[str, object], ...]
) -> tuple[str, tuple[PostgreSQLAdminParameter, ...]]:
    parameters: list[PostgreSQLAdminParameter] = [json.dumps(admin_receipts)]
    conditions: list[str] = []
    if query.mode == "read":
        conditions.append("receipt->>'call_id' = %s")
        parameters.append(query.call_id)
    else:
        conditions.extend(
            [
                "(receipt->>'started_at')::timestamptz >= %s",
                "(receipt->>'started_at')::timestamptz < %s",
            ]
        )
        parameters.extend((query.filters.start, query.filters.end))
        for field in ("service", "model", "purpose", "outcome"):
            value = getattr(query.filters, field)
            if value is not None:
                conditions.append(f"receipt->>'{field}' = %s")
                parameters.append(value)
        if query.filters.cost_status is not None:
            conditions.append("receipt->'cost'->>'status' = %s")
            parameters.append(query.filters.cost_status)
        if query.filters.operation_id is not None:
            conditions.append("""operation_id::uuid IN (
                WITH RECURSIVE links AS (
                    SELECT DISTINCT o.root_opportunity_id AS child,
                        vo.root_opportunity_id AS parent
                    FROM armi.opportunities o
                    JOIN armi.external_evidence e USING (evidence_id)
                    LEFT JOIN armi.live_vision_observations v ON v.observation_id = e.visual_observation_id
                    LEFT JOIN armi.cognitive_episodes ve ON ve.cognitive_episode_id = v.origin_episode_id
                    LEFT JOIN armi.opportunities vo ON vo.opportunity_id = ve.opportunity_id
                    UNION
                    SELECT child.root_opportunity_id, effect.root_opportunity_id
                    FROM armi.codex_task_sources verification
                    JOIN armi.opportunities child ON child.opportunity_id = verification.opportunity_id
                    JOIN armi.effects effect ON effect.effect_id = verification.effect_id
                    UNION
                    SELECT child.root_opportunity_id, parent.root_opportunity_id
                    FROM armi.cognitive_episodes query
                    JOIN armi.opportunities child ON child.opportunity_id = query.life_query_result_opportunity_id
                    JOIN armi.opportunities parent ON parent.opportunity_id = query.opportunity_id
                ), related(id) AS (
                    SELECT COALESCE(o.root_opportunity_id, selector.id)
                    FROM (SELECT %s::uuid AS id) selector
                    LEFT JOIN armi.opportunities o ON o.opportunity_id = selector.id
                    UNION
                    SELECT l.child FROM links l JOIN related r ON l.parent = r.id
                ) SELECT id FROM related
            )""")
            parameters.append(query.filters.operation_id)
    base = _BASE.format(where=" AND ".join(conditions))
    if query.mode == "read":
        return (
            base
            + f"""SELECT {_ROW} || jsonb_build_object(
                'auxiliary_requests', COALESCE((
                    SELECT jsonb_agg(a.receipt ORDER BY a.receipt->>'started_at')
                    FROM calls a WHERE a.owner = filtered.owner
                        AND a.attempt_id = filtered.attempt_id
                        AND (a.receipt->>'billable')::boolean = false
                        AND (a.receipt->>'parent_call_id' IS NULL
                            OR a.receipt->>'parent_call_id' = filtered.receipt->>'call_id')
                ), '[]'::jsonb)) FROM filtered""",
            tuple(parameters),
        )
    if query.mode == "list":
        parameters.extend((query.limit, query.offset))
        return (
            base
            + f""", page AS (
            SELECT * FROM filtered WHERE billable
            ORDER BY started_at DESC, receipt->>'call_id' DESC LIMIT %s OFFSET %s
        )
        SELECT jsonb_build_object(
            'total', (SELECT count(*) FROM filtered WHERE billable),
            'items', COALESCE((SELECT jsonb_agg({_ROW} ORDER BY started_at DESC,
                receipt->>'call_id' DESC) FROM page), '[]'::jsonb))
        """,
            tuple(parameters),
        )
    units = _UNITS.format(source="filtered")
    daily_units = _UNITS.format(source="day_calls")
    group_units = _UNITS.format(source="group_calls")
    return (
        base
        + f"""
    SELECT jsonb_build_object(
        'currency', 'CNY', 'price_label', 'official_list_price_estimate',
        'timezone', 'Asia/Shanghai',
        'coverage', 'owner_calls_and_admin_checks;codex_subscription_excluded',
        'totals', (SELECT {_TOTALS} FROM filtered),
        'units', ({units}),
        'daily', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'date', d.day, 'totals', (
                    SELECT {_TOTALS} FROM filtered
                    WHERE (started_at AT TIME ZONE 'Asia/Shanghai')::date = d.day),
                'units', (WITH day_calls AS (
                    SELECT * FROM filtered
                    WHERE (started_at AT TIME ZONE 'Asia/Shanghai')::date = d.day)
                    {daily_units})) ORDER BY d.day)
            FROM (SELECT DISTINCT (started_at AT TIME ZONE 'Asia/Shanghai')::date AS day
                  FROM filtered WHERE billable) d
        ), '[]'::jsonb),
        'groups', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'service', g.service, 'model', g.model,
                'totals', (SELECT {_TOTALS} FROM filtered
                    WHERE receipt->>'service' = g.service AND receipt->>'model' = g.model),
                'units', (WITH group_calls AS (
                    SELECT * FROM filtered
                    WHERE receipt->>'service' = g.service AND receipt->>'model' = g.model)
                    {group_units})) ORDER BY g.service, g.model)
            FROM (SELECT DISTINCT receipt->>'service' AS service,
                                  receipt->>'model' AS model
                  FROM filtered WHERE billable) g
        ), '[]'::jsonb))
    """,
        tuple(parameters),
    )


def usage_result(row: tuple[object, ...] | None) -> dict[str, object]:
    if row is None:
        raise ValueError("USAGE-CALL-NOT-FOUND")
    if not isinstance(row[0], dict):
        raise ValueError("USAGE-QUERY-RESULT")
    return cast(dict[str, object], row[0])


__all__ = ("usage_result", "usage_statement")
