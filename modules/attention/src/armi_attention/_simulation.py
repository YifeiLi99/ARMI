"""Owner's pending work and deadlines for the isolated simulation clock."""

from armi_runtime_foundation import PostgreSQLTransaction, SimulationState


class SimulationRead:
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState:
        row = await (
            await transaction.execute(
                """SELECT EXISTS(SELECT 1 FROM armi.opportunities WHERE current_disposition IN ('open','selected') AND available_after<=armi.business_time(statement_timestamp())), (SELECT min(at) FROM (SELECT available_after AS at FROM armi.opportunities WHERE current_disposition='open' UNION ALL SELECT next_consideration_at FROM armi.autonomy_plans WHERE (policy->>'enabled')::boolean AND phase='waiting') deadlines WHERE at>armi.business_time(statement_timestamp()))"""
            )
        ).fetchone()
        assert row is not None
        return SimulationState(bool(row[0]), row[1])
