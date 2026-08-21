"""CON-OPENAPI checks for the current Creator contract."""

from __future__ import annotations

import json
import unittest
from typing import Any, cast

from armi_runtime.interfaces.creator_contract import (
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    CapabilityRequestItemResponse,
    CreatorLifeMaterialResponse,
    CreatorMaintenanceStatusResponse,
    CreatorMaintenanceTimelineItemResponse,
    CreatorMemoryItemResponse,
    CreatorProjectionEventResponse,
    CreatorRelationshipBoundaryRequest,
    CreatorRelationshipCurrentResponse,
    EffectResponse,
    FailedOutcomeResponse,
    LifeRecordItemResponse,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    WaitingOutcomeResponse,
)
from armi_runtime.interfaces.creator_openapi import (
    build_creator_openapi,
    create_creator_openapi_app,
)
from fastapi.routing import APIRoute
from pydantic import ValidationError

ENVIRONMENT_ID = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9aa"
INSTANT = "2026-07-29T10:00:00.000000Z"


def runtime_status() -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "environment_id": ENVIRONMENT_ID,
        "runtime_state": "starting",
        "readiness": "not_ready",
        "reason_codes": ["RUNTIME_RECOVERING"],
        "components": [
            {"component": "database", "state": "ready", "reason_codes": []},
            {
                "component": "runtime",
                "state": "degraded",
                "reason_codes": ["RUNTIME_RECOVERING"],
            },
            {"component": "creator_web", "state": "ready", "reason_codes": []},
        ],
        "observed_at": INSTANT,
    }


def rejected() -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "status": "rejected",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "occurred_at": INSTANT,
        "message": "request rejected",
        "error": {
            "category": "auth",
            "code": "AUTH_BROWSER_SESSION_REQUIRED",
        },
    }


class CreatorContractTests(unittest.TestCase):
    def test_openapi_paths_are_the_real_public_runtime_routes(self) -> None:
        app = create_creator_openapi_app()
        runtime_routes = {
            (method.lower(), route.path)
            for route in app.routes
            if isinstance(route, APIRoute) and route.include_in_schema
            for method in route.methods or set()
            if method != "HEAD"
        }
        schema = build_creator_openapi()
        schema_routes = {
            (method, path)
            for path, path_item in cast(
                dict[str, dict[str, Any]], schema["paths"]
            ).items()
            for method in path_item
        }
        self.assertEqual(runtime_routes, schema_routes)
        self.assertTrue(
            all(not path.startswith("/v1/local/") for _, path in runtime_routes)
        )
        self.assertTrue(all(not path.startswith("/ui") for _, path in runtime_routes))

    def test_openapi_has_exact_paths_operations_and_security(self) -> None:
        schema = build_creator_openapi()
        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertNotIn("servers", schema)
        paths = cast(dict[str, Any], schema["paths"])
        self.assertEqual(
            set(paths),
            {
                "/health/live",
                "/health/ready",
                "/v1/browser-sessions",
                "/v1/browser-sessions/current",
                "/v1/channels/qq/status",
                "/v1/channels/qq/start",
                "/v1/channels/qq/stop",
                "/v1/voice/status",
                "/v1/voice/start",
                "/v1/voice/stop",
                "/v1/vision/status",
                "/v1/vision/start",
                "/v1/vision/stop",
                "/v1/vision/observe",
                "/v1/vision/preview",
                "/v1/activities",
                "/v1/activities/{activity_id}/timeline",
                "/v1/life-records",
                "/v1/materials/{material_id}",
                "/v1/memories",
                "/v1/memories/{memory_id}/timeline",
                "/v1/maintenance/status",
                "/v1/maintenance/{maintenance_session_id}/timeline",
                "/v1/maintenance/{maintenance_session_id}/wake",
                "/v1/relationships/current",
                "/v1/relationships/current/boundaries",
                "/v1/relationships/{relationship_id}/timeline",
                "/v1/runtime/status",
                "/v1/operations/{result_ref}",
                "/v1/other-human-records",
                "/v1/other-human-records/{party_id}/scenes",
                "/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline",
                "/v1/prompts/creator-guidance",
                "/v1/prompts/creator-guidance/deactivation",
                "/v1/exports",
                "/v1/exports/{export_id}",
                "/v1/data-rights/orders",
                "/v1/data-rights/orders/{order_id}",
                "/v1/effects/{effect_id}",
                "/v1/effects/{effect_id}/artifacts/{artifact_kind}",
                "/v1/subject/summary",
                "/v1/capability-requests",
                "/v1/capability-requests/{capability_request_id}/decision",
                "/v1/scenes",
                "/v1/scenes/{scene_key}/close",
                "/v1/scenes/{scene_key}/events",
                "/v1/scenes/{scene_key}/codex-tasks",
                "/v1/scenes/{scene_key}/messages",
                "/v1/scenes/{scene_key}/reopen",
                "/v1/scenes/{scene_key}/timeline",
            },
        )
        self.assertEqual(
            paths["/health/live"]["get"]["operationId"],
            "getHealthLive",
        )
        self.assertEqual(
            paths["/health/ready"]["get"]["operationId"],
            "getHealthReady",
        )
        runtime = paths["/v1/runtime/status"]["get"]
        self.assertEqual(runtime["operationId"], "getRuntimeStatus")
        self.assertEqual(runtime["security"], [{"browserSessionBearer": []}])
        self.assertEqual(set(runtime["responses"]), {"200", "401", "403", "503"})
        qq_health = paths["/v1/channels/qq/status"]["get"]
        self.assertEqual(qq_health["operationId"], "getQQChannelHealth")
        self.assertEqual(qq_health["security"], [{"browserSessionBearer": []}])
        self.assertEqual(set(qq_health["responses"]), {"200", "401", "403", "503"})
        self.assertEqual(
            paths["/v1/channels/qq/start"]["post"]["operationId"],
            "startQQChannel",
        )
        self.assertEqual(
            paths["/v1/channels/qq/stop"]["post"]["operationId"],
            "stopQQChannel",
        )
        voice = paths["/v1/voice/status"]["get"]
        self.assertEqual(voice["operationId"], "getLiveVoiceStatus")
        self.assertEqual(voice["security"], [{"browserSessionBearer": []}])
        self.assertNotIn("security", paths["/v1/browser-sessions"]["post"])
        self.assertEqual(
            set(paths["/v1/browser-sessions"]["post"]["responses"]),
            {"200", "403", "503"},
        )
        self.assertNotIn("delete", paths["/v1/browser-sessions/current"])
        self.assertNotIn("security", paths["/health/live"]["get"])
        self.assertNotIn("security", paths["/health/ready"]["get"])
        prompt = paths["/v1/prompts/creator-guidance"]
        self.assertEqual(prompt["get"]["operationId"], "getCreatorPrompt")
        self.assertEqual(prompt["put"]["operationId"], "reviseCreatorPrompt")
        self.assertEqual(
            prompt["put"]["security"],
            [{"browserSessionBearer": []}],
        )
        self.assertEqual(
            set(prompt["put"]["responses"]),
            {"200", "400", "401", "403", "409", "413", "503"},
        )
        deactivation = paths["/v1/prompts/creator-guidance/deactivation"]["post"]
        self.assertEqual(
            deactivation["operationId"],
            "deactivateCreatorPrompt",
        )
        export = paths["/v1/exports"]["post"]
        self.assertEqual(export["operationId"], "createCreatorExport")
        self.assertEqual(export["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(export["responses"]),
            {"200", "201", "400", "401", "403", "409", "413", "503"},
        )
        export_query = paths["/v1/exports/{export_id}"]["get"]
        self.assertEqual(export_query["operationId"], "getCreatorExport")
        self.assertEqual(
            set(export_query["responses"]),
            {"200", "400", "401", "403", "404", "503"},
        )
        data_rights = paths["/v1/data-rights/orders"]["post"]
        self.assertEqual(data_rights["operationId"], "createDataRightsOrder")
        self.assertEqual(
            set(data_rights["responses"]),
            {"200", "201", "400", "401", "403", "409", "413", "503"},
        )
        data_rights_query = paths["/v1/data-rights/orders/{order_id}"]["get"]
        self.assertEqual(data_rights_query["operationId"], "getDataRightsOrder")
        self.assertEqual(
            set(data_rights_query["responses"]),
            {"200", "400", "401", "403", "404", "503"},
        )
        timeline = paths["/v1/scenes/{scene_key}/timeline"]["get"]
        self.assertEqual(timeline["operationId"], "getSceneTimeline")
        self.assertEqual(timeline["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(timeline["responses"]),
            {"200", "400", "401", "403", "404", "409", "503"},
        )
        scenes = paths["/v1/scenes"]
        self.assertEqual(scenes["get"]["operationId"], "listCreatorScenes")
        self.assertEqual(scenes["post"]["operationId"], "createCreatorScene")
        self.assertEqual(
            set(scenes["post"]["responses"]),
            {"201", "400", "401", "403", "409", "503"},
        )
        self.assertEqual(
            paths["/v1/scenes/{scene_key}/close"]["post"]["operationId"],
            "closeCreatorScene",
        )
        self.assertEqual(
            paths["/v1/scenes/{scene_key}/reopen"]["post"]["operationId"],
            "reopenCreatorScene",
        )
        activities = paths["/v1/activities"]["get"]
        self.assertEqual(activities["operationId"], "listCreatorActivities")
        self.assertEqual(activities["security"], [{"browserSessionBearer": []}])
        self.assertEqual(set(activities["responses"]), {"200", "401", "403", "503"})
        activity_timeline = paths["/v1/activities/{activity_id}/timeline"]["get"]
        self.assertEqual(activity_timeline["operationId"], "getCreatorActivityTimeline")
        self.assertEqual(activity_timeline["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(activity_timeline["responses"]),
            {"200", "400", "401", "403", "404", "503"},
        )
        relationship = paths["/v1/relationships/current"]["get"]
        self.assertEqual(
            relationship["operationId"],
            "getCreatorRelationshipCurrent",
        )
        self.assertEqual(
            relationship["security"],
            [{"browserSessionBearer": []}],
        )
        relationship_timeline = paths["/v1/relationships/{relationship_id}/timeline"][
            "get"
        ]
        self.assertEqual(
            relationship_timeline["operationId"],
            "getCreatorRelationshipTimeline",
        )
        boundary = paths["/v1/relationships/current/boundaries"]["post"]
        self.assertEqual(
            boundary["operationId"],
            "expressCreatorRelationshipBoundary",
        )
        self.assertEqual(
            set(boundary["responses"]),
            {"202", "400", "401", "403", "409", "413", "503"},
        )
        life_records = paths["/v1/life-records"]["get"]
        self.assertEqual(life_records["operationId"], "queryCreatorLifeRecords")
        self.assertEqual(life_records["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(life_records["responses"]),
            {"200", "400", "401", "403", "409", "503"},
        )
        material = paths["/v1/materials/{material_id}"]["get"]
        self.assertEqual(material["operationId"], "getCreatorLifeMaterial")
        self.assertEqual(material["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(material["responses"]),
            {"200", "400", "401", "403", "404", "503"},
        )
        memories = paths["/v1/memories"]["get"]
        self.assertEqual(memories["operationId"], "listCreatorMemories")
        memory_timeline = paths["/v1/memories/{memory_id}/timeline"]["get"]
        self.assertEqual(
            memory_timeline["operationId"],
            "getCreatorMemoryTimeline",
        )
        maintenance = paths["/v1/maintenance/status"]["get"]
        self.assertEqual(maintenance["operationId"], "getCreatorMaintenanceStatus")
        self.assertEqual(maintenance["security"], [{"browserSessionBearer": []}])
        self.assertEqual(set(maintenance["responses"]), {"200", "401", "403", "503"})
        maintenance_timeline = paths[
            "/v1/maintenance/{maintenance_session_id}/timeline"
        ]["get"]
        self.assertEqual(
            maintenance_timeline["operationId"],
            "getCreatorMaintenanceTimeline",
        )
        self.assertEqual(
            set(maintenance_timeline["responses"]),
            {"200", "400", "401", "403", "404", "503"},
        )
        wake = paths["/v1/maintenance/{maintenance_session_id}/wake"]["post"]
        self.assertEqual(wake["operationId"], "requestCreatorEmergencyWake")
        self.assertEqual(
            set(wake["responses"]), {"204", "401", "403", "404", "409", "503"}
        )
        events = paths["/v1/scenes/{scene_key}/events"]["get"]
        self.assertEqual(events["operationId"], "streamSceneEvents")
        self.assertEqual(events["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(events["responses"]),
            {"200", "400", "401", "403", "404", "409", "429", "503"},
        )
        event_content = events["responses"]["200"]["content"]["text/event-stream"]
        self.assertEqual(
            event_content["schema"]["x-event-data-schema"]["$ref"],
            "#/components/schemas/CreatorProjectionEventResponse",
        )
        messages = paths["/v1/scenes/{scene_key}/messages"]["post"]
        self.assertEqual(messages["operationId"], "acceptCreatorMessage")
        self.assertEqual(messages["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(messages["responses"]),
            {"202", "400", "401", "403", "404", "409", "413", "503"},
        )
        operation = paths["/v1/operations/{result_ref}"]["get"]
        self.assertEqual(operation["operationId"], "getCreatorOperation")
        self.assertEqual(operation["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            paths["/v1/other-human-records"]["get"]["operationId"],
            "listOtherHumanRecordParties",
        )
        self.assertEqual(
            paths["/v1/other-human-records/{party_id}/scenes"]["get"]["operationId"],
            "listOtherHumanRecordScenes",
        )
        self.assertEqual(
            paths["/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline"][
                "get"
            ]["operationId"],
            "getOtherHumanRecordTimeline",
        )
        summary = paths["/v1/subject/summary"]["get"]
        self.assertEqual(summary["operationId"], "getSubjectSummary")
        self.assertEqual(summary["security"], [{"browserSessionBearer": []}])
        operation_schema = cast(dict[str, Any], schema["components"])["schemas"][
            "OperationOutcomeResponse"
        ]
        self.assertEqual(
            {branch["$ref"].rsplit("/", 1)[-1] for branch in operation_schema["oneOf"]},
            {
                "OperationAcceptedOutcomeResponse",
                "OperationAppliedOutcomeResponse",
                "OperationCompletedOutcomeResponse",
                "OperationWaitingOutcomeResponse",
                "OperationRejectedOutcomeResponse",
                "OperationUnavailableOutcomeResponse",
                "OperationFailedOutcomeResponse",
                "OperationUnknownOutcomeResponse",
            },
        )

    def test_openapi_is_repeatable(self) -> None:
        first = json.dumps(
            build_creator_openapi(),
            sort_keys=True,
            separators=(",", ":"),
        )
        second = json.dumps(
            build_creator_openapi(),
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(first, second)

    def test_maintenance_status_separates_objective_state_from_hidden_details(
        self,
    ) -> None:
        status = CreatorMaintenanceStatusResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "creator-maintenance.v2",
                "session": {
                    "maintenance_session_id": ENVIRONMENT_ID,
                    "trigger_kind": "system_deadline",
                    "phase": "self_check",
                    "result_status": "running",
                    "revision_no": 3,
                    "head_version": 3,
                    "wake_requested": False,
                    "started_at": INSTANT,
                    "updated_at": INSTANT,
                    "finished_at": None,
                },
                "waiting_input_count": 2,
            }
        )
        assert status.session is not None
        self.assertEqual(status.session.trigger_kind, "system_deadline")
        self.assertEqual(status.waiting_input_count, 2)
        with self.assertRaises(ValidationError):
            CreatorMaintenanceStatusResponse.model_validate(
                {
                    **status.model_dump(),
                    "private_memory": "hidden",
                }
            )

    def test_maintenance_timeline_exposes_only_bounded_self_check_problem(self) -> None:
        issue = CreatorMaintenanceTimelineItemResponse.model_validate(
            {
                "revision_id": ENVIRONMENT_ID,
                "revision_no": 3,
                "phase": "self_check",
                "result_status": "running",
                "transition_kind": "advanced",
                "occurred_at": INSTANT,
                "work_outcome": "issue_found",
                "problem_summary": "有一项内部责任需要后续关注。",
            }
        )
        self.assertEqual(issue.work_outcome, "issue_found")

    def test_runtime_status_accepts_canonical_wire(self) -> None:
        model = RuntimeStatusResponse.model_validate_json(json.dumps(runtime_status()))
        self.assertEqual(model.environment_id, ENVIRONMENT_ID)
        self.assertEqual(model.runtime_state.value, "starting")
        self.assertEqual(model.readiness.value, "not_ready")

    def test_runtime_status_rejects_invalid_boundaries(self) -> None:
        invalid: list[tuple[str, object]] = [
            ("contract_version", "2.0"),
            ("environment_id", "550e8400-e29b-41d4-a716-446655440000"),
            ("runtime_state", "not_ready"),
            ("readiness", "maintenance"),
            ("observed_at", "2026-07-29T10:00:00Z"),
            ("reason_codes", ["bad-code"]),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                sample = runtime_status()
                sample[field] = value
                with self.assertRaises(ValidationError):
                    RuntimeStatusResponse.model_validate_json(json.dumps(sample))

    def test_runtime_status_rejects_unknown_fields(self) -> None:
        sample = runtime_status()
        sample["future"] = True
        with self.assertRaises(ValidationError):
            RuntimeStatusResponse.model_validate_json(json.dumps(sample))

    def test_rejected_outcome_matches_kernel_contract(self) -> None:
        model = RejectedOutcomeResponse.model_validate_json(json.dumps(rejected()))
        self.assertEqual(model.status, "rejected")
        self.assertEqual(model.error.code, "AUTH_BROWSER_SESSION_REQUIRED")

    def test_operation_waiting_and_failed_states_are_exhaustive(self) -> None:
        common = {
            "contract_version": "1.0",
            "trace_id": "0123456789abcdef0123456789abcdef",
            "occurred_at": INSTANT,
            "message": "safe operation state",
        }
        waiting = WaitingOutcomeResponse.model_validate(
            {
                **common,
                "status": "waiting",
                "result_ref": ENVIRONMENT_ID,
                "waiting_for": "context_preparation",
                "resume_condition": "context_prepared",
            }
        )
        self.assertEqual(waiting.waiting_for, "context_preparation")
        failed = FailedOutcomeResponse.model_validate(
            {
                **common,
                "status": "failed",
                "error": {
                    "category": "internal",
                    "code": "INTERNAL_CONTEXT_PREPARATION_FAILED",
                },
            }
        )
        self.assertEqual(failed.status, "failed")

    def test_session_responses_require_the_authoritative_default_scene(self) -> None:
        metadata = {
            "contract_version": "1.0",
            "environment_id": ENVIRONMENT_ID,
            "creator_party_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ab",
            "default_scene_key": "default",
            "issued_at": INSTANT,
            "expires_at": "2026-07-29T18:00:00.000000Z",
        }
        current = BrowserSessionCurrentResponse.model_validate(metadata)
        created = BrowserSessionResponse.model_validate(
            {
                **metadata,
                "browser_session_token": f"browser-v1.{'a' * 43}",
            }
        )
        self.assertEqual(current.creator_party_id, metadata["creator_party_id"])
        self.assertTrue(created.browser_session_token.startswith("browser-v1."))
        self.assertEqual(current.default_scene_key, "default")
        with self.assertRaises(ValidationError):
            BrowserSessionCurrentResponse.model_validate(
                {**metadata, "default_scene_key": None}
            )

    def test_projection_event_response_is_strict(self) -> None:
        sample = {
            "contract_version": "1.0",
            "event_id": f"sse-v1.{'a' * 22}.1",
            "event_kind": "scene.timeline.invalidated",
            "resource_kind": "scene_timeline",
            "resource_ref": "default",
            "projection_version": "scene-timeline.v6",
            "occurred_at": INSTANT,
        }
        model = CreatorProjectionEventResponse.model_validate(sample)
        self.assertEqual(model.resource_ref, "default")
        for field, value in (
            ("event_id", "sse-v1.invalid.1"),
            ("event_kind", "timeline.item"),
            ("resource_kind", "subject"),
            ("projection_version", "scene-timeline.v1"),
            ("occurred_at", "2026-07-29T10:00:00Z"),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(ValidationError),
            ):
                CreatorProjectionEventResponse.model_validate({**sample, field: value})

    def test_relationship_projection_excludes_scene_text_and_boundary_is_strict(
        self,
    ) -> None:
        current = CreatorRelationshipCurrentResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "creator-relationship.v2",
                "relationship": {
                    "relationship_id": ENVIRONMENT_ID,
                    "current_revision_id": ENVIRONMENT_ID,
                    "head_version": 1,
                    "created_at": INSTANT,
                    "current": {
                        "relationship_revision_id": ENVIRONMENT_ID,
                        "revision_no": 1,
                        "facts": [
                            {
                                "fact_id": ENVIRONMENT_ID,
                                "kind": "party_expression",
                                "summary": "Creator 表达了联系限制",
                            }
                        ],
                        "interpretation": "我会尊重这项边界",
                        "boundaries": [
                            {
                                "party_role": "other",
                                "kind": "contact",
                                "action": "restrict",
                                "summary": "不要在深夜联系",
                            }
                        ],
                        "commitments": [],
                        "open_issues": [],
                        "commitment_event": None,
                        "issue_resolution": None,
                        "status": "active",
                        "occurred_at": INSTANT,
                    },
                },
            }
        )
        assert current.relationship is not None
        self.assertEqual(current.relationship.current.boundaries[0].kind, "contact")
        projected = current.model_dump(mode="json")
        self.assertNotIn("scene_key", json.dumps(projected))
        self.assertNotIn("message", json.dumps(projected))
        with self.assertRaises(ValidationError):
            CreatorRelationshipCurrentResponse.model_validate(
                {
                    **projected,
                    "relationship": {
                        **cast(dict[str, object], projected["relationship"]),
                        "current": {
                            **cast(
                                dict[str, object],
                                cast(dict[str, object], projected["relationship"])[
                                    "current"
                                ],
                            ),
                            "scene_text": "不应进入关系投影",
                        },
                    },
                }
            )
        boundary = CreatorRelationshipBoundaryRequest.model_validate(
            {
                "contract_version": "1.0",
                "kind": "exit",
                "action": "end_contact",
                "summary": "结束联系",
            }
        )
        self.assertEqual(boundary.action, "end_contact")
        with self.assertRaises(ValidationError):
            CreatorRelationshipBoundaryRequest.model_validate(
                {
                    "contract_version": "1.0",
                    "kind": "contact",
                    "action": "end_contact",
                    "summary": "错误组合",
                }
            )
        with self.assertRaises(ValidationError):
            CreatorRelationshipBoundaryRequest.model_validate(
                {
                    "contract_version": "1.0",
                    "kind": "contact",
                    "action": "restrict",
                    "summary": "   ",
                }
            )

    def test_relationship_projection_event_is_exact(self) -> None:
        event = CreatorProjectionEventResponse.model_validate(
            {
                "contract_version": "1.0",
                "event_id": f"sse-v1.{'a' * 22}.1",
                "event_kind": "relationship.invalidated",
                "resource_kind": "relationship",
                "resource_ref": ENVIRONMENT_ID,
                "projection_version": "creator-relationship.v2",
                "occurred_at": INSTANT,
            }
        )
        self.assertEqual(event.resource_kind, "relationship")

    def test_exact_record_and_memory_projection_keep_recallability_explicit(
        self,
    ) -> None:
        record = LifeRecordItemResponse.model_validate(
            {
                "record_ref": ENVIRONMENT_ID,
                "record_kind": "memory",
                "summary": "刚从记录取得的内容",
                "source_kind": "reported",
                "occurred_at": INSTANT,
                "naturally_recallable": False,
                "retrieval_kind": "creator_view",
            }
        )
        self.assertFalse(record.naturally_recallable)
        memory = CreatorMemoryItemResponse.model_validate(
            {
                "memory_id": ENVIRONMENT_ID,
                "summary": "刚从记录取得的内容",
                "uncertainty": None,
                "source_kind": "reported",
                "source_fact_class": "external_claim",
                "accessibility": "forgotten",
                "revision_kind": "forgotten",
                "revision_no": 2,
                "head_version": 2,
                "created_at": INSTANT,
                "updated_at": INSTANT,
            }
        )
        self.assertEqual(memory.accessibility, "forgotten")

    def test_life_material_projection_exposes_only_daily_creator_fields(self) -> None:
        material = CreatorLifeMaterialResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "creator-life-material.v1",
                "material_id": ENVIRONMENT_ID,
                "material_kind": "diary",
                "revision_no": 2,
                "title": "雨天随记",
                "body": "只读正文",
                "metadata": {"mood": "quiet"},
                "material_status": "active",
                "privacy_status": "creator_visible",
                "created_at": INSTANT,
                "updated_at": INSTANT,
            }
        )
        self.assertEqual(material.body, "只读正文")
        for field in ("owner_party_id", "artifact_id", "body_digest", "source_kind"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CreatorLifeMaterialResponse.model_validate(
                    {**material.model_dump(mode="json"), field: "hidden"}
                )
        with self.assertRaises(ValidationError):
            CreatorLifeMaterialResponse.model_validate(
                {
                    **material.model_dump(mode="json"),
                    "privacy_status": "private",
                }
            )

    def test_capability_and_effect_projections_keep_the_authority_link(self) -> None:
        request_id = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ab"
        grant_id = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ac"
        request = CapabilityRequestItemResponse.model_validate(
            {
                "capability_request_id": request_id,
                "capability_kind": "creator.scene.reply",
                "operation": "send",
                "subject_id": ENVIRONMENT_ID,
                "scene_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ad",
                "purpose": "respond_to_creator",
                "audience_scope": "creator",
                "data_scope": "creator_visible_response",
                "valid_for_seconds": 600,
                "max_uses": 2,
                "max_payload_bytes": 4096,
                "status": "limited",
                "capability_availability": "available",
                "request_version": 2,
                "created_at": INSTANT,
                "status_changed_at": INSTANT,
                "effective_grant": {
                    "scope_kind": "creator_scene_reply",
                    "grant_ref": grant_id,
                    "status": "active",
                    "valid_from": INSTANT,
                    "valid_until": "2026-07-29T10:10:00.000000Z",
                    "max_uses": 1,
                    "consumed_uses": 0,
                    "remaining_uses": 1,
                    "max_payload_bytes": 2048,
                },
            }
        )
        assert request.effective_grant is not None
        self.assertEqual(request.effective_grant.grant_ref, grant_id)
        effect = EffectResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "creator-effect.v3",
                "effect_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ae",
                "action_intent_ref": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9af",
                "action_intent_revision_ref": request_id,
                "policy_decision_ref": grant_id,
                "capability_kind": "creator.scene.reply",
                "effect_kind": "creator_response",
                "status": "registered",
                "verification_status": "not_started",
                "registered_at": INSTANT,
                "attempt_count": 0,
            }
        )
        self.assertEqual(effect.action_intent_revision_ref, request_id)

    def test_timeline_v5_exposes_creator_text_and_public_refs(self) -> None:
        operation_ref = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ad"
        item = {
            "timeline_item_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ab",
            "source_kind": "creator_input",
            "source_ref": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ac",
            "status": "accepted",
            "occurred_at": INSTANT,
            "operation_ref": operation_ref,
            "message": "Creator 原始输入",
        }
        parsed = SceneTimelineItemResponse.model_validate(item)
        self.assertEqual(parsed.operation_ref, operation_ref)
        self.assertEqual(parsed.message, "Creator 原始输入")
        page = SceneTimelinePageResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "scene-timeline.v6",
                "scene_key": "default",
                "items": [item],
            }
        )
        self.assertEqual(page.items[0].operation_ref, operation_ref)
        effect_ref = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ae"
        response = SceneTimelineItemResponse.model_validate(
            {
                "timeline_item_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9af",
                "source_kind": "creator_response",
                "source_ref": effect_ref,
                "status": "completed",
                "occurred_at": INSTANT,
                "effect_ref": effect_ref,
            }
        )
        self.assertEqual(response.effect_ref, effect_ref)
        with self.assertRaises(ValidationError):
            SceneTimelinePageResponse.model_validate(
                {
                    "contract_version": "1.0",
                    "projection_version": "scene-timeline.v1",
                    "scene_key": "default",
                    "items": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
