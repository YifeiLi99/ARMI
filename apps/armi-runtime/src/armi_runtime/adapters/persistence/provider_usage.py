"""Authenticated usage reads from owner projection and local Admin receipts."""

import asyncio
from pathlib import Path
from typing import LiteralString, cast

from armi_kernel.application import UsageQuery
from armi_local_control import ProviderCheckReceipts
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    usage_result,
    usage_statement,
)


class PostgreSQLUsageQuery:
    def __init__(self, factory: PostgreSQLRuntimeUnitOfWorkFactory, root: Path) -> None:
        self._factory = factory
        self._receipts = ProviderCheckReceipts(root)

    async def query(self, request: UsageQuery) -> dict[str, object]:
        checks = await asyncio.to_thread(self._receipts.read)
        statement, parameters = usage_statement(request, checks)
        async with self._factory.unit_of_work(read_only=True) as unit:
            # SQL fragments are fixed in usage_statement; filter values are parameters.
            row = await (
                await unit.transaction.execute(
                    cast(LiteralString, statement), parameters
                )
            ).fetchone()
        return usage_result(row)
