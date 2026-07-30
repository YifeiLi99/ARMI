"""CON-OPENAPI checks for the frozen S007 steel-frame contract."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any, cast

from armi_runtime.interfaces.creator_contract import (
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
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

    def test_session_responses_are_strict_and_have_no_scene_placeholder(self) -> None:
        metadata = {
            "contract_version": "1.0",
            "environment_id": ENVIRONMENT_ID,
            "creator_party_id": "01890f47-7ac2-7cc4-98c2-9f4e3f13b9ab",
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
        self.assertNotIn("default_scene_key", current.model_dump())
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


if __name__ == "__main__":
    unittest.main()
