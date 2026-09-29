"""Owner's pending work and deadlines for the isolated simulation clock."""

from armi_runtime_foundation import PostgreSQLTransaction, SimulationState


class SimulationRead:
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState:
        row = await (
            await transaction.execute(
                """SELECT false, min(at) FROM (SELECT consideration_at AS at FROM armi.maintenance_sessions WHERE result_status='running' UNION ALL SELECT deadline_at FROM armi.maintenance_sessions WHERE result_status='running') deadlines WHERE at>armi.business_time(statement_timestamp())"""
            )
        ).fetchone()
        assert row is not None
        return SimulationState(bool(row[0]), row[1])
