"""Data Rights-owned offline access to managed snapshot scope records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


class PostgreSQLManagedSnapshotAdmin:
    def party_scopes(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        party_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, int, int], ...]:
        rows = connection.execute(
            """SELECT requested.party_id,
                      COALESCE(fence.contact_generation,1),
                      COALESCE(fence.use_generation,1)
               FROM unnest(%s::uuid[]) AS requested(party_id)
               LEFT JOIN armi.data_rights_party_fences AS fence
                 ON fence.party_id=requested.party_id
               ORDER BY requested.party_id""",
            (list(party_ids),),
        ).fetchall()
        return tuple((row[0], int(row[1]), int(row[2])) for row in rows)

    def register(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        snapshot_id: UUID,
        snapshot_kind: str,
        contract_version: str,
        managed_path: str,
        party_scopes: tuple[tuple[UUID, int, int], ...],
    ) -> None:
        connection.execute(
            """INSERT INTO armi.managed_data_snapshots (
                   managed_snapshot_id,snapshot_kind,contract_version,managed_path)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (managed_snapshot_id) DO NOTHING""",
            (snapshot_id, snapshot_kind, contract_version, managed_path),
        )
        for party_id, contact_generation, use_generation in party_scopes:
            connection.execute(
                """INSERT INTO armi.managed_data_snapshot_parties (
                       managed_snapshot_id,party_id,contact_generation,use_generation)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (managed_snapshot_id,party_id) DO NOTHING""",
                (
                    snapshot_id,
                    party_id,
                    contact_generation,
                    use_generation,
                ),
            )


__all__ = ("PostgreSQLManagedSnapshotAdmin",)
