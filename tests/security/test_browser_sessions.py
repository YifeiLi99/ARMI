from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
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

    def test_lease_is_generation_and_monotonic_deadline_fenced(self) -> None:
        established = self.store.establish()
        lease = self.store.lease(established.token)
        self.assertEqual(self.store.validate_lease(lease).creator_party_id, CREATOR_ID)
        self.store.revoke_all()
        with self.assertRaises(BrowserSessionViolation):
            self.store.validate_lease(lease)

        replacement = self.store.establish()
        replacement_lease = self.store.lease(replacement.token)
        self.clock.value += 28_800
        with self.assertRaises(BrowserSessionViolation):
            self.store.validate_lease(replacement_lease)

    def test_lease_cannot_borrow_replacement_session_after_token_verification(self):
        first = self.store.establish()
        original_lock = self.store._lock
        replacement_tokens = []
        store = self.store

        class RotateOnFirstUnlock:
            armed = True

            def __enter__(self):
                original_lock.acquire()

            def __exit__(self, *_args):
                original_lock.release()
                if self.armed:
                    self.armed = False
                    store.revoke_all()
                    replacement_tokens.append(store.establish().token)

        # Simulate another caller rotating the session at the first unlocked boundary.
        with patch.object(self.store, "_lock", RotateOnFirstUnlock()):
            lease = self.store.lease(first.token)
            self.assertEqual(len(replacement_tokens), 1)
            self.assertNotEqual(first.token, replacement_tokens[0])
            with self.assertRaises(BrowserSessionViolation):
                self.store.validate_lease(lease)
            self.store.verify(replacement_tokens[0])


if __name__ == "__main__":
    unittest.main()
