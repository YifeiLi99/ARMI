from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid7

from armi_kernel.application import (
    CapabilityRequestStatus,
    CodexModel,
    CreatorCodexTaskCommand,
    CreatorGrantCommand,
    CreatorGrantResult,
    CreatorInputAcceptance,
    CreatorInputCommand,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    EffectArtifactKind,
    EvidenceId,
    OpportunityId,
    SceneTimelinePage,
    SceneTimelineQuery,
)
from armi_kernel.contracts import Digest
from armi_runtime.composition.lifecycle import LifecycleController
from armi_runtime.interfaces.browser_sessions import BrowserSessionStore
from armi_runtime.interfaces.creator_app import (
    _creator_visible_codex_artifact,
    create_runtime_app,
)
from armi_runtime.interfaces.creator_contract import (
    Readiness,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
)
from armi_runtime.interfaces.creator_events import CreatorEventBroker
from armi_runtime.interfaces.static_assets import StaticAsset, StaticAssetStore
from fastapi.testclient import TestClient

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
CREATOR_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234568"
AUTHORITY = "127.0.0.1:45678"
CREATOR_BEARER = f"creator-v1.{'a' * 43}"


class _SceneTimelineQuery:
    async def query(self, request: SceneTimelineQuery) -> SceneTimelinePage:
        return SceneTimelinePage(scene_key=request.scene_key, items=())


class _CreatorInput:
    def __init__(self) -> None:
        self.acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(b"message"),
            True,
        )
        self.commands: list[CreatorInputCommand] = []

    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        self.commands.append(command)
        return self.acceptance

    async def get(self, opportunity_id: OpportunityId) -> CreatorOperation:
        self.assert_opportunity(opportunity_id)
        value = self.acceptance
        return CreatorOperation(
            CreatorInputAcceptance(
                value.interaction_id,
                value.evidence_id,
                value.opportunity_id,
                value.request_digest,
                value.content_digest,
                False,
            ),
            CreatorOperationPhase.ACCEPTED,
        )

    def assert_opportunity(self, opportunity_id: OpportunityId) -> None:
        if opportunity_id != self.acceptance.opportunity_id:
            raise AssertionError("unexpected opportunity")


class _CreatorCodexTask:
    def __init__(self) -> None:
        self.acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"codex-request"),
            Digest.from_bytes(b"codex-task-manifest"),
            True,
        )
        self.commands: list[CreatorCodexTaskCommand] = []

    async def accept(self, command: CreatorCodexTaskCommand) -> CreatorInputAcceptance:
        self.commands.append(command)
        return self.acceptance


class _CapabilityPolicy:
    def __init__(self) -> None:
        self.request_id = uuid7()
        self.commands: list[CreatorGrantCommand] = []

    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        del cursor
        return {
            "items": [
                {
                    "capability_request_id": str(self.request_id),
                    "capability_kind": "creator.scene.reply",
                    "operation": "send",
                    "subject_id": ENVIRONMENT_ID,
                    "scene_id": ENVIRONMENT_ID,
                    "audience_scope": "creator",
                    "data_scope": "creator_visible_response",
                    "purpose": "respond_to_creator",
                    "workspace_scope": None,
                    "artifact_scope": None,
                    "network_access": None,
                    "valid_for_seconds": 60,
                    "max_uses": 1,
                    "max_payload_bytes": 1024,
                    "status": "pending",
                    "capability_availability": "available",
                    "request_version": 1,
                    "created_at": datetime.now(UTC),
                    "resolution_reason_code": None,
                    "effective_grant": None,
                }
            ][:limit],
            "next_cursor": None,
            "creator_party_id": str(creator_party_id),
        }

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult:
        self.commands.append(command)
        return CreatorGrantResult(
            command.request_id,
            command.expected_version + 1,
            CapabilityRequestStatus.DENIED,
            Digest.from_bytes(b"decision"),
        )


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
        self.sessions = BrowserSessionStore(
            creator_bearer=CREATOR_BEARER.encode(),
            environment_id=UUID(ENVIRONMENT_ID),
            creator_party_id=UUID(CREATOR_ID),
            bootstrap_ttl_seconds=120,
            session_ttl_seconds=28_800,
        )
        self.events = CreatorEventBroker(epoch=b"\x06" * 16)
        self.creator_input = _CreatorInput()
        self.creator_codex_task = _CreatorCodexTask()
        self.capability_policy = _CapabilityPolicy()

    def test_codex_final_result_projects_only_verified_deliverable(self) -> None:
        content, media_type = _creator_visible_codex_artifact(
            EffectArtifactKind.FINAL_RESULT,
            b'{"changed_paths":["result.md"],"deliverable":"done\\n","summary":"ok"}',
            "application/json",
        )
        self.assertEqual(content, b"done\n")
        self.assertEqual(media_type, "text/plain")

    def _status(self) -> RuntimeStatusResponse:
        snapshot = self.lifecycle.snapshot()
        return RuntimeStatusResponse(
            contract_version="1.0",
            environment_id=snapshot.environment_id,
            runtime_state=snapshot.runtime_state,
            readiness=snapshot.readiness,
            reason_codes=list(snapshot.reason_codes),
            observed_at=snapshot.observed_at,
        )

    def _app(self, *, sessions: bool = True):
        async def started() -> None:
            self.lifecycle.start()
            self.lifecycle.complete_startup(("TEST_BLOCKER",))

        async def stopping() -> None:
            self.lifecycle.drain()
            self.lifecycle.stop()

        return create_runtime_app(
            readiness=lambda: self.lifecycle.snapshot().readiness,
            runtime_status=self._status,
            assets=self.assets,
            browser_sessions=self.sessions if sessions else None,
            expected_authority=AUTHORITY,
            request_body_max_bytes=1024,
            on_started=started,
            on_stopping=stopping,
            scene_timeline_query=_SceneTimelineQuery(),
            creator_events=self.events,
            creator_input=self.creator_input,
            codex_task_admission=self.creator_codex_task,
            creator_operations=self.creator_input,
            capability_policy=self.capability_policy,
        )

    @staticmethod
    def _browser_headers(token: str | None = None) -> dict[str, str]:
        headers = {
            "Origin": f"http://{AUTHORITY}",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def test_health_and_static_surface_are_exact(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            redirect = client.get("/ui", follow_redirects=False)
            index = client.get("/ui/")
            asset = client.get("/ui/assets/app-a1.js")

            self.assertEqual(live.json(), {"status": "alive"})
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(redirect.status_code, 308)
            self.assertEqual(index.status_code, 200)
            self.assertEqual(asset.status_code, 200)
            self.assertNotIn("access-control-allow-origin", index.headers)
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)
        self.assertEqual(self.lifecycle.snapshot().runtime_state.value, "stopped")

    def test_capability_request_list_and_decision_are_session_bound(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
                content=b"",
            )
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": issued.json()["bootstrap_code"]},
            )
            token = session.json()["browser_session_token"]
            page = client.get(
                "/v1/capability-requests?limit=50",
                headers=self._browser_headers(token),
            )
            self.assertEqual(page.status_code, 200)
            self.assertEqual(len(page.json()["items"]), 1)
            decision = client.post(
                f"/v1/capability-requests/{self.capability_policy.request_id}/decision",
                headers=self._browser_headers(token),
                json={
                    "contract_version": "1.0",
                    "decision_id": str(uuid7()),
                    "expected_request_version": 1,
                    "decision": "deny",
                },
            )
            self.assertEqual(decision.status_code, 200)
            self.assertEqual(decision.json()["status"], "applied")
            self.assertEqual(decision.json()["state_version"], 2)
            self.assertEqual(len(self.capability_policy.commands), 1)
            rejected = client.post(
                f"/v1/capability-requests/{self.capability_policy.request_id}/decision",
                headers={**self._browser_headers(token), "Origin": "http://invalid"},
                json={
                    "contract_version": "1.0",
                    "decision_id": str(uuid7()),
                    "expected_request_version": 1,
                    "decision": "deny",
                },
            )
            self.assertEqual(rejected.status_code, 403)

    def test_full_issue_exchange_status_and_logout_flow(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
                content=b"",
            )
            self.assertEqual(issued.status_code, 200)
            code = issued.json()["bootstrap_code"]
            established = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": code},
            )
            self.assertEqual(established.status_code, 200)
            token = established.json()["browser_session_token"]
            self.assertEqual(established.json()["default_scene_key"], "default")

            current = client.get(
                "/v1/browser-sessions/current",
                headers=self._browser_headers(token),
            )
            status = client.get(
                "/v1/runtime/status",
                headers=self._browser_headers(token),
            )
            logged_out = client.delete(
                "/v1/browser-sessions/current",
                headers=self._browser_headers(token),
            )
            stale = client.get(
                "/v1/browser-sessions/current",
                headers=self._browser_headers(token),
            )

        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["creator_party_id"], CREATOR_ID)
        self.assertEqual(current.json()["default_scene_key"], "default")
        self.assertNotIn("browser_session_token", current.json())
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["runtime_state"], "blocked")
        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual(stale.status_code, 401)

    def test_timeline_is_authenticated_and_query_parameters_are_exact(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
                content=b"",
            )
            established = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": issued.json()["bootstrap_code"]},
            )
            token = established.json()["browser_session_token"]
            timeline = client.get(
                "/v1/scenes/default/timeline?limit=50",
                headers=self._browser_headers(token),
            )
            duplicate = client.get(
                "/v1/scenes/default/timeline?limit=50&limit=51",
                headers=self._browser_headers(token),
            )
            unrelated = client.get(
                "/v1/runtime/status?limit=50",
                headers=self._browser_headers(token),
            )

        self.assertEqual(
            timeline.json(),
            {
                "contract_version": "1.0",
                "projection_version": "scene-timeline.v3",
                "scene_key": "default",
                "items": [],
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(unrelated.status_code, 400)

    def test_creator_message_acceptance_and_operation_are_authoritative(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
            )
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": issued.json()["bootstrap_code"]},
            )
            token = session.json()["browser_session_token"]
            accepted = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-1",
                },
                json={
                    "contract_version": "1.0",
                    "message": "  exact\r\ntext  ",
                },
            )
            operation = client.get(
                accepted.json()["details"]["operation_url"],
                headers=self._browser_headers(token),
            )
            blank = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-2",
                },
                json={"contract_version": "1.0", "message": " \r\n "},
            )
            duplicate = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-3",
                    "Content-Type": "application/json",
                },
                content=b'{"contract_version":"1.0","message":"a","message":"b"}',
            )
            duplicate_idempotency = client.post(
                "/v1/scenes/default/messages",
                headers=[
                    *self._browser_headers(token).items(),
                    ("Idempotency-Key", "request-4"),
                    ("Idempotency-Key", "request-5"),
                    ("Content-Type", "application/json"),
                ],
                content=b'{"contract_version":"1.0","message":"valid"}',
            )
            wrong_content_type = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-6",
                    "Content-Type": "text/plain",
                },
                content=b'{"contract_version":"1.0","message":"valid"}',
            )
            invalid_utf8 = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-7",
                    "Content-Type": "application/json",
                },
                content=b'{"contract_version":"1.0","message":"\xff"}',
            )
            query = client.post(
                "/v1/scenes/default/messages?token=x",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-8",
                },
                json={"contract_version": "1.0", "message": "valid"},
            )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertEqual(accepted.json()["custodian"], "runtime")
        self.assertEqual(operation.status_code, 200)
        self.assertEqual(operation.json()["result_ref"], accepted.json()["result_ref"])
        self.assertEqual(self.creator_input.commands[0].message, "  exact\r\ntext  ")
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate_idempotency.status_code, 400)
        self.assertEqual(wrong_content_type.status_code, 400)
        self.assertEqual(invalid_utf8.status_code, 400)
        self.assertEqual(query.status_code, 400)

    def test_creator_codex_task_is_explicit_authenticated_intake(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
            )
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": issued.json()["bootstrap_code"]},
            )
            token = session.json()["browser_session_token"]
            accepted = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-1",
                },
                json={
                    "contract_version": "1.0",
                    "objective": "整理一份可核验的交付说明。",
                },
            )
            research = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-research-1",
                },
                json={
                    "contract_version": "1.0",
                    "objective": "查询今天的公开新闻并附来源。",
                    "model_id": "gpt-5.6-luna",
                    "reasoning_effort": "low",
                    "web_search": True,
                },
            )
            blank = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-2",
                },
                json={"contract_version": "1.0", "objective": "  \r\n"},
            )
            wrong_origin = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Origin": "http://localhost:45678",
                    "Idempotency-Key": "codex-task-3",
                },
                json={"contract_version": "1.0", "objective": "valid"},
            )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(research.status_code, 202)
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertEqual(
            self.creator_codex_task.commands[0].objective,
            "整理一份可核验的交付说明。",
        )
        self.assertIs(self.creator_codex_task.commands[1].model_id, CodexModel.LUNA)
        self.assertTrue(self.creator_codex_task.commands[1].web_search)
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(wrong_origin.status_code, 403)

    def test_replay_wrong_kind_and_boundary_requests_are_rejected(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
                content=b"",
            )
            code = issued.json()["bootstrap_code"]
            first = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": code},
            )
            replay = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": code},
            )
            wrong_origin = client.post(
                "/v1/browser-sessions",
                headers={
                    **self._browser_headers(),
                    "Origin": "http://localhost:45678",
                },
                json={"bootstrap_code": code},
            )
            wrong_kind = client.get(
                "/v1/runtime/status",
                headers=self._browser_headers(CREATOR_BEARER),
            )
            proxy = client.get(
                "/health/live",
                headers={"Forwarded": "host=127.0.0.1"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(wrong_kind.status_code, 401)
        self.assertEqual(proxy.status_code, 421)
        RejectedOutcomeResponse.model_validate(replay.json())

    def test_duplicate_json_cookie_url_and_oversize_are_rejected(self) -> None:
        headers = {
            **self._browser_headers(),
            "Content-Type": "application/json",
        }
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            duplicate = client.post(
                "/v1/browser-sessions",
                headers=headers,
                content=b'{"bootstrap_code":"x","bootstrap_code":"y"}',
            )
            cookie = client.get(
                "/v1/runtime/status",
                headers={
                    **self._browser_headers("browser-v1." + "a" * 43),
                    "Cookie": "x=y",
                },
            )
            query = client.get(
                "/v1/runtime/status?token=x",
                headers=self._browser_headers("browser-v1." + "a" * 43),
            )
            oversized = client.get("/health/live", headers={"Content-Length": "1025"})

        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(cookie.status_code, 403)
        self.assertEqual(query.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    def test_event_stream_validates_boundary_accept_and_replay_header(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            issued = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
            )
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                json={"bootstrap_code": issued.json()["bootstrap_code"]},
            )
            token = session.json()["browser_session_token"]
            base = self._browser_headers(token)
            wrong_accept = client.get(
                "/v1/scenes/default/events",
                headers=base,
            )
            query = client.get(
                "/v1/scenes/default/events?token=x",
                headers={**base, "Accept": "text/event-stream"},
            )
            malformed = client.get(
                "/v1/scenes/default/events",
                headers={
                    **base,
                    "Accept": "text/event-stream",
                    "Last-Event-ID": "invalid",
                },
            )
            stale = client.get(
                "/v1/scenes/default/events",
                headers={
                    **base,
                    "Accept": "text/event-stream",
                    "Last-Event-ID": f"sse-v1.{'A' * 22}.1",
                },
            )
            invisible = client.get(
                "/v1/scenes/other/events",
                headers={**base, "Accept": "text/event-stream"},
            )

        self.assertEqual(wrong_accept.status_code, 400)
        self.assertEqual(query.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], "INPUT_EVENT_ID_INVALID")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "CONFLICT_EVENT_GAP")
        self.assertEqual(invisible.status_code, 404)

    def test_host_fetch_origin_preflight_and_creator_route_matrix(self) -> None:
        code_body = {"bootstrap_code": f"bootstrap-v1.{'a' * 22}"}
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            host_variants = tuple(
                client.get(
                    "/health/live",
                    headers={"Host": host},
                ).status_code
                for host in (
                    "localhost:45678",
                    "127.0.0.1.:45678",
                    "[::1]:45678",
                    "127.0.0.1",
                    "127.0.0.1:80",
                )
            )
            missing_fetch = client.post(
                "/v1/browser-sessions",
                headers={
                    "Origin": f"http://{AUTHORITY}",
                    "Content-Type": "application/json",
                },
                json=code_body,
            )
            cross_site = client.post(
                "/v1/browser-sessions",
                headers={
                    **self._browser_headers(),
                    "Sec-Fetch-Site": "cross-site",
                },
                json=code_body,
            )
            preflight = client.options(
                "/v1/browser-sessions",
                headers={
                    "Origin": f"http://{AUTHORITY}",
                    "Access-Control-Request-Method": "POST",
                },
            )
            creator_from_browser = client.post(
                "/v1/browser-bootstrap-codes",
                headers={
                    "Authorization": f"Bearer {CREATOR_BEARER}",
                    **self._browser_headers(),
                },
            )

        self.assertEqual(host_variants, (421, 421, 421, 421, 421))
        self.assertEqual(missing_fetch.status_code, 403)
        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(preflight.status_code, 405)
        self.assertEqual(creator_from_browser.status_code, 403)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_missing_session_capability_is_unavailable(self) -> None:
        with TestClient(
            self._app(sessions=False),
            base_url=f"http://{AUTHORITY}",
        ) as client:
            response = client.post(
                "/v1/browser-bootstrap-codes",
                headers={"Authorization": f"Bearer {CREATOR_BEARER}"},
            )
        self.assertEqual(response.status_code, 503)

    def test_readiness_provider_is_never_implicitly_ready(self) -> None:
        self.assertEqual(self.lifecycle.snapshot().readiness, Readiness.NOT_READY)


if __name__ == "__main__":
    unittest.main()
