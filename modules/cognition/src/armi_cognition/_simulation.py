"""Owner's pending work and deadlines for the isolated simulation clock."""

from armi_runtime_foundation import PostgreSQLTransaction, SimulationState


class SimulationRead:
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState:
        row = await (
            await transaction.execute(
                """SELECT EXISTS(SELECT 1 FROM armi.cognitive_episodes WHERE status IN ('preparing','prepared','calling_model','finalizing')), NULL::timestamptz"""
            )
        ).fetchone()
        assert row is not None
        return SimulationState(bool(row[0]), row[1])
