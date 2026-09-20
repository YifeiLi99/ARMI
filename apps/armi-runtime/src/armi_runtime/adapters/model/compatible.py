"""Responses transports with provider-specific JSON generation and one contract."""

# ruff: noqa: RUF001 -- Chinese model instructions intentionally use Chinese punctuation.

from __future__ import annotations

import json
from typing import Any, cast

from armi_kernel.application import (
    ModelBinding,
    ModelRequest,
    ModelViolation,
    provider_call,
)
from armi_kernel.contracts import Digest
from openai import APIStatusError

from .structured import StructuredRequestRenderer


class CompatibleStructuredTransport(StructuredRequestRenderer):
    """Reuse the exact prompt/schema renderer, never the Ark request protocol."""

    def request_parameters(
        self, binding: ModelBinding, request: ModelRequest
    ) -> dict[str, Any]:
        schema = self.output_format(request)["schema"]
        inputs = self.render_input(request)
        # DESIGN.md: generation controls differ; the backend contract never does.
        # Do not mistake a successful HTTP response for validated candidate data.
        instructions = (
            self._instructions
            + "\n\n输出必须是单个完整 JSON 对象，不含 Markdown 代码围栏、解释或额外对象。"
            + "以下是后端验证使用的完整 JSON Schema，必须满足全部字段、类型和约束：\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        properties = self._candidate_schema.get("properties", {})
        if set(properties) == {"decision", "appraisal", "social"}:
            example = {
                "candidate": {
                    "decision": {"kind": "reply", "content": "示例回复"},
                    "appraisal": None,
                    "social": None,
                }
            }
            experience_example = {
                "candidate": {
                    "decision": {"kind": "reply", "content": "示例回复"},
                    "appraisal": None,
                    "social": {
                        "experience": {
                            "first_person_gist": "这次交谈让我有了一段新的个人经历。",
                            "uncertainty": None,
                        },
                        "relationship_change": None,
                    },
                }
            }
            instructions += (
                "\n\n合法 JSON 格式示例（仅示意层级，实际内容按本轮判断）：\n"
                + json.dumps(example, ensure_ascii=False)
                + "\n注意 decision、appraisal、social 都在 candidate 对象内部。"
                + "若填写 appraisal，事件元数据与内部 appraisal 评价对象应分别遵循 Schema；"
                + "不要把它们混为同一层。示例中的 null 不要求省略本轮实际形成的评价或经历。"
                + "\n\n仅形成经历、没有关系变化的合法示例：\n"
                + json.dumps(experience_example, ensure_ascii=False)
                + "\nrelationship_change 为 null 与内部字段全为 null 的对象不同；后者非法。"
            )
        parameters: dict[str, Any] = {
            "model": binding.model_id,
            "instructions": instructions,
            "input": inputs,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": "none"},
            "tools": [],
        }
        if binding.provider == "qwen":
            # Qwen Responses documents no text.format constraint. Never send an
            # ignored parameter and claim it enforces JSON. Disable server storage.
            parameters["store"] = False
        elif binding.provider == "deepseek":
            parameters["text"] = {"format": {"type": "json_object"}}
        else:
            raise ModelViolation("MODEL-BINDING")
        return parameters

    async def tokenize(
        self, *, api_key: memoryview, binding: ModelBinding, request_bytes: bytes
    ) -> int:
        # Neither selected API exposes Ark's tokenization endpoint. Reserve a
        # conservative UTF-8 byte budget, including schema and message framing;
        # this is a local estimate, never reported as provider usage. See DESIGN.md.
        request = ModelRequest(
            request_bytes,
            Digest.from_bytes(request_bytes),
            1,
            binding.output_token_limit,
        )
        parameters = self.request_parameters(binding, request)
        return (
            len(
                json.dumps(
                    parameters, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            )
            + 1024
        )

    async def invoke(
        self, *, api_key: memoryview, binding: ModelBinding, request: ModelRequest
    ) -> dict[str, Any]:
        client = self._clients.get_compatible(api_key, binding)
        raw: Any
        response: Any
        async with provider_call(
            provider=binding.provider, model=binding.model_id, service="generation"
        ) as call:
            try:
                parameters = self.request_parameters(binding, request)
                raw = cast(
                    Any,
                    await client.responses.with_raw_response.create(**parameters),
                )
                response = raw.parse()
            except APIStatusError as error:
                await call.capture(
                    usage=None,
                    provider_request_id=error.response.headers.get("x-request-id")
                    or error.request_id,
                )
                raise
            document = cast(dict[str, Any], response.model_dump(mode="json"))
            usage: Any = document.get("usage")
            await call.capture(
                usage=cast(dict[str, object], usage)
                if isinstance(usage, dict)
                else None,
                provider_request_id=raw.headers.get("x-request-id")
                or document.get("id"),
                response_model=document.get("model"),
            )
        if not isinstance(usage, dict):
            raise ModelViolation("MODEL-PROVIDER-RESPONSE")
        usage = cast(dict[str, Any], usage)
        text = "".join(
            part["text"]
            for item in document.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        normalized_usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cached_input_tokens": cast(
                dict[str, Any], usage.get("input_tokens_details") or {}
            ).get("cached_tokens", 0),
        }
        return {
            "provider_request_id": document.get("id"),
            "model_id": document.get("model"),
            "output_text": text,
            "usage": normalized_usage,
            "raw": document,
        }
