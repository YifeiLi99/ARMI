"""Read the authoritative origin of a subject-requested observation."""

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLVisualOriginRead:
    async def origin_episode(
        self, transaction: PostgreSQLTransaction, *, observation_id: UUID
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """SELECT origin_episode_id FROM armi.live_vision_observations
                   WHERE observation_id=%s""",
                (observation_id,),
            )
        ).fetchone()
        return None if row is None else row[0]
