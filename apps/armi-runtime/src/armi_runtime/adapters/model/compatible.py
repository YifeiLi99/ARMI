"""Vendor-documented Qwen Chat and DeepSeek Responses structured transports."""

from __future__ import annotations

import json
from typing import Any, cast

from armi_kernel.application import (
    ModelBinding,
    ModelRequest,
    ModelViolation,
    normalize_token_usage,
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
        schema = self.output_format(request)
        inputs = self.render_input(request)
        if binding.provider == "qwen":
            return {
                "model": binding.model_id,
                "messages": [
                    {"role": "system", "content": self._instructions},
                    *inputs,
                ],
                "max_tokens": request.max_output_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {k: v for k, v in schema.items() if k != "type"},
                },
                "enable_thinking": False,
            }
        if binding.provider == "deepseek":
            # DeepSeek documents text.format fully supported; keep strict:true.
            # All purposes require schema-constrained output (DESIGN.md). Never
            # fall back to json_object, repair JSON or retry without the schema.
            return {
                "model": binding.model_id,
                "instructions": self._instructions,
                "input": inputs,
                "max_output_tokens": request.max_output_tokens,
                "text": {"format": schema},
                "reasoning": {"effort": "none"},
                "tools": [],
            }
        raise ModelViolation("MODEL-BINDING")

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
                if binding.provider == "qwen":
                    parameters["extra_body"] = {
                        "enable_thinking": parameters.pop("enable_thinking")
                    }
                    raw = cast(
                        Any,
                        await client.chat.completions.with_raw_response.create(
                            **parameters
                        ),
                    )
                else:
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
            quantities = None
            if binding.provider == "qwen" and isinstance(usage, dict):
                chat_usage = cast(dict[str, Any], usage)
                quantities = normalize_token_usage(
                    {
                        "input_tokens": chat_usage.get("prompt_tokens"),
                        "output_tokens": chat_usage.get("completion_tokens"),
                        "input_tokens_details": chat_usage.get("prompt_tokens_details"),
                    }
                )
            await call.capture(
                quantities=quantities,
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
        if binding.provider == "qwen":
            choices = document.get("choices")
            if not isinstance(choices, list) or len(cast(list[Any], choices)) != 1:
                raise ModelViolation("MODEL-PROVIDER-RESPONSE")
            choice = cast(list[dict[str, Any]], choices)[0]
            message = choice["message"]
            text = message.get("content") or ""
            forbidden = bool(
                message.get("tool_calls")
                or message.get("refusal")
                or message.get("reasoning_content")
            )
            normalized = {
                "status": "completed"
                if choice.get("finish_reason") == "stop"
                else "incomplete",
                "output": [{"type": "forbidden" if forbidden else "message"}],
            }
            normalized_usage = {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "cached_input_tokens": cast(
                    dict[str, Any], usage.get("prompt_tokens_details") or {}
                ).get("cached_tokens", 0),
            }
        else:
            normalized = document
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
            "raw": normalized,
        }
