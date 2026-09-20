"""Owner-owned activity facts for autonomy admission; no cross-owner SQL."""

from datetime import datetime
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


async def human_input_activity(
    transaction: PostgreSQLTransaction, *, subject_id: UUID
) -> tuple[bool, datetime | None]:
    row = await (
        await transaction.execute(
            """SELECT COALESCE(bool_or(recognition_status='pending'),false),max(received_at)
           FROM armi.party_input_interactions WHERE subject_id=%s
             AND addressed_to_subject IS DISTINCT FROM false""",
            (subject_id,),
        )
    ).fetchone()
    return (False, None) if row is None else (bool(row[0]), row[1])
