"""Unit checks for transaction contracts and the redacted error boundary."""

from __future__ import annotations

import unittest
from uuid import UUID

import psycopg
from armi_kernel.application import (
    CasStatus,
    PostCommitAction,
    TransactionIsolation,
    classify_cas_rows,
)
from armi_runtime.adapters.transaction_errors import (
    CommitState,
    DatabaseFailureKind,
    map_database_error,
)
from psycopg_pool import PoolTimeout

_FIRST = UUID("01980f7d-7b8f-7000-8000-000000000001")
_SECOND = UUID("01980f7d-7b8f-7000-8000-000000000002")


class TransactionContractTests(unittest.TestCase):
    def test_isolation_values_are_exact(self) -> None:
        self.assertEqual(
            tuple(TransactionIsolation),
            (
                TransactionIsolation.READ_COMMITTED,
                TransactionIsolation.REPEATABLE_READ,
                TransactionIsolation.SERIALIZABLE,
            ),
        )

    def test_cas_row_count_is_strict(self) -> None:
        self.assertIs(classify_cas_rows(1), CasStatus.APPLIED)
        self.assertIs(classify_cas_rows(0), CasStatus.CONFLICT)
        for value in (-1, 2, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                classify_cas_rows(value)

    def test_post_commit_action_is_only_an_immutable_description(self) -> None:
        action = PostCommitAction("audit.append", _FIRST)
        self.assertEqual(action.kind, "audit.append")
        with self.assertRaises(ValueError):
            PostCommitAction("Callback()", _FIRST)
        with self.assertRaises(ValueError):
            PostCommitAction("audit.append", UUID(int=1))


class DatabaseErrorMappingTests(unittest.TestCase):
    def assert_mapping(
        self,
        error: BaseException,
        code: str,
        kind: DatabaseFailureKind,
        *,
        retryable: bool = False,
        during_commit: bool = False,
        commit_state: CommitState = CommitState.NOT_STARTED,
    ) -> None:
        mapped = map_database_error(error, during_commit=during_commit)
        self.assertEqual(mapped.code, code)
        self.assertIs(mapped.kind, kind)
        self.assertEqual(mapped.retryable_reassessment, retryable)
        self.assertIs(mapped.commit_state, commit_state)
        rendered = repr(mapped) + str(mapped)
        self.assertNotIn(str(error), rendered)
        self.assertNotIn("SELECT", rendered)

    def test_sqlstate_mapping_does_not_parse_messages(self) -> None:
        cases = (
            (
                psycopg.errors.SerializationFailure("private detail"),
                "DB-TX-SERIALIZATION",
                DatabaseFailureKind.CONFLICT,
                True,
            ),
            (
                psycopg.errors.DeadlockDetected("private detail"),
                "DB-TX-DEADLOCK",
                DatabaseFailureKind.CONFLICT,
                True,
            ),
            (
                psycopg.errors.LockNotAvailable("private detail"),
                "DB-TX-LOCK-UNAVAILABLE",
                DatabaseFailureKind.CONFLICT,
                False,
            ),
            (
                psycopg.errors.QueryCanceled("private detail"),
                "DB-TX-STATEMENT-TIMEOUT",
                DatabaseFailureKind.DEPENDENCY,
                False,
            ),
            (
                psycopg.errors.UniqueViolation("private detail"),
                "DB-TX-UNIQUE",
                DatabaseFailureKind.CONSTRAINT,
                False,
            ),
            (
                psycopg.errors.ForeignKeyViolation("private detail"),
                "DB-TX-FOREIGN-KEY",
                DatabaseFailureKind.CONSTRAINT,
                False,
            ),
            (
                psycopg.errors.CheckViolation("private detail"),
                "DB-TX-CHECK",
                DatabaseFailureKind.CONSTRAINT,
                False,
            ),
            (
                psycopg.errors.NotNullViolation("private detail"),
                "DB-TX-NOT-NULL",
                DatabaseFailureKind.CONSTRAINT,
                False,
            ),
            (
                psycopg.errors.InsufficientPrivilege("private detail"),
                "DB-TX-PRIVILEGE",
                DatabaseFailureKind.INTEGRITY,
                False,
            ),
            (
                psycopg.errors.InFailedSqlTransaction("private detail"),
                "DB-TX-ABORTED",
                DatabaseFailureKind.INTERNAL,
                False,
            ),
        )
        for error, code, kind, retryable in cases:
            with self.subTest(code=code):
                self.assert_mapping(
                    error,
                    code,
                    kind,
                    retryable=retryable,
                )

    def test_pool_connection_and_commit_unknown_are_distinct(self) -> None:
        self.assert_mapping(
            PoolTimeout("private detail"),
            "DB-TX-POOL-TIMEOUT",
            DatabaseFailureKind.DEPENDENCY,
        )
        self.assert_mapping(
            psycopg.OperationalError("private detail"),
            "DB-TX-CONNECTION",
            DatabaseFailureKind.DEPENDENCY,
        )
        self.assert_mapping(
            psycopg.OperationalError("private detail"),
            "DB-TX-COMMIT-UNKNOWN",
            DatabaseFailureKind.UNKNOWN,
            during_commit=True,
            commit_state=CommitState.UNKNOWN,
        )
        for error in (
            psycopg.errors.TransactionResolutionUnknown("private detail"),
            psycopg.errors.StatementCompletionUnknown("private detail"),
        ):
            with self.subTest(sqlstate=error.sqlstate):
                self.assert_mapping(
                    error,
                    "DB-TX-COMMIT-UNKNOWN",
                    DatabaseFailureKind.UNKNOWN,
                    commit_state=CommitState.UNKNOWN,
                )

    def test_rolled_back_state_is_explicit(self) -> None:
        mapped = map_database_error(
            psycopg.errors.UniqueViolation("private detail"),
            rolled_back=True,
        )
        self.assertIs(mapped.commit_state, CommitState.ROLLED_BACK)


if __name__ == "__main__":
    unittest.main()
