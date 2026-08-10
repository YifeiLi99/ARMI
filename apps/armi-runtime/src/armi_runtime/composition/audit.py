"""Explicit operational audit query composition; never wired to product surfaces."""

from __future__ import annotations

from armi_kernel.application import AuditQuery, AuditQueryResult

from armi_runtime.adapters.persistence.audit_events import AuditEventRepository
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)


class AuditQueryGateway:
    __slots__ = ("_repository", "_unit_of_work_factory")

    def __init__(
        self,
        repository: AuditEventRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    ) -> None:
        self._repository = repository
        self._unit_of_work_factory = unit_of_work_factory

    async def query(self, query: AuditQuery) -> AuditQueryResult:
        async with self._unit_of_work_factory.unit_of_work(
            read_only=True,
        ) as unit_of_work:
            return await self._repository.query(unit_of_work, query)


__all__ = ("AuditQueryGateway",)
