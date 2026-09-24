"""Confirmed Runtime time; stopped or unconfirmed intervals never accrue."""

from decimal import Decimal
from typing import cast
from uuid import UUID

from .admin_transactions import PostgreSQLAdminTransaction
from .transactions import PostgreSQLTransaction


async def active_runtime_seconds(
    transaction: PostgreSQLTransaction, *, subject_id: UUID
) -> float:
    row = await (
        await transaction.execute(
            "SELECT COALESCE(sum(active_runtime_microseconds),0) FROM armi.runtime_instances WHERE subject_id=%s",
            (subject_id,),
        )
    ).fetchone()
    assert row is not None
    return float(cast(Decimal, row[0])) / 1_000_000


def active_runtime_seconds_admin(
    transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
) -> float:
    row = transaction.execute(
        "SELECT COALESCE(sum(active_runtime_microseconds),0) FROM armi.runtime_instances WHERE subject_id=%s",
        (subject_id,),
    ).fetchone()
    assert row is not None
    return float(cast(Decimal, row[0])) / 1_000_000
