from __future__ import annotations

import unittest
from uuid import uuid7

from armi_kernel.application import (
    ExecutionCustodyMode,
    ExecutionCustodyPermit,
    ExecutionCustodyRequest,
    ExecutionCustodyScope,
    ExecutionCustodyScopeKind,
    ExecutionCustodyViolation,
    ordered_custody_requests,
)


class ExecutionCustodyContractTests(unittest.TestCase):
    def test_requests_are_ordered_by_scope_then_reference(self) -> None:
        runtime_id, first_party, second_party, scene_id = sorted(
            (uuid7(), uuid7(), uuid7(), uuid7()), key=lambda value: value.int
        )
        requests = ordered_custody_requests(
            ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.OUTREACH_SCENE, scene_id
                ),
                ExecutionCustodyMode.EXCLUSIVE,
            ),
            ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY, second_party
                ),
                ExecutionCustodyMode.SHARED,
            ),
            ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.RUNTIME_AUTHORITY, runtime_id
                ),
                ExecutionCustodyMode.SHARED,
            ),
            ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY, first_party
                ),
                ExecutionCustodyMode.SHARED,
            ),
        )

        self.assertEqual(
            tuple(request.scope.kind for request in requests),
            (
                ExecutionCustodyScopeKind.RUNTIME_AUTHORITY,
                ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY,
                ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY,
                ExecutionCustodyScopeKind.OUTREACH_SCENE,
            ),
        )
        self.assertEqual(requests[1].scope.reference, first_party)
        self.assertEqual(requests[2].scope.reference, second_party)

    def test_duplicate_scope_is_rejected(self) -> None:
        scope = ExecutionCustodyScope(
            ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY, uuid7()
        )
        with self.assertRaises(ExecutionCustodyViolation) as raised:
            ordered_custody_requests(
                ExecutionCustodyRequest(scope, ExecutionCustodyMode.SHARED),
                ExecutionCustodyRequest(scope, ExecutionCustodyMode.EXCLUSIVE),
            )
        self.assertEqual(raised.exception.code, "CUSTODY-ORDER")

    def test_callers_cannot_construct_an_out_of_order_permit(self) -> None:
        runtime = ExecutionCustodyRequest(
            ExecutionCustodyScope(ExecutionCustodyScopeKind.RUNTIME_AUTHORITY, uuid7()),
            ExecutionCustodyMode.SHARED,
        )
        party = ExecutionCustodyRequest(
            ExecutionCustodyScope(ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY, uuid7()),
            ExecutionCustodyMode.SHARED,
        )
        with self.assertRaises(ExecutionCustodyViolation) as raised:
            ExecutionCustodyPermit((party, runtime))
        self.assertEqual(raised.exception.code, "CUSTODY-ORDER")


if __name__ == "__main__":
    unittest.main()
