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


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class BrowserSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.store = BrowserSessionStore(
            environment_id=ENVIRONMENT_ID,
            creator_party_id=CREATOR_ID,
            session_ttl_seconds=28_800,
            monotonic=self.clock,
        )

    def test_establish_verify_and_runtime_shutdown(self) -> None:
        established = self.store.establish()
        self.assertRegex(established.token, r"^browser-v1\.[A-Za-z0-9_-]{43}$")
        self.assertEqual(
            self.store.verify(established.token).creator_party_id,
            CREATOR_ID,
        )
        self.store.revoke_all()
        with self.assertRaisesRegex(
            BrowserSessionViolation,
            "^AUTH_SESSION_REQUIRED$",
        ):
            self.store.verify(established.token)

    def test_multiple_local_tabs_share_the_process_connection(self) -> None:
        first = self.store.establish().token
        second = self.store.establish().token
        self.assertEqual(first, second)
        self.store.verify(first)
        self.store.verify(second)

    def test_expired_wrong_kind_and_restart_tokens_are_rejected(self) -> None:
        token = self.store.establish().token
        self.clock.value += 28_800
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify(token)
        with self.assertRaises(BrowserSessionViolation):
            self.store.verify("not-a-browser-token")
        restarted = BrowserSessionStore(
            environment_id=ENVIRONMENT_ID,
            creator_party_id=CREATOR_ID,
            session_ttl_seconds=28_800,
            monotonic=self.clock,
        )
        with self.assertRaises(BrowserSessionViolation):
            restarted.verify(token)

    def test_concurrent_establish_returns_one_process_connection(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            tokens = tuple(
                executor.map(lambda _index: self.store.establish().token, range(8))
            )

        self.assertEqual(len(set(tokens)), 1)
        self.store.verify(tokens[0])

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            BrowserSessionViolation,
            "^SEC_CREATOR_CONFIGURATION$",
        ):
            BrowserSessionStore(
                environment_id=ENVIRONMENT_ID,
                creator_party_id=CREATOR_ID,
                session_ttl_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
