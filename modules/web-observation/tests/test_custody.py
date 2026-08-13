from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

from armi_kernel.application import (
    RuntimeFence,
    RuntimeInstanceId,
)
from armi_kernel.config_yaml import load_yaml_mapping
from armi_kernel.contracts import IdempotencyKey, SubjectId, TraceId
from armi_web_observation._custody import (
    build_request_bytes,
    load_custody_policy,
    normalize_full_response,
    parse_request_bytes,
)
from armi_web_observation.api import (
    WebObservationDraft,
    WebObservationRequestId,
    WebObservationToolAction,
    WebObservationViolation,
)


class WebObservationCustodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.subject_id = uuid7()
        self.fence = RuntimeFence(
            RuntimeInstanceId(uuid7()),
            self.subject_id,
            uuid7(),
            uuid7(),
            1,
        )

    def test_draft_and_request_are_strict_and_deterministic(self) -> None:
        request_id = WebObservationRequestId(uuid7())
        draft = WebObservationDraft(
            request_id,
            SubjectId(self.subject_id),
            self.fence,
            IdempotencyKey("research-1"),
            "公开资料检索".encode(),
            TraceId("1" * 32),
        )
        raw = build_request_bytes(
            request_id=str(draft.request_id.value),
            subject_id=str(draft.subject_id.value),
            runtime_instance_id=str(self.fence.runtime_instance_id.value),
            fence_token=self.fence.fence_token,
            idempotency_key=draft.idempotency_key.value,
            query=draft.query_bytes.decode(),
        )
        self.assertEqual(parse_request_bytes(raw)["query"], "公开资料检索")
        self.assertEqual(
            raw,
            build_request_bytes(
                request_id=str(draft.request_id.value),
                subject_id=str(draft.subject_id.value),
                runtime_instance_id=str(self.fence.runtime_instance_id.value),
                fence_token=self.fence.fence_token,
                idempotency_key=draft.idempotency_key.value,
                query=draft.query_bytes.decode(),
            ),
        )

    def test_query_and_manifest_boundaries_reject_drift(self) -> None:
        with self.assertRaises(WebObservationViolation) as context:
            WebObservationDraft(
                WebObservationRequestId(uuid7()),
                SubjectId(self.subject_id),
                self.fence,
                IdempotencyKey("research-2"),
                b" \t\n",
                TraceId("2" * 32),
            )
        self.assertEqual(context.exception.code, "WEB-QUERY")
        manifest = Path("configs/web-search.yaml").read_bytes()
        self.assertEqual(
            load_custody_policy(manifest).binding_id,
            "armi.model-tool.volcengine-ark-web-search-v1",
        )
        changed = cast(dict[str, Any], load_yaml_mapping(manifest))
        changed["tool_actions"].append("submit")
        with self.assertRaises(WebObservationViolation):
            load_custody_policy(json.dumps(changed).encode())

    def test_full_result_preserves_actions_text_citations_and_usage(self) -> None:
        raw = {
            "id": "resp_test",
            "model": "doubao-seed-evolving",
            "status": "completed",
            "store": False,
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "PostgreSQL 18",
                        "queries": ["PostgreSQL 18", "official documentation"],
                        "sources": [
                            {
                                "type": "url",
                                "url": "https://www.postgresql.org/docs/18/",
                            }
                        ],
                    },
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "公开资料摘要",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.postgresql.org/docs/18/",
                                    "title": "PostgreSQL 18 Documentation",
                                }
                            ],
                        }
                    ],
                },
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "tool_usage": {"web_search": 1},
            },
        }
        canonical, actions, usage, model = normalize_full_response(raw)
        self.assertEqual(actions, (WebObservationToolAction.SEARCH,))
        self.assertEqual(usage.web_search_calls, 1)
        self.assertEqual(usage.citation_count, 1)
        self.assertEqual(model, "doubao-seed-evolving")
        decoded = json.loads(canonical)
        self.assertNotIn("provider_request_digest", decoded)
        self.assertEqual(decoded["messages"][0]["parts"][0]["text"], "公开资料摘要")
        without_provider_id = dict(raw)
        without_provider_id.pop("id")
        self.assertEqual(normalize_full_response(without_provider_id)[0], canonical)

    def test_unknown_tools_hidden_reasoning_and_missing_citations_fail(self) -> None:
        base = {
            "id": "resp_test",
            "model": "doubao-seed-evolving",
            "status": "completed",
            "store": False,
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {"type": "submit", "value": "forbidden"},
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "x", "annotations": []}
                    ],
                },
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "tool_usage": {"web_search": 1},
            },
        }
        for mutation in (
            base,
            {**base, "reasoning_content": "do not retain"},
        ):
            with self.assertRaises(WebObservationViolation):
                normalize_full_response(mutation)


if __name__ == "__main__":
    unittest.main()
