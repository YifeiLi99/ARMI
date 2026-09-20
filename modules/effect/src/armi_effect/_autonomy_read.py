"""Owner-owned activity facts for autonomy admission; no cross-owner SQL."""

from datetime import datetime
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


async def response_delivery_activity(
    transaction: PostgreSQLTransaction, *, action_intent_ids: tuple[UUID, ...]
) -> tuple[bool, datetime | None]:
    row = await (
        await transaction.execute(
            """SELECT COALESCE(bool_or(e.status IN ('registered','dispatching')
                    OR o.status IN ('ready','claimed')),false),
                  GREATEST(max(e.settled_at),max(o.delivered_at))
           FROM armi.effects e LEFT JOIN armi.effect_outbox_items o USING(effect_id)
           WHERE e.action_intent_id=ANY(%s::uuid[])""",
            (list(action_intent_ids),),
        )
    ).fetchone()
    return (False, None) if row is None else (bool(row[0]), row[1])
