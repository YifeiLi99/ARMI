"""Owner-owned activity facts for autonomy admission; no cross-owner SQL."""

from datetime import datetime
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


async def social_delivery_status(
    transaction: PostgreSQLTransaction, *, root_opportunity_id: UUID
) -> str:
    rows = await (
        await transaction.execute(
            """SELECT dispatch_status FROM armi.effects WHERE root_opportunity_id=%s
           AND effect_kind='creator_response'""",
            (root_opportunity_id,),
        )
    ).fetchall()
    if not rows:
        return "missing"
    states = {str(row[0]) for row in rows}
    if states <= {"delivered"}:
        return "delivered"
    if states & {"ready", "claimed"}:
        return "pending"
    return "unknown" if "unknown" in states else "failed"


async def response_delivery_activity(
    transaction: PostgreSQLTransaction, *, action_intent_ids: tuple[UUID, ...]
) -> tuple[bool, datetime | None]:
    row = await (
        await transaction.execute(
            """SELECT COALESCE(bool_or(e.status IN ('registered','dispatching')
                    OR e.dispatch_status IN ('ready','claimed')),false),
                  GREATEST(max(e.settled_at),max(e.delivered_at))
           FROM armi.effects e
           WHERE e.action_intent_id=ANY(%s::uuid[])""",
            (list(action_intent_ids),),
        )
    ).fetchone()
    return (False, None) if row is None else (bool(row[0]), row[1])
