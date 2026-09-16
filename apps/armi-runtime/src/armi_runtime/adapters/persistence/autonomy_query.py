"""Read autonomous status and history through the common database query."""

from typing import Literal, LiteralString, cast

from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    autonomy_result,
    autonomy_statement,
)
from armi_sleep.api import SleepReadPort


class PostgreSQLAutonomyQuery:
    def __init__(
        self, factory: PostgreSQLRuntimeUnitOfWorkFactory, sleep: SleepReadPort
    ) -> None:
        self._factory = factory
        self._sleep = sleep

    async def query(
        self,
        mode: Literal["status", "history"],
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]:
        async with self._factory.unit_of_work(read_only=True) as unit:
            sleeping = False
            if mode == "status" and unit.runtime_fence is not None:
                sleeping = (
                    await self._sleep.active_maintenance(
                        unit.transaction, subject_id=unit.runtime_fence.subject_id
                    )
                    is not None
                )
            statement, parameters = autonomy_statement(
                mode, limit, offset, sleeping=sleeping
            )
            row = await (
                await unit.transaction.execute(
                    cast(LiteralString, statement), parameters
                )
            ).fetchone()
        return autonomy_result(row)
