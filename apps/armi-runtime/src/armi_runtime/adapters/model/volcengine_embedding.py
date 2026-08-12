"""Volcengine Ark text embedding adapter for Context projection and query text."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from armi_context.api import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBinding,
    EmbeddingResponse,
)
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    ModelViolation,
)

_PURPOSE = CredentialPurpose("model.embedding")


class EmbeddingTransport(Protocol):
    async def embed(
        self,
        *,
        api_key: memoryview,
        binding: EmbeddingBinding,
        text: str,
    ) -> dict[str, Any]: ...


class ArkEmbeddingTransport:
    async def embed(
        self,
        *,
        api_key: memoryview,
        binding: EmbeddingBinding,
        text: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=binding.timeout_seconds) as client:
            response = await client.post(
                f"{binding.api_base}/embeddings/multimodal",
                headers={
                    b"authorization": b"Bearer " + bytes(api_key),
                    b"content-type": b"application/json",
                },
                json={
                    "model": binding.model_id,
                    "input": [{"type": "text", "text": text}],
                    "encoding_format": "float",
                },
            )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        value["provider_request_id"] = response.headers.get("x-request-id")
        return value


class VolcengineArkEmbeddingAdapter:
    __slots__ = ("_binding", "_credential_port", "_locator", "_transport")

    def __init__(
        self,
        *,
        binding: EmbeddingBinding,
        credential_port: CredentialPort,
        locator: CredentialLocator,
        transport: EmbeddingTransport | None = None,
    ) -> None:
        if (
            binding.provider != "volcengine_ark"
            or binding.dimensions != EMBEDDING_DIMENSIONS
            or binding.credential_purpose != _PURPOSE.value
        ):
            raise ModelViolation("MODEL-BINDING")
        self._binding = binding
        self._credential_port = credential_port
        self._locator = locator
        self._transport = transport or ArkEmbeddingTransport()

    @property
    def binding(self) -> EmbeddingBinding:
        return self._binding

    async def embed(self, text: str) -> EmbeddingResponse:
        if type(text) is not str or not text or len(text) > 1500 or "\x00" in text:
            raise ModelViolation("MODEL-EMBEDDING-INPUT")
        secret = self._copy_secret()
        try:
            value = await self._transport.embed(
                api_key=memoryview(secret).toreadonly(),
                binding=self._binding,
                text=text,
            )
            data = value.get("data")
            usage = value.get("usage")
            if not isinstance(data, list) or len(data) != 1:
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
            embedding = data[0].get("embedding") if isinstance(data[0], dict) else None
            if (
                not isinstance(embedding, list)
                or len(embedding) != EMBEDDING_DIMENSIONS
                or any(type(item) not in {int, float} for item in embedding)
            ):
                raise ModelViolation("MODEL-EMBEDDING-DIMENSIONS")
            input_tokens = (
                usage.get("prompt_tokens", usage.get("input_tokens"))
                if isinstance(usage, dict)
                else None
            )
            if input_tokens is not None and (
                type(input_tokens) is not int or input_tokens < 0
            ):
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
            request_id = value.get("provider_request_id")
            if request_id is not None and type(request_id) is not str:
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
            return EmbeddingResponse(
                tuple(float(item) for item in embedding),
                request_id,
                input_tokens,
            )
        except ModelViolation:
            raise
        except httpx.TimeoutException:
            raise ModelViolation("MODEL-EMBEDDING-TIMEOUT") from None
        except httpx.HTTPStatusError as error:
            code = (
                "MODEL-CREDENTIAL"
                if error.response.status_code in {401, 403}
                else "MODEL-EMBEDDING-PROVIDER"
            )
            raise ModelViolation(code) from None
        except httpx.HTTPError:
            raise ModelViolation("MODEL-EMBEDDING-CONNECTION") from None
        finally:
            for index in range(len(secret)):
                secret[index] = 0

    def _copy_secret(self) -> bytearray:
        try:
            with self._credential_port.resolve(self._locator, _PURPOSE) as handle:
                return handle.consume(lambda value: bytearray(value))
        except Exception:
            raise ModelViolation("MODEL-CREDENTIAL") from None


__all__ = (
    "ArkEmbeddingTransport",
    "EmbeddingTransport",
    "VolcengineArkEmbeddingAdapter",
)
