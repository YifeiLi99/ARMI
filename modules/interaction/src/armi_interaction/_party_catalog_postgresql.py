"""Interaction-owned party roster used by cross-module coordinators."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLInteractionPartyCatalog:
    async def all_party_ids(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                "SELECT party_id FROM armi.parties ORDER BY party_id"
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    def admin_party_ids(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> tuple[UUID, ...]:
        rows = connection.execute(
            "SELECT party_id FROM armi.parties ORDER BY party_id"
        ).fetchall()
        return tuple(row[0] for row in rows)


__all__ = ("PostgreSQLInteractionPartyCatalog",)
