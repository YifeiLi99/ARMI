"""Fixed migrator operation used only by disposable environment reset."""

from __future__ import annotations

import psycopg


class AdminEnvironmentMigrationGateway:
    """Remove only the packaged ARMI schema so migration 0001 recreates it."""

    __slots__ = ()

    @staticmethod
    def recreate_empty_schema(conninfo: str) -> None:
        with psycopg.connect(conninfo, autocommit=False) as connection:
            connection.execute("SET LOCAL ROLE armi_owner")
            connection.execute("DROP SCHEMA IF EXISTS armi CASCADE")
            connection.commit()


__all__ = ("AdminEnvironmentMigrationGateway",)
