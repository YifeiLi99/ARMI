"""CON-OPENAPI checks for the frozen S007 steel-frame contract."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, cast

from armi_runtime.interfaces.creator_contract import (
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    CreatorProjectionEventResponse,
    FailedOutcomeResponse,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    WaitingOutcomeResponse,
    build_creator_openapi,
)
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
                "/v1/browser-bootstrap-codes",
                "/v1/browser-sessions",
                "/v1/browser-sessions/current",
                "/v1/runtime/status",
                "/v1/operations/{result_ref}",
                "/v1/subject/summary",
                "/v1/capability-requests",
                "/v1/capability-requests/{capability_request_id}/decision",
                "/v1/scenes/{scene_key}/events",
                "/v1/scenes/{scene_key}/messages",
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
        self.assertEqual(
            paths["/v1/browser-bootstrap-codes"]["post"]["security"],
            [{"creatorBearer": []}],
        )
        self.assertNotIn("security", paths["/v1/browser-sessions"]["post"])
        self.assertNotIn("security", paths["/health/live"]["get"])
        self.assertNotIn("security", paths["/health/ready"]["get"])
        timeline = paths["/v1/scenes/{scene_key}/timeline"]["get"]
        self.assertEqual(timeline["operationId"], "getSceneTimeline")
        self.assertEqual(timeline["security"], [{"browserSessionBearer": []}])
        self.assertEqual(
            set(timeline["responses"]),
            {"200", "400", "401", "403", "404", "409", "503"},
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
        summary = paths["/v1/subject/summary"]["get"]
        self.assertEqual(summary["operationId"], "getSubjectSummary")
        self.assertEqual(summary["security"], [{"browserSessionBearer": []}])
        operation_schema = cast(dict[str, Any], schema["components"])["schemas"][
            "OperationOutcomeResponse"
        ]
        self.assertEqual(
            {branch["$ref"].rsplit("/", 1)[-1] for branch in operation_schema["oneOf"]},
            {
                "AcceptedOutcomeResponse",
                "AppliedOutcomeResponse",
                "CompletedOutcomeResponse",
                "WaitingOutcomeResponse",
                "RejectedOutcomeResponse",
                "FailedOutcomeResponse",
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
            ("reason_codes", ["RUNTIME_RECOVERING", "RUNTIME_RECOVERING"]),
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
                "retryable": False,
            }
        )
        self.assertFalse(failed.retryable)
        with self.assertRaises(ValidationError):
            WaitingOutcomeResponse.model_validate(
                {
                    **common,
                    "status": "waiting",
                    "result_ref": ENVIRONMENT_ID,
                    "waiting_for": "context_preparation",
                    "resume_condition": "model_step_available",
                }
            )

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

    def test_error_category_prefix_mismatch_is_rejected(self) -> None:
        sample = copy.deepcopy(rejected())
        error = sample["error"]
        assert isinstance(error, dict)
        error["code"] = "CONFLICT_SUBJECT_VERSION"
        with self.assertRaises(ValidationError):
            RejectedOutcomeResponse.model_validate_json(json.dumps(sample))

    def test_projection_event_response_is_strict(self) -> None:
        sample = {
            "contract_version": "1.0",
            "event_id": f"sse-v1.{'a' * 22}.1",
            "event_kind": "scene.timeline.invalidated",
            "resource_kind": "scene_timeline",
            "resource_ref": "default",
            "projection_version": "scene-timeline.v2",
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

    def test_timeline_v2_exposes_only_creator_input_operation_refs(self) -> None:
        operation_ref = "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ad"
        item = {
            "timeline_item_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ab",
            "source_kind": "creator_input",
            "source_ref": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ac",
            "status": "accepted",
            "occurred_at": INSTANT,
            "operation_ref": operation_ref,
        }
        parsed = SceneTimelineItemResponse.model_validate(item)
        self.assertEqual(parsed.operation_ref, operation_ref)
        page = SceneTimelinePageResponse.model_validate(
            {
                "contract_version": "1.0",
                "projection_version": "scene-timeline.v2",
                "scene_key": "default",
                "items": [item],
            }
        )
        self.assertEqual(page.items[0].operation_ref, operation_ref)
        with self.assertRaises(ValidationError):
            SceneTimelineItemResponse.model_validate(
                {key: value for key, value in item.items() if key != "operation_ref"}
            )
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
