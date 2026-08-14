"""Volcengine embedding transport boundary tests."""

from __future__ import annotations

from typing import Any

import pytest
from armi_context.api import EMBEDDING_DIMENSIONS, EmbeddingBinding
from armi_runtime.adapters.model import volcengine_embedding
from armi_runtime.adapters.model.volcengine_embedding import ArkEmbeddingTransport


@pytest.mark.asyncio
async def test_embedding_transport_ignores_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_options: dict[str, Any] = {}

    class Response:
        def __init__(self) -> None:
            self.headers = {"x-request-id": "request-1"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": []}

    class Client:
        def __init__(self, **options: Any) -> None:
            client_options.update(options)

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(volcengine_embedding.httpx, "AsyncClient", Client)
    binding = EmbeddingBinding(
        provider="volcengine_ark",
        api_base="https://ark.cn-beijing.volces.com/api/v3",
        model_id="doubao-embedding-vision-250615",
        model_binding="armi.embedding.test.v1",
        dimensions=EMBEDDING_DIMENSIONS,
        timeout_seconds=30,
        credential_identity="armi.model.ark-api-key.v1",
        credential_locator="model.ark_api_key",
        credential_purpose="model.embedding",
    )

    await ArkEmbeddingTransport().embed(
        api_key=memoryview(b"test-key"),
        binding=binding,
        text="test",
    )

    assert client_options["trust_env"] is False
