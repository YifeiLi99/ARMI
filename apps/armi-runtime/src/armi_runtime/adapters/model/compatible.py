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
        return output

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
            + "格式检查只在内部进行；任何层级都不得添加 Schema 未定义的字段，"
            + "包括说明、注释、格式检查记录或推理过程。"
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
            # Provider-specific chat sampling; keep Qwen's default top_p. DESIGN.md.
            parameters["temperature"] = 1.0
        elif binding.provider == "deepseek":
            parameters["text"] = {"format": {"type": "json_object"}}
            # Chat variation is intentional; never replace strict validation with
            # lower temperature. DeepSeek fixes non-thinking top_p at 1.0.
            parameters["temperature"] = 1.0
            parameters["top_p"] = 1.0
        else:
            raise ModelViolation("MODEL-BINDING")
        example = _dialogue_example(set(properties), self.context_refs(request))
        if example is not None:
            # Both providers generate this same contract without a proven strict
            # decoder. Show nesting explicitly; never repair returned JSON. DESIGN.md.
            parameters["instructions"] += (
                "\n\n完整对话 JSON 层级示例（只示意格式，不代表本轮应作出的判断）：\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
                + "\n注意 candidate.appraisal 是完整事件；其内部 appraisal 才是评价维度。"
                + "candidate.appraisal 内的直接字段为 gist、basis_refs、event_phase、trajectory、appraisal。"
                + "事件依据写在 candidate.appraisal.basis_refs，不得在 candidate 下再复制一份 basis_refs。"
                + "\ncandidate 的直接字段只能是："
                + "、".join(sorted(properties))
                + "。嵌套字段不得提到 candidate 层；输出前检查每个字段所属对象。"
                + "是否形成评价、经历或变化由本轮判断；不要照搬示例判断或引用，"
                + "需要引用时选择本轮实际支持判断的 Context 条目。"
                + "\n输出使用多行 JSON、每层 2 空格缩进；每个属性独占一行，"
                + "对象的右花括号另起一行并对齐该对象所在层，不压缩成单行。"
                + "对象内每个属性必须有字段名，不直接放入无字段名的对象。"
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
                "causality": None,
                "concerns": [
                    {
                        "direction": "unchanged",
                        "significance": "peripheral",
                        "target": "relationship",
                    }
                ],
                "coping": None,
                "demand": None,
                "engagement": "not_applicable",
                "expectedness": "expected",
                "intrinsic_quality": "neutral",
                "outcome_certainty": "settled",
                "self_involvement": "limited",
                "standards": None,
            },
        }
        if available_refs
        else None,
    }
    if other_human:
        candidate["social"] = None
    else:
        candidate.update(
            experience=None, changes=[], mind_appraisals=[], concern_changes=[]
        )
    return {"candidate": candidate}
