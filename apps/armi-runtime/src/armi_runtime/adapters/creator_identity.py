"""Read-only database adapter for the unique born Creator identity."""

from __future__ import annotations

from uuid import UUID

import psycopg


def read_creator_party_id(conninfo: str) -> UUID | None:
    """Return the sole active primary Creator without exposing connection details."""

    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT party_id
                FROM armi.parties
                WHERE party_kind = 'creator'
                  AND creator_role = 'unique_primary_creator'
                  AND status = 'active'
                """
            ).fetchall()
    except psycopg.Error:
        return None
    if len(rows) != 1 or not isinstance(rows[0][0], UUID):
        return None
    return rows[0][0]


__all__ = ("read_creator_party_id",)
