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


async def last_voice_activity(
    transaction: PostgreSQLTransaction, *, subject_id: UUID
) -> datetime | None:
    row = await (
        await transaction.execute(
            "SELECT max(last_voice_ended_at) FROM armi.interaction_scenes WHERE subject_id=%s",
            (subject_id,),
        )
    ).fetchone()
    return None if row is None else row[0]


async def mark_voice_activity_ended(
    transaction: PostgreSQLTransaction, *, scene_ids: tuple[UUID, ...]
) -> None:
    await transaction.execute(
        "UPDATE armi.interaction_scenes SET last_voice_ended_at=statement_timestamp() "
        "WHERE scene_id=ANY(%s::uuid[])",
        (list(scene_ids),),
    )
