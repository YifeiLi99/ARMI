from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid7

from armi_kernel.application import (
    ActivityStatus,
    ActivityTransition,
    CapabilityRequestStatus,
    CodexModel,
    CreatorActivityItem,
    CreatorActivityPage,
    CreatorActivityTimeline,
    CreatorActivityTimelineItem,
    CreatorActivityViolation,
    CreatorCodexTaskCommand,
    CreatorGrantCommand,
    CreatorGrantResult,
    CreatorInputAcceptance,
    CreatorInputCommand,
    CreatorInteractionId,
    CreatorMaintenanceSession,
    CreatorMaintenanceStatus,
    CreatorMaintenanceTimeline,
    CreatorMaintenanceTimelineItem,
    CreatorMaintenanceViolation,
    CreatorMemoryItem,
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    CreatorMemoryTimelineItem,
    CreatorOperation,
    CreatorOperationPhase,
    EffectArtifactKind,
    EvidenceId,
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceTriggerKind,
    OpportunityId,
    SceneTimelinePage,
    SceneTimelineQuery,
)
from armi_kernel.application.life_records import (
    MemoryAccessibility as QueryMemoryAccessibility,
)
from armi_kernel.application.life_records import (
    MemoryRevisionKind as QueryMemoryRevisionKind,
)
from armi_kernel.contracts import Digest, Instant
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


class _CreatorActivityQuery:
    def __init__(self) -> None:
        self.activity_id = uuid7()
        self.created_at = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)

    async def list_current(self) -> CreatorActivityPage:
        return CreatorActivityPage(
            (
                CreatorActivityItem(
                    activity_id=self.activity_id,
                    activity_kind="self_directed",
                    status=ActivityStatus.READY,
                    goal="整理今天想继续探索的事情",
                    progress_summary=None,
                    waiting_kind=None,
                    waiting_summary=None,
                    resume_not_before=None,
                    terminal_reason=None,
                    revision_no=1,
                    head_version=1,
                    transition_kind=ActivityTransition.CREATED,
                    is_focused=False,
                    created_at=self.created_at,
                    updated_at=self.created_at,
                ),
            ),
            False,
        )

    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline:
        if activity_id != self.activity_id:
            raise CreatorActivityViolation("ACTIVITY-QUERY-NOT-FOUND")
        return CreatorActivityTimeline(
            activity_id,
            (
                CreatorActivityTimelineItem(
                    event_id=uuid7(),
                    event_kind="created",
                    resulting_status=ActivityStatus.READY,
                    summary=None,
                    review_not_before=None,
                    occurred_at=self.created_at,
                ),
            ),
            False,
        )


class _CreatorMaintenanceQuery:
    def __init__(self) -> None:
        self.session_id = uuid7()
        self.revision_id = uuid7()
        self.occurred_at = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
        self.wake_requested = False

    async def status(self) -> CreatorMaintenanceStatus:
        return CreatorMaintenanceStatus(
            CreatorMaintenanceSession(
                session_id=self.session_id,
                trigger_kind=MaintenanceTriggerKind.SYSTEM_DEADLINE,
                phase=MaintenancePhase.SELF_CHECK,
                result_status=MaintenanceResultStatus.RUNNING,
                revision_no=3,
                head_version=3,
                wake_requested=self.wake_requested,
                started_at=self.occurred_at,
                updated_at=self.occurred_at,
                finished_at=None,
            ),
            2,
        )

    async def timeline(self, session_id: UUID) -> CreatorMaintenanceTimeline:
        if session_id != self.session_id:
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-NOT-FOUND")
        return CreatorMaintenanceTimeline(
            session_id,
            (
                CreatorMaintenanceTimelineItem(
                    revision_id=self.revision_id,
                    revision_no=3,
                    phase=MaintenancePhase.SELF_CHECK,
                    result_status=MaintenanceResultStatus.RUNNING,
                    transition_kind="advanced",
                    occurred_at=self.occurred_at,
                ),
            ),
            False,
        )


class _LifeRecordQuery:
    def __init__(self) -> None:
        self.memory_id = uuid7()
        self.revision_id = uuid7()
        self.occurred_at = datetime(2026, 8, 4, 10, 30, tzinfo=UTC)
        self.requests: list[LifeRecordQuery] = []

    async def query(self, request: LifeRecordQuery) -> LifeRecordPage:
        self.requests.append(request)
        return LifeRecordPage(
            (
                LifeRecordItem(
                    record_ref=self.memory_id,
                    record_kind=LifeRecordKind.MEMORY,
                    summary="刚从记录查到的旧理解",
                    source_kind="reported",
                    occurred_at=Instant(self.occurred_at),
                    naturally_recallable=False,
                    retrieval_kind=request.retrieval_kind,
                ),
            )
        )

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor=None,
    ) -> CreatorMemoryPage:
        del limit, query_text, cursor
        return CreatorMemoryPage(
            (
                CreatorMemoryItem(
                    memory_id=self.memory_id,
                    summary="刚从记录查到的旧理解",
                    uncertainty="来源是转述",
                    source_kind="reported",
                    source_fact_class="external_claim",
                    accessibility=QueryMemoryAccessibility.FORGOTTEN,
                    revision_kind=QueryMemoryRevisionKind.FORGOTTEN,
                    revision_no=2,
                    head_version=2,
                    created_at=Instant(self.occurred_at),
                    updated_at=Instant(self.occurred_at),
                ),
            )
        )

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor=None,
    ) -> CreatorMemoryTimeline:
        del limit, cursor
        if memory_id != self.memory_id:
            raise LifeRecordQueryViolation("LIFE-QUERY-NOT-FOUND")
        return CreatorMemoryTimeline(
            memory_id,
            (
                CreatorMemoryTimelineItem(
                    revision_id=self.revision_id,
                    revision_no=2,
                    revision_kind=QueryMemoryRevisionKind.FORGOTTEN,
                    accessibility=QueryMemoryAccessibility.FORGOTTEN,
                    summary="刚从记录查到的旧理解",
                    uncertainty="来源是转述",
                    source_kind="reported",
                    source_fact_class="external_claim",
                    relation_kind=None,
                    related_memory_id=None,
                    occurred_at=Instant(self.occurred_at),
                ),
            ),
        )


class _EmergencyWake:
    def __init__(self, query: _CreatorMaintenanceQuery) -> None:
        self.query = query
        self.requests: list[tuple[UUID, UUID]] = []

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        if session_id != self.query.session_id:
            raise AssertionError("unexpected maintenance session")
        self.requests.append((session_id, request_id))
        self.query.wake_requested = True
        return session_id

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
        self.activity_query = _CreatorActivityQuery()
        self.life_record_query = _LifeRecordQuery()
        self.maintenance_query = _CreatorMaintenanceQuery()
        self.emergency_wake = _EmergencyWake(self.maintenance_query)

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
            creator_activity_query=self.activity_query,
            life_record_query=self.life_record_query,
            creator_memory_query=self.life_record_query,
            creator_maintenance_query=self.maintenance_query,
            creator_emergency_wake=self.emergency_wake,
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

    def test_activity_overview_and_timeline_are_read_only_and_session_bound(
        self,
    ) -> None:
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
            activities = client.get(
                "/v1/activities",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/activities/{self.activity_query.activity_id}/timeline",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/activities/{uuid7()}/timeline",
                headers=self._browser_headers(token),
            )
            unauthenticated = client.get(
                "/v1/activities",
                headers=self._browser_headers(),
            )

        self.assertEqual(activities.status_code, 200)
        self.assertEqual(activities.json()["projection_version"], "creator-activity.v1")
        self.assertEqual(activities.json()["items"][0]["status"], "ready")
        self.assertNotIn("resumption_cue", activities.text)
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["event_kind"], "created")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unauthenticated.status_code, 401)

    def test_exact_life_query_and_memory_history_do_not_masquerade_as_recall(
        self,
    ) -> None:
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
            records = client.get(
                "/v1/life-records?kind=memory&q=%E6%97%A7%E7%90%86%E8%A7%A3&limit=20",
                headers=self._browser_headers(token),
            )
            memories = client.get(
                "/v1/memories?limit=20",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/memories/{self.life_record_query.memory_id}/timeline?limit=20",
                headers=self._browser_headers(token),
            )
            invalid = client.get(
                "/v1/life-records?kind=secret",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/memories/{uuid7()}/timeline?limit=20",
                headers=self._browser_headers(token),
            )

        self.assertEqual(records.status_code, 200)
        self.assertEqual(records.json()["retrieval_kind"], "creator_view")
        self.assertFalse(records.json()["items"][0]["naturally_recallable"])
        request = self.life_record_query.requests[0]
        self.assertIs(request.actor, LifeRecordActor.CREATOR)
        self.assertIs(request.record_kind, LifeRecordKind.MEMORY)
        self.assertEqual(request.query_text, "旧理解")
        self.assertEqual(memories.json()["items"][0]["accessibility"], "forgotten")
        self.assertEqual(timeline.json()["items"][0]["revision_kind"], "forgotten")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_maintenance_status_timeline_and_wake_are_session_bound(self) -> None:
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
            status = client.get(
                "/v1/maintenance/status",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/maintenance/{self.maintenance_query.session_id}/timeline",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/maintenance/{uuid7()}/timeline",
                headers=self._browser_headers(token),
            )
            wake = client.post(
                f"/v1/maintenance/{self.maintenance_query.session_id}/wake",
                headers=self._browser_headers(token),
            )
            unauthenticated = client.get(
                "/v1/maintenance/status",
                headers=self._browser_headers(),
            )

        self.assertEqual(status.status_code, 200)
        self.assertEqual(
            status.json()["session"]["trigger_kind"],
            "system_deadline",
        )
        self.assertEqual(status.json()["waiting_input_count"], 2)
        self.assertNotIn("memory", status.text)
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["phase"], "self_check")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(wake.status_code, 204)
        self.assertEqual(len(self.emergency_wake.requests), 1)
        self.assertEqual(self.emergency_wake.requests[0][0], self.maintenance_query.session_id)
        self.assertEqual(self.emergency_wake.requests[0][1].version, 7)
        self.assertEqual(unauthenticated.status_code, 401)

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
