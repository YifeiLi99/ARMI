"""Unit checks for transaction contracts and the redacted error boundary."""

from __future__ import annotations

import unittest
from uuid import UUID

import psycopg
from armi_kernel.application import (
    CasStatus,
    LockPlan,
    LockTarget,
    LockTargetKind,
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
        self.assertEqual(
            tuple(LockTargetKind),
            (
                LockTargetKind.SUBJECT,
                LockTargetKind.LIFE_RUNTIME,
                LockTargetKind.SUBJECT_COMPONENT,
                LockTargetKind.RELATIONSHIP,
                LockTargetKind.ACTIVITY,
                LockTargetKind.MEMORY,
                LockTargetKind.GOVERNANCE_EFFECT,
            ),
        )

    def test_lock_plan_uses_kind_then_unsigned_uuid_bytes(self) -> None:
        plan = LockPlan(
            (
                LockTarget(LockTargetKind.MEMORY, _SECOND, None),
                LockTarget(LockTargetKind.SUBJECT, _SECOND, 4),
                LockTarget(LockTargetKind.SUBJECT, _FIRST, 3),
                LockTarget(LockTargetKind.ACTIVITY, _FIRST, None),
            )
        )
        self.assertEqual(
            [(target.kind, target.object_id) for target in plan.targets],
            [
                (LockTargetKind.SUBJECT, _FIRST),
                (LockTargetKind.SUBJECT, _SECOND),
                (LockTargetKind.ACTIVITY, _FIRST),
                (LockTargetKind.MEMORY, _SECOND),
            ],
        )

    def test_duplicate_target_and_illegal_version_are_rejected(self) -> None:
        target = LockTarget(LockTargetKind.SUBJECT, _FIRST, 0)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            LockPlan((target, target))
        for value in (-1, True, 1.5):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "expected_version"),
            ):
                LockTarget(
                    LockTargetKind.SUBJECT,
                    _FIRST,
                    value,  # type: ignore[arg-type]
                )

    def test_cas_root_requires_expected_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "CAS root"):
            LockPlan.for_cas(LockTarget(LockTargetKind.SUBJECT, _FIRST, None))
        plan = LockPlan.for_cas(
            LockTarget(LockTargetKind.SUBJECT, _FIRST, 0),
            LockTarget(LockTargetKind.ACTIVITY, _SECOND, None),
        )
        self.assertEqual(plan.targets[0].expected_version, 0)

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
