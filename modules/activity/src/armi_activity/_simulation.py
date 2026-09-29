"""Owner's pending work and deadlines for the isolated simulation clock."""

from armi_runtime_foundation import PostgreSQLTransaction, SimulationState


class SimulationRead:
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState:
        row = await (
            await transaction.execute(
                """SELECT false, min(resume_not_before) FROM armi.activity_revisions WHERE is_current AND resume_not_before>armi.business_time(statement_timestamp())"""
            )
        ).fetchone()
        assert row is not None
        return SimulationState(bool(row[0]), row[1])
