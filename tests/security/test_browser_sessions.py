from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from armi_runtime.interfaces.browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
)

ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
CREATOR_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234568")
CREATOR_BEARER = f"creator-v1.{'a' * 43}"


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class BrowserSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.store = BrowserSessionStore(
            creator_bearer=CREATOR_BEARER.encode(),
            environment_id=ENVIRONMENT_ID,
            creator_party_id=CREATOR_ID,
            bootstrap_ttl_seconds=120,
            session_ttl_seconds=28_800,
            monotonic=self.clock,
        )

    def test_issue_exchange_verify_and_revoke(self) -> None:
        issued = self.store.issue(CREATOR_BEARER)
        self.assertRegex(issued.code, r"^bootstrap-v1\.[A-Za-z0-9_-]{22}$")
        established = self.store.exchange(issued.code)
        self.assertRegex(established.token, r"^browser-v1\.[A-Za-z0-9_-]{43}$")
        self.assertEqual(
            self.store.verify(established.token).creator_party_id,
            CREATOR_ID,
        )
        self.store.revoke(established.token)
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify(established.token)

    def test_new_code_and_new_session_revoke_the_old_value(self) -> None:
        first_code = self.store.issue(CREATOR_BEARER).code
        second_code = self.store.issue(CREATOR_BEARER).code
        with self.assertRaises(BrowserSessionViolation):
            self.store.exchange(first_code)
        first_session = self.store.exchange(second_code).token
        next_session = self.store.exchange(self.store.issue(CREATOR_BEARER).code).token
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify(first_session)
        self.store.verify(next_session)

    def test_expiry_replay_wrong_kind_and_restart_are_rejected(self) -> None:
        code = self.store.issue(CREATOR_BEARER).code
        self.clock.value += 120
        with self.assertRaises(BrowserSessionViolation):
            self.store.exchange(code)

        token = self.store.exchange(self.store.issue(CREATOR_BEARER).code).token
        with self.assertRaises(BrowserSessionViolation):
            self.store.exchange(token)
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify(CREATOR_BEARER)
        self.store.revoke_all()
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify(token)
        restarted = BrowserSessionStore(
            creator_bearer=CREATOR_BEARER.encode(),
            environment_id=ENVIRONMENT_ID,
            creator_party_id=CREATOR_ID,
            bootstrap_ttl_seconds=120,
            session_ttl_seconds=28_800,
            monotonic=self.clock,
        )
        with self.assertRaises(BrowserSessionViolation):
            restarted.verify(token)

    def test_concurrent_exchange_has_exactly_one_winner(self) -> None:
        code = self.store.issue(CREATOR_BEARER).code

        def exchange() -> bool:
            try:
                self.store.exchange(code)
            except BrowserSessionViolation:
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = tuple(executor.map(lambda _index: exchange(), range(8)))
        self.assertEqual(results.count(True), 1)

    def test_sixth_failure_is_rate_limited_and_errors_are_secret_free(self) -> None:
        for _ in range(5):
            with self.assertRaisesRegex(
                BrowserSessionViolation,
                "^AUTH_CREATOR_REJECTED$",
            ):
                self.store.issue(f"creator-v1.{'b' * 43}")
        with self.assertRaisesRegex(
            BrowserSessionViolation,
            "^AUTH_RATE_LIMITED$",
        ):
            self.store.issue(CREATOR_BEARER)
        self.assertNotIn(CREATOR_BEARER, repr(self.store))

    def test_invalid_long_bearer_never_constructs_a_store(self) -> None:
        with self.assertRaisesRegex(
            BrowserSessionViolation,
            "^SEC_CREATOR_BEARER_FORMAT$",
        ):
            BrowserSessionStore(
                creator_bearer=b"short",
                environment_id=ENVIRONMENT_ID,
                creator_party_id=CREATOR_ID,
                bootstrap_ttl_seconds=120,
                session_ttl_seconds=28_800,
            )

    def test_browser_session_failures_are_rate_limited(self) -> None:
        for _ in range(5):
            with self.assertRaisesRegex(
                BrowserSessionViolation,
                "^AUTH_SESSION_REQUIRED$",
            ):
                self.store.verify(f"browser-v1.{'z' * 43}")
        with self.assertRaisesRegex(
            BrowserSessionViolation,
            "^AUTH_RATE_LIMITED$",
        ):
            self.store.verify(f"browser-v1.{'z' * 43}")


if __name__ == "__main__":
    unittest.main()
