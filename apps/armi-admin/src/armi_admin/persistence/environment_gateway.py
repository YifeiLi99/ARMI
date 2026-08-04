"""Fixed migrator operation used only by disposable environment reset."""

from __future__ import annotations

import psycopg


class AdminEnvironmentSchemaGateway:
    """Remove the disposable ARMI schema before installing the current DDL."""

    __slots__ = ()

    @staticmethod
    def recreate_empty_schema(conninfo: str) -> None:
        with psycopg.connect(conninfo, autocommit=False) as connection:
            connection.execute("SET LOCAL ROLE armi_owner")
            connection.execute("DROP SCHEMA IF EXISTS armi CASCADE")
            connection.commit()


__all__ = ("AdminEnvironmentSchemaGateway",)
