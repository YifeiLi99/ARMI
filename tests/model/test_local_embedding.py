"""Local llama.cpp embedding boundary tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from armi_context.api import EMBEDDING_QUERY_INSTRUCTION, load_embedding_binding
from armi_runtime.adapters.model import local_embedding
from armi_runtime.adapters.model.local_embedding import LocalLlamaCppEmbeddingAdapter

ROOT = Path(__file__).resolve().parents[2]
TEMPORARY_TOKEN = "temporary" + "-token"


@pytest.mark.asyncio
async def test_local_embedding_uses_loopback_without_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_options: dict[str, Any] = {}
    requests: list[tuple[str, dict[str, str], dict[str, object]]] = []

    class Response:
        def __init__(self) -> None:
            self.headers = {"x-request-id": "request-1"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [{"index": 0, "embedding": [0.03125] * 1024}],
                "usage": {"prompt_tokens": 7},
            }

    class Client:
        def __init__(self, **options: Any) -> None:
            client_options.update(options)

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> Response:
            requests.append((url, headers, json))
            return Response()

    monkeypatch.setattr(local_embedding.httpx, "AsyncClient", Client)
    binding = load_embedding_binding(ROOT / "configs/model-bindings.yaml")
    adapter = LocalLlamaCppEmbeddingAdapter(
        binding=binding,
        base_url="http://127.0.0.1:45000/v1",
        api_key=TEMPORARY_TOKEN,
    )

    response = await adapter.embed_query("主人喜欢什么?")

    assert client_options["trust_env"] is False
    assert requests == [
        (
            "http://127.0.0.1:45000/v1/embeddings",
            {"authorization": f"Bearer {TEMPORARY_TOKEN}"},
            {
                "model": binding.model_id,
                "input": [f"{EMBEDDING_QUERY_INSTRUCTION}主人喜欢什么?"],
                "encoding_format": "float",
            },
        )
    ]
    assert response.provider_request_id == "request-1"
    assert response.input_tokens == 7


@pytest.mark.asyncio
async def test_document_embedding_does_not_add_query_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs: list[list[str]] = []

    class Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {"index": index, "embedding": [0.03125] * 1024}
                    for index in range(2)
                ]
            }

    class Client:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, **options: Any) -> Response:
            inputs.append(options["json"]["input"])
            return Response()

    monkeypatch.setattr(local_embedding.httpx, "AsyncClient", Client)
    binding = load_embedding_binding(ROOT / "configs/model-bindings.yaml")
    adapter = LocalLlamaCppEmbeddingAdapter(
        binding=binding,
        base_url="http://127.0.0.1:45000/v1",
        api_key=TEMPORARY_TOKEN,
    )

    responses = await adapter.embed_documents(("记忆一", "材料二"))

    assert inputs == [["记忆一", "材料二"]]
    assert len(responses) == 2


@pytest.mark.asyncio
async def test_local_embedding_reuses_and_closes_loopback_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = 0
    closed = 0

    class Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [{"index": 0, "embedding": [0.03125] * 1024}],
                "usage": {"prompt_tokens": 7},
            }

    class Client:
        def __init__(self, **_options: Any) -> None:
            nonlocal created
            created += 1

        async def post(self, _url: str, **_options: Any) -> Response:
            return Response()

        async def aclose(self) -> None:
            nonlocal closed
            closed += 1

    monkeypatch.setattr(local_embedding.httpx, "AsyncClient", Client)
    binding = load_embedding_binding(ROOT / "configs/model-bindings.yaml")
    adapter = LocalLlamaCppEmbeddingAdapter(
        binding=binding,
        base_url="http://127.0.0.1:45000/v1",
        api_key=TEMPORARY_TOKEN,
    )

    await adapter.embed_query("第一次查询")
    await adapter.embed_query("第二次查询")
    await adapter.close()

    assert created == 1
    assert closed == 1
