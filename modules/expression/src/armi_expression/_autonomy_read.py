"""Owner-owned activity facts for autonomy admission; no cross-owner SQL."""

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


async def response_intent_ids(
    transaction: PostgreSQLTransaction, *, subject_id: UUID
) -> tuple[UUID, ...]:
    rows = await (
        await transaction.execute(
            """SELECT action_intent_id FROM armi.action_intents
           WHERE subject_id=%s AND action_kind='party_response'""",
            (subject_id,),
        )
    ).fetchall()
    return tuple(row[0] for row in rows)
