"""Owner's pending work and deadlines for the isolated simulation clock."""

from armi_runtime_foundation import PostgreSQLTransaction, SimulationState


class SimulationRead:
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState:
        row = await (
            await transaction.execute(
                """SELECT EXISTS(SELECT 1 FROM armi.effects WHERE dispatch_status='claimed' OR (dispatch_status='ready' AND available_at<=armi.business_time(statement_timestamp()))), (SELECT min(available_at) FROM armi.effects WHERE dispatch_status='ready' AND available_at>armi.business_time(statement_timestamp()))"""
            )
        ).fetchone()
        assert row is not None
        return SimulationState(bool(row[0]), row[1])
