"""Owner-owned activity facts for autonomy admission; no cross-owner SQL."""

from datetime import datetime
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


async def voice_activity(
    transaction: PostgreSQLTransaction, *, subject_id: UUID
) -> tuple[bool, datetime | None]:
    row = await (
        await transaction.execute(
            """SELECT COALESCE(bool_or(ended_at IS NULL),false),max(ended_at)
           FROM armi.live_voice_sessions WHERE subject_id=%s""",
            (subject_id,),
        )
    ).fetchone()
    return (False, None) if row is None else (bool(row[0]), row[1])
