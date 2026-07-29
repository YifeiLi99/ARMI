from __future__ import annotations

import unittest

from armi_runtime.composition.lifecycle import LifecycleController
from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.creator_contract import (
    Readiness,
    RejectedOutcomeResponse,
    UnavailableOutcomeResponse,
)
from armi_runtime.interfaces.static_assets import StaticAsset, StaticAssetStore
from fastapi.testclient import TestClient

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
AUTHORITY = "127.0.0.1:45678"


class CreatorRuntimeAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lifecycle = LifecycleController(environment_id=ENVIRONMENT_ID)
        self.assets = StaticAssetStore(
            {
                "index.html": StaticAsset(
                    b"<!doctype html><title>ARMI Creator</title>",
                    "text/html",
                    "no-store",
                ),
                "assets/app-a1.js": StaticAsset(
                    b"export {};",
                    "text/javascript",
                    "public, max-age=31536000, immutable",
                ),
            }
        )

    def _app(self):
        async def started() -> None:
            self.lifecycle.start()
            self.lifecycle.block()

        async def stopping() -> None:
            self.lifecycle.drain()
            self.lifecycle.stop()

        return create_runtime_app(
            readiness=lambda: self.lifecycle.snapshot().readiness,
            assets=self.assets,
            expected_authority=AUTHORITY,
            request_body_max_bytes=1024,
            on_started=started,
            on_stopping=stopping,
        )

    def test_health_and_static_surface_are_exact(self) -> None:
        with TestClient(
            self._app(),
            base_url=f"http://{AUTHORITY}",
        ) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            redirect = client.get("/ui", follow_redirects=False)
            index = client.get("/ui/")
            asset = client.get("/ui/assets/app-a1.js")

            self.assertEqual(live.status_code, 200)
            self.assertEqual(live.json(), {"status": "alive"})
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(ready.json(), {"status": "not_ready"})
            self.assertEqual(redirect.status_code, 308)
            self.assertEqual(redirect.headers["location"], "/ui/")
            self.assertEqual(index.status_code, 200)
            self.assertEqual(asset.status_code, 200)
            self.assertEqual(
                asset.headers["cache-control"],
                "public, max-age=31536000, immutable",
            )
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)
        self.assertEqual(
            self.lifecycle.snapshot().runtime_state.value,
            "stopped",
        )

    def test_protected_status_never_returns_200(self) -> None:
        with TestClient(
            self._app(),
            base_url=f"http://{AUTHORITY}",
        ) as client:
            missing = client.get("/v1/runtime/status")
            bearer = client.get(
                "/v1/runtime/status",
                headers={"Authorization": "Bearer local-session"},
            )

        self.assertEqual(missing.status_code, 401)
        rejected = RejectedOutcomeResponse.model_validate(missing.json())
        self.assertEqual(rejected.error.code, "AUTH_SESSION_REQUIRED")
        self.assertEqual(bearer.status_code, 503)
        unavailable = UnavailableOutcomeResponse.model_validate(bearer.json())
        self.assertEqual(
            unavailable.error.code,
            "DEPENDENCY_SESSION_VERIFIER_UNAVAILABLE",
        )

    def test_wrong_host_and_oversized_request_are_rejected(self) -> None:
        with TestClient(
            self._app(),
            base_url=f"http://{AUTHORITY}",
        ) as client:
            wrong_host = client.get("/health/live", headers={"Host": "localhost"})
            oversized = client.get(
                "/health/live",
                headers={"Content-Length": "1025"},
            )

        self.assertEqual(wrong_host.status_code, 421)
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(wrong_host.content, b"")
        self.assertEqual(wrong_host.headers["x-frame-options"], "DENY")

    def test_static_store_rejects_traversal(self) -> None:
        self.assertIsNone(self.assets.get("../manifest.json"))
        self.assertIsNone(self.assets.get(r"assets\app.js"))
        self.assertIsNone(self.assets.get(""))

    def test_readiness_provider_is_never_implicitly_ready(self) -> None:
        self.assertEqual(
            self.lifecycle.snapshot().readiness,
            Readiness.NOT_READY,
        )


if __name__ == "__main__":
    unittest.main()
