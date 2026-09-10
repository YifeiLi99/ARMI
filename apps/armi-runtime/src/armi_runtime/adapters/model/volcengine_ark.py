"""Single-provider Volcengine Ark Responses adapter."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol, cast

import httpx
import rfc8785
from armi_cognition.api import CognitionSchemaDocument
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    ModelBinding,
    ModelInvocationResult,
    ModelPort,
    ModelRequest,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
)
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

_PURPOSE = CredentialPurpose("model.request")
_FINGERPRINT_DOMAIN = b"armi.model.credential-fingerprint.v1\0"
_EVOLVING_MODEL_ID = "doubao-seed-evolving"
_PROVIDER_MODEL_ID = re.compile(r"^doubao-seed-[a-z0-9-]{1,96}$", re.ASCII)
_CONTEXT_REF_PATTERN = r"^ctx:[1-9][0-9]{0,2}$"
_DIALOGUE_INPUT_VERSION = "armi.creator-dialogue-input.v6"


class ArkTransport(Protocol):
    async def tokenize(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request_bytes: bytes,
    ) -> int: ...

    async def invoke(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request: ModelRequest,
    ) -> dict[str, Any]: ...


class CandidateValue(Protocol):
    @property
    def schema_version(self) -> str: ...

    def model_dump_json(
        self,
        *,
        exclude_none: bool = False,
    ) -> str: ...


class CandidateParser(Protocol):
    def __call__(
        self,
        value: bytes,
        *,
        allowed_context_refs: frozenset[str],
    ) -> CandidateValue: ...


class OpenAIArkTransport:
    """OpenAI SDK transport pinned to the Ark API base."""

    __slots__ = ("_candidate_schema", "_instructions", "_schema_name")

    def __init__(
        self,
        candidate_schema: dict[str, Any],
        *,
        instructions: str,
        schema_name: str,
    ) -> None:
        self._candidate_schema = candidate_schema
        self._instructions = instructions
        self._schema_name = schema_name

    async def tokenize(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request_bytes: bytes,
    ) -> int:
        client = _client(api_key, binding)
        try:
            provider_input = _provider_input(request_bytes)
            rendered_input = (
                provider_input
                if isinstance(provider_input, str)
                else json.dumps(
                    provider_input, ensure_ascii=False, separators=(",", ":")
                )
            )
            provider_schema = _strict_provider_schema(
                self._candidate_schema,
                available_refs=_available_refs(request_bytes),
            )
            result_value = await client.post(
                "/tokenization",
                cast_to=cast(Any, dict[str, Any]),
                body={
                    "model": binding.model_id,
                    "text": "\n".join(
                        (
                            self._instructions,
                            rendered_input,
                            json.dumps(
                                provider_schema,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
                    ),
                },
            )
        finally:
            await client.close()
        if not isinstance(result_value, dict):
            raise ModelViolation("MODEL-TOKENIZATION")
        result = cast(dict[str, object], result_value)
        usage_value = result.get("usage")
        usage = (
            cast(dict[str, object], usage_value)
            if isinstance(usage_value, dict)
            else {}
        )
        data_value = result.get("data")
        data_tokens: object = None
        if isinstance(data_value, list):
            data_items = cast(list[object], data_value)
            if len(data_items) == 1 and isinstance(data_items[0], dict):
                data_item = cast(dict[str, object], data_items[0])
                data_tokens = data_item.get("total_tokens")
        candidate_values = (
            result.get("total_tokens"),
            usage.get("total_tokens"),
            usage.get("input_tokens"),
            data_tokens,
        )
        tokens = next(
            (value for value in candidate_values if type(value) is int and value > 0),
            None,
        )
        if tokens is None:
            raise ModelViolation("MODEL-TOKENIZATION")
        return tokens

    async def invoke(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request: ModelRequest,
    ) -> dict[str, Any]:
        client = _client(api_key, binding)
        try:
            provider_schema = _strict_provider_schema(
                self._candidate_schema,
                available_refs=_available_refs(request.canonical_bytes),
            )
            response = await client.responses.create(
                model=binding.model_id,
                instructions=self._instructions,
                input=cast(Any, _provider_input(request.canonical_bytes)),
                store=False,
                max_output_tokens=request.max_output_tokens,
                tools=[],
                text=cast(
                    Any,
                    {
                        "format": {
                            "type": "json_schema",
                            "name": self._schema_name,
                            "strict": True,
                            "schema": provider_schema,
                        }
                    },
                ),
                extra_body={"thinking": {"type": "disabled"}},
            )
        finally:
            await client.close()
        output_types = tuple(
            getattr(item, "type", type(item).__name__) for item in response.output
        )
        if not output_types or any(value != "message" for value in output_types):
            raise ModelViolation("MODEL-RESPONSE-FORBIDDEN")
        usage = response.usage
        return {
            "provider_request_id": response.id,
            "request_id": getattr(response, "_request_id", None),
            "model_id": response.model,
            "output_text": response.output_text,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cached_input_tokens": _cached_tokens(usage),
            },
            "raw": response.model_dump(mode="json"),
        }


def _provider_input(request_bytes: bytes) -> str | list[dict[str, str]]:
    try:
        text_value = request_bytes.decode("utf-8")
        request_value: object = json.loads(text_value)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ModelViolation("MODEL-REQUEST") from None
    if not isinstance(request_value, dict):
        return text_value
    request_document = cast(dict[object, object], request_value)
    if request_document.get("schema_version") != _DIALOGUE_INPUT_VERSION:
        return text_value
    messages_value = request_document.get("messages")
    if not isinstance(messages_value, list) or not messages_value:
        raise ModelViolation("MODEL-REQUEST")
    messages: list[dict[str, str]] = []
    for message_value in cast(list[object], messages_value):
        if not isinstance(message_value, dict):
            raise ModelViolation("MODEL-REQUEST")
        message = cast(dict[object, object], message_value)
        role = message.get("role")
        content = message.get("content")
        if (
            role not in {"system", "user", "assistant"}
            or not isinstance(content, str)
            or not content
        ):
            raise ModelViolation("MODEL-REQUEST")
        messages.append({"role": cast(str, role), "content": content})
    return messages


class VolcengineArkModelAdapter(ModelPort):
    """Resolve one credential and invoke the only active Ark binding."""

    __slots__ = (
        "_binding",
        "_credential_port",
        "_locator",
        "_parse_candidate",
        "_transport",
    )

    def __init__(
        self,
        *,
        binding: ModelBinding,
        credential_port: CredentialPort,
        locator: CredentialLocator,
        candidate_schema: CognitionSchemaDocument,
        candidate_parser: CandidateParser,
        instructions: str,
        schema_name: str,
        transport: ArkTransport | None = None,
    ) -> None:
        if (
            binding.provider != "volcengine_ark"
            or binding.model_id != _EVOLVING_MODEL_ID
            or binding.version_policy != "provider_evolving_alias"
            or not binding.response_model_identity_required
        ):
            raise ModelViolation("MODEL-BINDING")
        self._binding = binding
        self._credential_port = credential_port
        self._locator = locator
        self._parse_candidate = candidate_parser
        provider_schema = cast(
            dict[str, Any], json.loads(candidate_schema.canonical_bytes)
        )
        self._transport = transport or OpenAIArkTransport(
            provider_schema,
            instructions=instructions,
            schema_name=schema_name,
        )

    @property
    def binding(self) -> ModelBinding:
        return self._binding

    def credential_fingerprint(self) -> str:
        secret = self._copy_secret()
        try:
            return (
                "sha256:"
                + hashlib.sha256(_FINGERPRINT_DOMAIN + bytes(secret)).hexdigest()
            )
        finally:
            _wipe(secret)

    async def tokenize(self, canonical_request: bytes) -> int:
        secret = self._copy_secret()
        try:
            return await self._transport.tokenize(
                api_key=memoryview(secret).toreadonly(),
                binding=self._binding,
                request_bytes=canonical_request,
            )
        except ModelViolation:
            raise
        except APITimeoutError:
            raise ModelViolation("MODEL-TOKENIZATION-TIMEOUT", retryable=True) from None
        except APIConnectionError:
            raise ModelViolation("MODEL-CONNECTION", retryable=True) from None
        except APIStatusError as error:
            raise _status_violation(error.status_code, dispatched=False) from None
        except Exception:
            raise ModelViolation("MODEL-TOKENIZATION") from None
        finally:
            _wipe(secret)

    async def invoke(self, request: ModelRequest) -> ModelInvocationResult:
        if request.input_tokens > self._binding.input_token_limit:
            raise ModelViolation("MODEL-BUDGET")
        secret = self._copy_secret()
        try:
            response = await self._transport.invoke(
                api_key=memoryview(secret).toreadonly(),
                binding=self._binding,
                request=request,
            )
            return self._settle_response(response, request)
        except ModelViolation:
            raise
        except APITimeoutError:
            return _failure(
                ModelResultStatus.TIMED_OUT,
                "MODEL-REQUEST-TIMEOUT",
            )
        except APIConnectionError:
            return _failure(
                ModelResultStatus.OUTCOME_UNKNOWN,
                "MODEL-OUTCOME-UNKNOWN",
            )
        except APIStatusError as error:
            raise _status_violation(error.status_code, dispatched=True) from None
        except Exception:
            return _failure(
                ModelResultStatus.PROVIDER_FAILED,
                "MODEL-PROVIDER-RESPONSE",
            )
        finally:
            _wipe(secret)

    def _copy_secret(self) -> bytearray:
        try:
            with self._credential_port.resolve(self._locator, _PURPOSE) as handle:
                return handle.consume(lambda value: bytearray(value))
        except Exception:
            raise ModelViolation("MODEL-CREDENTIAL") from None

    def _settle_response(
        self,
        response: dict[str, Any],
        request: ModelRequest,
    ) -> ModelInvocationResult:
        try:
            provider_request_id = response["provider_request_id"]
            model_id = response["model_id"]
            output_text = response["output_text"]
            usage_value = response["usage"]
            raw_value = response["raw"]
            input_tokens = usage_value["input_tokens"]
            output_tokens = usage_value["output_tokens"]
            cached_tokens = usage_value["cached_input_tokens"]
        except KeyError, TypeError:
            raise ModelViolation("MODEL-PROVIDER-RESPONSE") from None
        if (
            type(provider_request_id) is not str
            or not provider_request_id
            or type(model_id) is not str
            or _PROVIDER_MODEL_ID.fullmatch(model_id) is None
            or type(output_text) is not str
            or not output_text
            or type(input_tokens) is not int
            or input_tokens < 0
            or type(output_tokens) is not int
            or output_tokens < 0
            or type(cached_tokens) is not int
            or cached_tokens < 0
        ):
            raise ModelViolation("MODEL-PROVIDER-RESPONSE")
        usage = ModelUsage(
            input_tokens,
            output_tokens,
            cached_tokens,
            self._binding.estimate_cost_microyuan(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )
        try:
            allowed_refs = _candidate_allowed_refs(request.canonical_bytes)
            candidate = self._parse_candidate(
                output_text.encode("utf-8"),
                allowed_context_refs=allowed_refs,
            )
        except json.JSONDecodeError, KeyError, TypeError, UnicodeEncodeError:
            return _failure(
                ModelResultStatus.REJECTED,
                "MODEL-RESPONSE-SCHEMA",
                provider_request_id=provider_request_id,
                provider_model_id=model_id,
                usage=usage,
            )
        except ModelViolation as error:
            return _failure(
                ModelResultStatus.REJECTED,
                (
                    error.code
                    if error.code
                    in {"MODEL-RESPONSE-LIMIT", "MODEL-RESPONSE-REFERENCE"}
                    else "MODEL-RESPONSE-SCHEMA"
                ),
                provider_request_id=provider_request_id,
                provider_model_id=model_id,
                usage=usage,
            )
        if candidate.schema_version != self._binding.response_contract_version:
            return _failure(
                ModelResultStatus.REJECTED,
                "MODEL-RESPONSE-SCHEMA",
                provider_request_id=provider_request_id,
                provider_model_id=model_id,
                usage=usage,
            )
        if _contains_forbidden_output(raw_value):
            return _failure(
                ModelResultStatus.REJECTED,
                "MODEL-RESPONSE-FORBIDDEN",
                provider_request_id=provider_request_id,
                provider_model_id=model_id,
                usage=usage,
            )
        safe_response = {
            "schema_version": "armi.model-response-artifact.v1",
            "provider_request_id": provider_request_id,
            "provider_model_id": model_id,
            "candidate": json.loads(candidate.model_dump_json(exclude_none=True)),
            "usage": usage_value,
        }
        response_bytes = rfc8785.dumps(cast(Any, safe_response)) + b"\n"
        return ModelInvocationResult(
            ModelResultStatus.SUCCEEDED,
            provider_request_id,
            model_id,
            response_bytes,
            usage,
        )


def _client(api_key: memoryview, binding: ModelBinding) -> AsyncOpenAI:
    try:
        key = bytes(api_key).decode("utf-8")
    except UnicodeDecodeError:
        raise ModelViolation("MODEL-CREDENTIAL") from None
    return AsyncOpenAI(
        api_key=key,
        base_url=binding.api_base,
        max_retries=0,
        timeout=binding.timeout_seconds,
        http_client=httpx.AsyncClient(trust_env=False),
    )


def _available_refs(request_bytes: bytes) -> tuple[str, ...]:
    try:
        value: object = json.loads(request_bytes)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ModelViolation("MODEL-REQUEST") from None
    if not isinstance(value, dict):
        return ()
    refs = cast(dict[object, object], value).get("available_refs")
    if not isinstance(refs, list):
        return ()
    ref_values = cast(list[object], refs)
    if any(type(item) is not str for item in ref_values):
        return ()
    return tuple(sorted(set(cast(list[str], ref_values))))


def _candidate_allowed_refs(request_bytes: bytes) -> frozenset[str]:
    value: object = json.loads(request_bytes)
    if not isinstance(value, dict):
        raise TypeError("model request must be an object")
    document = cast(dict[object, object], value)
    available_refs = document.get("available_refs")
    if isinstance(available_refs, list):
        return frozenset(str(item) for item in cast(list[object], available_refs))
    included_context_refs = document.get("included_context_refs", ())
    if not isinstance(included_context_refs, (list, tuple)):
        raise TypeError("included context refs must be a sequence")
    refs: set[str] = set()
    for item in cast(list[object] | tuple[object, ...], included_context_refs):
        if not isinstance(item, dict):
            raise TypeError("included context ref must be an object")
        ref = cast(dict[object, object], item).get("ref")
        if ref is None:
            raise KeyError("ref")
        refs.add(str(ref))
    return frozenset(refs)


def _strict_provider_schema(
    value: object,
    *,
    available_refs: tuple[str, ...],
) -> object:
    if isinstance(value, list):
        return [
            _strict_provider_schema(item, available_refs=available_refs)
            for item in cast(list[object], value)
        ]
    if not isinstance(value, dict):
        return value
    result: dict[str, object] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise ModelViolation("MODEL-BINDING")
        if key in {"default", "discriminator"} or (
            key == "title" and isinstance(item, str)
        ):
            continue
        result[key] = _strict_provider_schema(item, available_refs=available_refs)
    if (
        available_refs
        and result.get("type") == "string"
        and result.get("pattern") == _CONTEXT_REF_PATTERN
    ):
        result.pop("pattern")
        result.pop("maxLength", None)
        result["enum"] = list(available_refs)
    properties = result.get("properties")
    if isinstance(properties, dict):
        property_keys = tuple(cast(dict[object, object], properties))
        if any(not isinstance(key, str) for key in property_keys):
            raise ModelViolation("MODEL-BINDING")
        result["required"] = list(cast(tuple[str, ...], property_keys))
        result["additionalProperties"] = False
    elif result.get("type") == "object" and "additionalProperties" not in result:
        result["additionalProperties"] = False
    return result


def _cached_tokens(usage: object) -> int:
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0)
    return cached if type(cached) is int and cached >= 0 else 0


def _contains_forbidden_output(value: object) -> bool:
    if not isinstance(value, dict):
        return True
    output_value = cast(dict[str, object], value).get("output")
    if not isinstance(output_value, list):
        return True
    output = cast(list[object], output_value)
    return any(
        not isinstance(item, dict)
        or cast(dict[str, object], item).get("type") != "message"
        for item in output
    )


def _failure(
    status: ModelResultStatus,
    code: str,
    *,
    provider_request_id: str | None = None,
    provider_model_id: str | None = None,
    usage: ModelUsage | None = None,
) -> ModelInvocationResult:
    return ModelInvocationResult(
        status,
        provider_request_id,
        provider_model_id,
        None,
        usage,
        code,
    )


def _status_violation(status_code: int, *, dispatched: bool) -> ModelViolation:
    if status_code == 429:
        return ModelViolation("MODEL-RATE-LIMITED", retryable=True)
    if 500 <= status_code <= 599:
        return ModelViolation("MODEL-PROVIDER-UNAVAILABLE", retryable=True)
    if status_code in {401, 403}:
        return ModelViolation("MODEL-CREDENTIAL")
    if status_code == 404:
        return ModelViolation("MODEL-NOT-AVAILABLE")
    if dispatched:
        return ModelViolation("MODEL-PROVIDER-REJECTED")
    return ModelViolation("MODEL-TOKENIZATION")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = (
    "ArkTransport",
    "CandidateParser",
    "OpenAIArkTransport",
    "VolcengineArkModelAdapter",
)
