"""Stable and redacted PostgreSQL transaction failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import psycopg
from psycopg_pool import PoolTimeout


class DatabaseFailureKind(StrEnum):
    CONFLICT = "conflict"
    CONSTRAINT = "constraint"
    DEPENDENCY = "dependency"
    INTEGRITY = "integrity"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class CommitState(StrEnum):
    NOT_STARTED = "not_started"
    ROLLED_BACK = "rolled_back"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class _FailureDefinition:
    code: str
    kind: DatabaseFailureKind
    retryable_reassessment: bool = False


_BY_SQLSTATE = {
    "40001": _FailureDefinition(
        "DB-TX-SERIALIZATION",
        DatabaseFailureKind.CONFLICT,
        retryable_reassessment=True,
    ),
    "40P01": _FailureDefinition(
        "DB-TX-DEADLOCK",
        DatabaseFailureKind.CONFLICT,
        retryable_reassessment=True,
    ),
    "55P03": _FailureDefinition("DB-TX-LOCK-UNAVAILABLE", DatabaseFailureKind.CONFLICT),
    "57014": _FailureDefinition(
        "DB-TX-STATEMENT-TIMEOUT", DatabaseFailureKind.DEPENDENCY
    ),
    "23505": _FailureDefinition("DB-TX-UNIQUE", DatabaseFailureKind.CONSTRAINT),
    "23503": _FailureDefinition("DB-TX-FOREIGN-KEY", DatabaseFailureKind.CONSTRAINT),
    "23514": _FailureDefinition("DB-TX-CHECK", DatabaseFailureKind.CONSTRAINT),
    "23502": _FailureDefinition("DB-TX-NOT-NULL", DatabaseFailureKind.CONSTRAINT),
    "42501": _FailureDefinition("DB-TX-PRIVILEGE", DatabaseFailureKind.INTEGRITY),
    "25P02": _FailureDefinition("DB-TX-ABORTED", DatabaseFailureKind.INTERNAL),
}
_COMMIT_UNKNOWN_SQLSTATES = frozenset({"08007", "40003"})


@dataclass(frozen=True, slots=True)
class DatabaseTransactionError(RuntimeError):
    code: str
    kind: DatabaseFailureKind
    retryable_reassessment: bool
    commit_state: CommitState

    def __str__(self) -> str:
        return f"{self.code}: database transaction failed"


def map_database_error(
    error: BaseException,
    *,
    during_commit: bool = False,
    rolled_back: bool = False,
) -> DatabaseTransactionError:
    if isinstance(error, PoolTimeout):
        definition = _FailureDefinition(
            "DB-TX-POOL-TIMEOUT", DatabaseFailureKind.DEPENDENCY
        )
    else:
        sqlstate = error.sqlstate if isinstance(error, psycopg.Error) else None
        if sqlstate in _COMMIT_UNKNOWN_SQLSTATES:
            return DatabaseTransactionError(
                "DB-TX-COMMIT-UNKNOWN",
                DatabaseFailureKind.UNKNOWN,
                False,
                CommitState.UNKNOWN,
            )
        if sqlstate in _BY_SQLSTATE:
            definition = _BY_SQLSTATE[sqlstate]
        elif during_commit and (
            sqlstate is None
            or sqlstate.startswith("08")
            or isinstance(error, psycopg.OperationalError)
        ):
            return DatabaseTransactionError(
                "DB-TX-COMMIT-UNKNOWN",
                DatabaseFailureKind.UNKNOWN,
                False,
                CommitState.UNKNOWN,
            )
        elif (sqlstate is not None and sqlstate.startswith("08")) or isinstance(
            error, psycopg.OperationalError
        ):
            definition = _FailureDefinition(
                "DB-TX-CONNECTION", DatabaseFailureKind.DEPENDENCY
            )
        else:
            definition = _FailureDefinition(
                "DB-TX-UNEXPECTED", DatabaseFailureKind.INTERNAL
            )
    return DatabaseTransactionError(
        definition.code,
        definition.kind,
        definition.retryable_reassessment,
        CommitState.ROLLED_BACK if rolled_back else CommitState.NOT_STARTED,
    )


__all__ = (
    "CommitState",
    "DatabaseFailureKind",
    "DatabaseTransactionError",
    "map_database_error",
)
