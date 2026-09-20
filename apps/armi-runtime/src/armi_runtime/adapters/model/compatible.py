"""Responses transports with provider-specific JSON generation and one contract."""

# ruff: noqa: RUF001 -- Chinese model instructions intentionally use Chinese punctuation.

from __future__ import annotations

import json
from typing import Any, cast

from armi_cognition.api import (
    dialogue_output_instructions,
    dialogue_output_kind,
    dialogue_output_schema,
    flatten_dialogue_output,
)
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

    # JSON-mode generation needs no all-required strict-provider expansion.
    # Preserve the backend's optional fields; see DESIGN.md.
    _require_all_output_fields = False

    def output_format(self, request: ModelRequest) -> dict[str, Any]:
        output = super().output_format(request)
        if set(self._candidate_schema.get("properties", {})) == {
            "decision",
            "appraisal",
            "social",
        }:
            # A narrower generation view, not a second backend contract. Requiring
            # an interpretation works for both new and existing relationships.
            # Keep every fact/boundary/commitment capability; DESIGN.md.
            _require_relationship_interpretation(output["schema"])
        output["schema"] = dialogue_output_schema(output["schema"])
        return output

    def request_parameters(
        self, binding: ModelBinding, request: ModelRequest
    ) -> dict[str, Any]:
        schema = self.output_format(request)["schema"]
        inputs = self.render_input(request)
        # DESIGN.md: generation controls differ; the backend contract never does.
        # Do not mistake a successful HTTP response for validated candidate data.
        dialogue = dialogue_output_kind(
            set(self._candidate_schema.get("properties", {}))
        )
        business_instructions = self._instructions
        if dialogue is not None:
            business_instructions = dialogue_output_instructions(business_instructions)
            business_instructions = business_instructions.replace(
                "候选放在 candidate 属性中。", "字段直接放在根对象。"
            ).replace("decision.kind", "action")
        instructions = (
            business_instructions
            + "\n\n输出必须是单个完整 JSON 对象，不含 Markdown 代码围栏、解释或额外对象。"
            + "格式检查只在内部进行；任何层级都不得添加 Schema 未定义的字段，"
            + "包括说明、注释、格式检查记录或推理过程。"
            + "只输出本轮需要的字段；required 之外且无变化的字段直接省略。"
            + "可选状态存在实际变化时才填写，不为填字段编造内容。"
            + "以下是从后端合同生成的完整 JSON Schema，必须满足全部字段、类型和约束：\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        properties = self._candidate_schema.get("properties", {})
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
            # Provider-specific chat sampling; keep Qwen's default top_p. DESIGN.md.
            parameters["temperature"] = 1.0
        elif binding.provider == "deepseek":
            parameters["text"] = {"format": {"type": "json_object"}}
            # Responses carries a candidate message, not a tool invocation. DESIGN.md.
            parameters["tool_choice"] = "none"
            # Chat variation is intentional; never replace strict validation with
            # lower temperature. DeepSeek fixes non-thinking top_p at 1.0.
            parameters["temperature"] = 1.3
            parameters["top_p"] = 1.0
        else:
            raise ModelViolation("MODEL-BINDING")
        example = _dialogue_example(set(properties), self.context_refs(request))
        if example is not None:
            # Both providers generate this same contract without a proven strict
            # decoder. Show nesting explicitly; never repair returned JSON. DESIGN.md.
            parameters["instructions"] += (
                "\n\n完整对话 JSON 层级示例（只示意格式，不代表本轮应作出的判断）：\n"
                + json.dumps(
                    flatten_dialogue_output(example["candidate"]),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n根对象的字段只能是："
                + "、".join(sorted(schema["properties"]))
                + "。事件评价全部使用根对象的 event_ 前缀字段，不创建 event_appraisal 对象。"
                + "event_self_compatibility 是兼容性字符串；仅冲突分支填写 event_self_scope。"
                + "没有事件评价时省略全部 event_ 字段；填写时必须包含事件描述、依据、阶段、轨迹及必需评价维度。"
                + "是否形成评价、经历或变化由本轮判断；不要照搬示例判断或引用，"
                + "需要引用时选择本轮实际支持判断的 Context 条目。"
                + '\n没有评价、经历或状态变化的普通回复只需：{"action":"reply","content":"在呢"}。'
                + "experience 是经历正文字符串；experience_uncertainty 是可选的不确定性说明。"
                + "不输出 candidate、decision、social 或 relationship_change 包装对象；不确定字段位置时以 Schema 为准。"
            )
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


def _require_relationship_interpretation(schema: dict[str, Any]) -> None:
    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            return schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
        return node

    def alternatives(node: dict[str, Any]) -> list[dict[str, Any]]:
        node = resolve(node)
        if "anyOf" in node:
            return [leaf for child in node["anyOf"] for leaf in alternatives(child)]
        return [node]

    candidate = resolve(schema["properties"]["candidate"])
    social = next(
        node
        for node in alternatives(candidate["properties"]["social"])
        if node.get("type") == "object"
    )
    relationship = social["properties"]["relationship_change"]
    interpreted = [
        node
        for node in alternatives(relationship)
        if node.get("type") == "object"
        and resolve(node["properties"]["interpretation"]).get("type") == "string"
    ]
    if len(interpreted) != 1:
        raise ModelViolation("MODEL-BINDING")
    social["properties"]["relationship_change"] = {
        "anyOf": [interpreted[0], {"type": "null"}]
    }


def _dialogue_example(
    properties: set[str], available_refs: tuple[str, ...]
) -> dict[str, Any] | None:
    other_human = properties == {"decision", "appraisal", "social"}
    creator = properties == {
        "decision",
        "appraisal",
        "experience",
        "changes",
        "mind_appraisals",
        "concern_changes",
    }
    if not (creator or other_human):
        return None
    candidate: dict[str, Any] = {
        "decision": {"kind": "reply", "content": "示例回复"},
        "appraisal": {
            "gist": "一次普通交谈",
            "basis_refs": list(available_refs[:1]),
            "event_phase": "realized",
            "trajectory": {"transition": "new"},
            "appraisal": {
                "concerns": [
                    {
                        "direction": "unchanged",
                        "significance": "peripheral",
                        "target": "relationship",
                    }
                ],
                "engagement": "not_applicable",
                "expectedness": "expected",
                "intrinsic_quality": "neutral",
                "outcome_certainty": "settled",
                "self_involvement": "limited",
            },
        }
        if available_refs
        else None,
    }
    if other_human:
        # One complete example demonstrates a preference without a contact ban.
        # Do not multiply partial response shapes; see DESIGN.md.
        candidate["social"] = {
            "experience": {
                "first_person_gist": "对方希望我听完倾诉再提建议。",
            },
            "relationship_change": {
                "interpretation": "对方愿意继续交流，希望先被倾听。",
                "fact": {
                    "kind": "party_expression",
                    "summary": "对方表示先别给建议。",
                },
            },
        }
    return {"candidate": candidate}
