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

    async def rights_fence(
        self, transaction: PostgreSQLTransaction, *, party_id: UUID
    ) -> tuple[int, int] | None:
        row = await (
            await transaction.execute(
                "SELECT rights_contact_generation,rights_use_generation FROM armi.parties WHERE party_id=%s",
                (party_id,),
            )
        ).fetchone()
        return None if row is None else (int(row[0]), int(row[1]))

    async def advance_rights_fence(
        self, transaction: PostgreSQLTransaction, *, party_id: UUID, use_increment: int
    ) -> tuple[int, int] | None:
        row = await (
            await transaction.execute(
                """UPDATE armi.parties
               SET rights_contact_generation=rights_contact_generation+1,
                   rights_use_generation=rights_use_generation+%s,
                   rights_updated_at=statement_timestamp()
               WHERE party_id=%s RETURNING rights_contact_generation,rights_use_generation""",
                (use_increment, party_id),
            )
        ).fetchone()
        return None if row is None else (int(row[0]), int(row[1]))

    async def all_party_fences(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[tuple[UUID, int, int], ...]:
        rows = await (
            await transaction.execute(
                "SELECT party_id,rights_contact_generation,rights_use_generation FROM armi.parties ORDER BY party_id"
            )
        ).fetchall()
        return tuple((row[0], int(row[1]), int(row[2])) for row in rows)

    def admin_party_ids(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> tuple[UUID, ...]:
        rows = connection.execute(
            "SELECT party_id FROM armi.parties ORDER BY party_id"
        ).fetchall()
        return tuple(row[0] for row in rows)


__all__ = ("PostgreSQLInteractionPartyCatalog",)
