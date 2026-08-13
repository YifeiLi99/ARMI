"""Read-only PostgreSQL backlog and storage observations for Runtime operations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import LiteralString

from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)

_COUNT_QUERIES: dict[str, LiteralString] = {
    "armi.durable_work": (
        "SELECT status, count(*) FROM armi.durable_work GROUP BY status ORDER BY status"
    ),
    "armi.effects": (
        "SELECT status, count(*) FROM armi.effects GROUP BY status ORDER BY status"
    ),
}
_AGE_QUERIES: dict[tuple[str, str, str], LiteralString] = {
    (
        "armi.durable_work",
        "status IN ('ready', 'leased')",
        "created_at",
    ): (
        "SELECT EXTRACT(EPOCH FROM (clock_timestamp() - min(created_at))) "
        "FROM armi.durable_work WHERE status IN ('ready', 'leased')"
    ),
    (
        "armi.effects",
        "status IN ('registered', 'dispatching', 'unknown')",
        "registered_at",
    ): (
        "SELECT EXTRACT(EPOCH FROM (clock_timestamp() - min(registered_at))) "
        "FROM armi.effects "
        "WHERE status IN ('registered', 'dispatching', 'unknown')"
    ),
}


class RuntimeObservationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseObservation:
    work_counts: tuple[tuple[str, int], ...]
    work_oldest_open_seconds: int | None
    effect_counts: tuple[tuple[str, int], ...]
    effect_oldest_open_seconds: int | None
    active_runtime_count: int
    runtime_heartbeat_age_seconds: int | None
    artifact_counts: tuple[tuple[str, int], ...]
    artifact_bytes: int
    database_bytes: int


class PostgreSQLRuntimeObservation:
    """Own one read-only diagnostic connection without write authority."""

    __slots__ = ("_factory",)

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
    ) -> None:
        self._factory = factory

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def collect(self) -> DatabaseObservation:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                work_counts = await _counts(connection, "armi.durable_work")
                work_age = await _oldest_age(
                    connection,
                    "armi.durable_work",
                    "status IN ('ready', 'leased')",
                    "created_at",
                )
                effect_counts = await _counts(connection, "armi.effects")
                effect_age = await _oldest_age(
                    connection,
                    "armi.effects",
                    "status IN ('registered', 'dispatching', 'unknown')",
                    "registered_at",
                )
                runtime_row = await (
                    await connection.execute(
                        """
                            SELECT count(*) FILTER (WHERE status = 'active'),
                                   EXTRACT(EPOCH FROM (
                                       clock_timestamp() - min(last_heartbeat_at)
                                           FILTER (WHERE status = 'active')
                                   ))
                            FROM armi.runtime_instances
                            """
                    )
                ).fetchone()
                artifact_rows = await (
                    await connection.execute(
                        """
                            SELECT integrity_status, count(*),
                                   COALESCE(sum(byte_size), 0)
                            FROM armi.artifacts
                            GROUP BY integrity_status
                            ORDER BY integrity_status
                            """
                    )
                ).fetchall()
                database_row = await (
                    await connection.execute(
                        "SELECT pg_database_size(current_database())"
                    )
                ).fetchone()
        except RuntimeTransactionFailure, RuntimeObservationError:
            raise RuntimeObservationError(
                "OBSERVABILITY_DATABASE_UNAVAILABLE"
            ) from None
        if runtime_row is None or database_row is None:
            raise RuntimeObservationError("OBSERVABILITY_DATABASE_SHAPE")
        return DatabaseObservation(
            work_counts=work_counts,
            work_oldest_open_seconds=work_age,
            effect_counts=effect_counts,
            effect_oldest_open_seconds=effect_age,
            active_runtime_count=int(runtime_row[0]),
            runtime_heartbeat_age_seconds=_age(runtime_row[1]),
            artifact_counts=tuple(
                (str(status), int(count)) for status, count, _bytes in artifact_rows
            ),
            artifact_bytes=sum(int(row[2]) for row in artifact_rows),
            database_bytes=int(database_row[0]),
        )


async def _counts(
    connection: PostgreSQLTransaction, table: str
) -> tuple[tuple[str, int], ...]:
    query = _COUNT_QUERIES.get(table)
    if query is None:
        raise RuntimeObservationError("OBSERVABILITY_DATABASE_QUERY")
    rows = await (await connection.execute(query)).fetchall()
    return tuple((str(status), int(count)) for status, count in rows)


async def _oldest_age(
    connection: PostgreSQLTransaction,
    table: str,
    predicate: str,
    timestamp_column: str,
) -> int | None:
    query = _AGE_QUERIES.get((table, predicate, timestamp_column))
    if query is None:
        raise RuntimeObservationError("OBSERVABILITY_DATABASE_QUERY")
    row = await (await connection.execute(query)).fetchone()
    return _age(None if row is None else row[0])


def _age(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | float | Decimal):
        raise RuntimeObservationError("OBSERVABILITY_DATABASE_SHAPE")
    return max(0, int(value))


__all__ = (
    "DatabaseObservation",
    "PostgreSQLRuntimeObservation",
    "RuntimeObservationError",
)
