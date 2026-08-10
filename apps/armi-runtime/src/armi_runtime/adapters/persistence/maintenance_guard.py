"""Read-only guard for destructive local retention maintenance."""

from __future__ import annotations

from armi_kernel.application import ArtifactViolation

from .unit_of_work import PostgreSQLUnitOfWork


class PostgreSQLMaintenanceGuard:
    __slots__ = ()

    async def require_runtime_stopped(self, unit_of_work: PostgreSQLUnitOfWork) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                "SELECT count(*) FROM armi.runtime_instances WHERE status = 'active'"
            )
        ).fetchone()
        if row is None:
            raise ArtifactViolation("ART-DATABASE")
        if int(row[0]) != 0:
            raise ArtifactViolation("ART-RUNTIME-ACTIVE")


__all__ = ("PostgreSQLMaintenanceGuard",)
