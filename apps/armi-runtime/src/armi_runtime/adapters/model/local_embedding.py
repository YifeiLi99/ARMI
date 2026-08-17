"""Loopback llama.cpp adapter for the local Context embedding model."""

from __future__ import annotations

import math
from typing import cast

import httpx
from armi_context.api import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_QUERY_MAX_CHARS,
    EmbeddingBinding,
    EmbeddingResponse,
)
from armi_kernel.application import ModelViolation


class LocalLlamaCppEmbeddingAdapter:
    __slots__ = ("_api_key", "_base_url", "_binding")

    def __init__(
        self,
        *,
        binding: EmbeddingBinding,
        base_url: str,
        api_key: str,
    ) -> None:
        if (
            binding.provider != "local_llama_cpp"
            or binding.dimensions != EMBEDDING_DIMENSIONS
            or binding.pooling != "last"
            or binding.normalization != "l2"
            or not base_url.startswith("http://127.0.0.1:")
            or not api_key
        ):
            raise ModelViolation("MODEL-BINDING")
        self._binding = binding
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @property
    def binding(self) -> EmbeddingBinding:
        return self._binding

    async def embed_query(self, text: str) -> EmbeddingResponse:
        if (
            type(text) is not str
            or not text.strip()
            or len(text) > EMBEDDING_QUERY_MAX_CHARS
            or "\x00" in text
        ):
            raise ModelViolation("MODEL-EMBEDDING-INPUT")
        values = await self._embed(
            (f"{self._binding.query_instruction}{text.strip()}",)
        )
        return values[0]

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[EmbeddingResponse, ...]:
        if (
            not texts
            or len(texts) > self._binding.document_batch_size
            or any(
                type(text) is not str
                or not text.strip()
                or len(text) > 1200
                or "\x00" in text
                for text in texts
            )
        ):
            raise ModelViolation("MODEL-EMBEDDING-INPUT")
        return await self._embed(tuple(text.strip() for text in texts))

    async def _embed(self, texts: tuple[str, ...]) -> tuple[EmbeddingResponse, ...]:
        try:
            async with httpx.AsyncClient(
                timeout=self._binding.timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._binding.model_id,
                        "input": list(texts),
                        "encoding_format": "float",
                    },
                )
            response.raise_for_status()
            value: object = response.json()
        except httpx.TimeoutException:
            raise ModelViolation("MODEL-EMBEDDING-TIMEOUT") from None
        except httpx.HTTPStatusError as error:
            code = (
                "MODEL-CREDENTIAL"
                if error.response.status_code in {401, 403}
                else "MODEL-EMBEDDING-PROVIDER"
            )
            raise ModelViolation(code) from None
        except httpx.HTTPError, ValueError:
            raise ModelViolation("MODEL-EMBEDDING-CONNECTION") from None
        if not isinstance(value, dict):
            raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        document = cast(dict[object, object], value)
        data_value = document.get("data")
        if not isinstance(data_value, list):
            raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        data = cast(list[object], data_value)
        if len(data) != len(texts):
            raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        usage_value = document.get("usage")
        input_tokens = None
        if isinstance(usage_value, dict):
            input_tokens = cast(dict[object, object], usage_value).get("prompt_tokens")
            if input_tokens is not None and (
                type(input_tokens) is not int or input_tokens < 0
            ):
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        request_id = response.headers.get("x-request-id")
        parsed: list[tuple[int, EmbeddingResponse]] = []
        for expected_index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
            row = cast(dict[object, object], item)
            index = row.get("index", expected_index)
            embedding_value = row.get("embedding")
            if type(index) is not int or not isinstance(embedding_value, list):
                raise ModelViolation("MODEL-EMBEDDING-DIMENSIONS")
            embedding = cast(list[object], embedding_value)
            if len(embedding) != EMBEDDING_DIMENSIONS or any(
                type(part) not in {int, float} for part in embedding
            ):
                raise ModelViolation("MODEL-EMBEDDING-DIMENSIONS")
            vector = tuple(float(cast(int | float, part)) for part in embedding)
            norm = math.sqrt(sum(part * part for part in vector))
            if (
                any(not math.isfinite(part) for part in vector)
                or not 0.98 <= norm <= 1.02
            ):
                raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
            parsed.append(
                (
                    index,
                    EmbeddingResponse(vector, request_id, input_tokens),
                )
            )
        parsed.sort(key=lambda item: item[0])
        if [item[0] for item in parsed] != list(range(len(texts))):
            raise ModelViolation("MODEL-EMBEDDING-RESPONSE")
        return tuple(item[1] for item in parsed)


__all__ = ("LocalLlamaCppEmbeddingAdapter",)
