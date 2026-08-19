"""Read-only live-vision artifact reference discovery for admin corrections."""

from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLLiveVisionAdmin:
    __slots__ = ()

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            """SELECT count(*) FROM armi.live_vision_observation_frames
               WHERE artifact_id=%s""",
            (artifact_id,),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLLiveVisionAdmin",)
