"""Read-only current-schema gateway for the Admin MCP tools."""

from __future__ import annotations

from dataclasses import dataclass

from armi_postgresql_contract import verify_postgresql_contract

from .role_session import AdminRoleBoundPool


@dataclass(frozen=True, slots=True)
class AdminSchemaSnapshot:
    server_version_num: int
    encoding: str
    timezone: str
    tables: tuple[str, ...]
    revision: str
    baseline_identity: str
    resource_digest: str
    catalog_digest: str
    role_policy_digest: str


class AdminSchemaGateway:
    """Open one role-bound pool and execute only fixed read statements."""

    __slots__ = ("_pool",)

    def __init__(self, pool: AdminRoleBoundPool) -> None:
        self._pool = pool

    def read_snapshot(self) -> AdminSchemaSnapshot:
        with self._pool.connection() as connection:
            evidence = verify_postgresql_contract(connection)
            rows = connection.execute(
                """
                    SELECT relation.relname
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'armi'
                      AND relation.relkind IN ('r', 'p')
                    ORDER BY relation.relname
                    """
            ).fetchall()
        return AdminSchemaSnapshot(
            server_version_num=evidence.server_version_num,
            encoding=evidence.encoding,
            timezone=evidence.timezone,
            tables=tuple(str(row[0]) for row in rows),
            revision=evidence.revision,
            baseline_identity=evidence.baseline_identity,
            resource_digest=evidence.resource_digest,
            catalog_digest=evidence.catalog_digest,
            role_policy_digest=evidence.role_policy_digest,
        )


__all__ = ("AdminSchemaGateway", "AdminSchemaSnapshot")
