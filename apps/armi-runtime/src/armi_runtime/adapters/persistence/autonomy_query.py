"""Read autonomous status and history through the common database query."""

from datetime import datetime
from typing import Literal, LiteralString, cast

from armi_attention.api import LifeOpportunityFactsPort, project_signal_status
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    autonomy_result,
    autonomy_statement,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort


class PostgreSQLAutonomyQuery:
    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        sleep: SleepReadPort,
        subject_state: SubjectStateReadPort,
        facts: LifeOpportunityFactsPort,
    ) -> None:
        self._factory = factory
        self._sleep = sleep
        self._subject_state = subject_state
        self._facts = facts

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
            result = autonomy_result(row)
            consumed = frozenset(
                (key[0], key[1], key[2])
                for key in cast(list[list[str]], result.pop("consumed_signal_keys", []))
            )
            if (
                mode == "status"
                and unit.runtime_fence is not None
                and result.get("observed_at") is not None
            ):
                signals = await self._facts.consideration_signals(
                    unit.transaction,
                    subject_id=unit.runtime_fence.subject_id,
                    minimum_delay_seconds=cast(
                        int,
                        cast(dict[str, object], result["policy"])[
                            "minimum_consideration_seconds"
                        ],
                    ),
                )
                project_signal_status(result, signals, consumed)
                result["concerns"] = await self._subject_state.attention_status(
                    unit.transaction,
                    subject_id=unit.runtime_fence.subject_id,
                    as_of=datetime.fromisoformat(str(result["observed_at"])),
                    consumed=consumed,
                )
            return result
