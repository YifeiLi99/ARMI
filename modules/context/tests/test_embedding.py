from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Self, TypeVar
from uuid import uuid7

import pytest
from armi_cognition._model_contract import load_purpose_binding
from armi_context._embedding import (
    EMBEDDING_BINDING_ID,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    LIFE_MATERIAL_CHUNK_CHARS,
    LIFE_MATERIAL_CHUNK_OVERLAP,
    chunk_life_material,
    load_embedding_binding,
)
from armi_context._profiles import context_profile
from armi_context.api import (
    ContextItemCandidate,
    ContextLayer,
    ContextRequirement,
    ContextSection,
    ContextSourceIdentity,
    ContextTrustClass,
    ContextViolation,
)
from armi_kernel.application import (
    CredentialLocator,
    CredentialPurpose,
    ModelViolation,
    SecretHandle,
)
from armi_runtime.adapters.model.volcengine_embedding import (
    VolcengineArkEmbeddingAdapter,
)

ROOT = Path(__file__).resolve().parents[3]
MODEL_BINDINGS = ROOT / "configs/model-bindings.yaml"
_ResultT = TypeVar("_ResultT")


class _Handle(AbstractContextManager["_Handle"]):
    @property
    def closed(self) -> bool:
        return False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def consume(self, operation: Callable[[memoryview], _ResultT]) -> _ResultT:
        return operation(memoryview(b"secret"))

    def close(self) -> None:
        return None


class _Credentials:
    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        assert locator.identity() == "file:ark"
        assert purpose.value == "model.embedding"
        return _Handle()


class _Transport:
    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    async def embed(self, **kwargs: object) -> dict[str, Any]:
        assert kwargs["text"] == "当前查询"
        return {
            "data": [{"embedding": [0.5] * self.dimensions}],
            "usage": {"prompt_tokens": 3},
            "provider_request_id": "request-1",
        }


def test_embedding_binding_is_fixed_and_uses_independent_purpose() -> None:
    binding = load_embedding_binding(MODEL_BINDINGS)
    assert binding.model_binding == EMBEDDING_BINDING_ID
    assert binding.model_id == EMBEDDING_MODEL_ID
    assert binding.dimensions == 1024
    assert binding.credential_locator == "model.ark_api_key"
    assert binding.credential_purpose == "model.embedding"


def test_life_material_chunking_is_deterministic_with_fixed_overlap() -> None:
    text = "x" * 2900
    chunks = chunk_life_material(text)
    assert tuple(map(len, chunks)) == (1500, 1500, 200)
    assert (
        chunks[0][-LIFE_MATERIAL_CHUNK_OVERLAP:]
        == chunks[1][:LIFE_MATERIAL_CHUNK_OVERLAP]
    )
    assert LIFE_MATERIAL_CHUNK_CHARS == 1500
    assert chunk_life_material(text) == chunks


@pytest.mark.asyncio
async def test_embedding_adapter_enforces_1024_dimensions() -> None:
    binding = load_embedding_binding(MODEL_BINDINGS)
    adapter = VolcengineArkEmbeddingAdapter(
        binding=binding,
        credential_port=_Credentials(),
        locator=CredentialLocator("file", "ark"),
        transport=_Transport(),
    )
    response = await adapter.embed("当前查询")
    assert len(response.vector) == 1024
    assert response.input_tokens == 3

    invalid = VolcengineArkEmbeddingAdapter(
        binding=binding,
        credential_port=_Credentials(),
        locator=CredentialLocator("file", "ark"),
        transport=_Transport(1023),
    )
    with pytest.raises(ModelViolation, match="MODEL-EMBEDDING-DIMENSIONS"):
        await invalid.embed("当前查询")


def test_all_cognitive_purposes_have_explicit_context_profiles() -> None:
    purposes = {
        "consider_creator_input",
        "consider_life_query_result",
        "consider_web_evidence",
        "consider_creator_outreach",
        "consider_other_human_input",
        "consider_autonomous_life",
        "consider_activity_attention",
        "consider_activity_internal_work",
        "consider_sleep",
        "maintain_subjective_memory",
        "perform_subject_self_check",
        "consider_codex_task",
        "consider_codex_result",
    }
    assert {context_profile(purpose).purpose for purpose in purposes} == purposes
    assert {
        load_purpose_binding(purpose, MODEL_BINDINGS).profile for purpose in purposes
    } == {
        "creator_dialogue",
        "web_evidence_cognition",
        "creator_outreach",
        "other_human_dialogue",
        "autonomous_activity",
        "activity_attention",
        "activity_internal_work",
        "sleep_decision",
        "memory_maintenance",
        "subject_self_check",
        "codex_task",
        "codex_result",
    }
    other = context_profile("consider_other_human_input")
    assert other.allows("self") and other.allows("mind")
    assert not other.allows("creator_prompt")
    assert not other.allows("current_memory")
    assert not other.allows("current_material")


def test_profile_fails_when_a_required_source_is_missing() -> None:
    profile = context_profile("consider_creator_input")
    candidate = ContextItemCandidate(
        ContextSection.RUNTIME_TRUTH,
        "runtime_identity",
        ContextSourceIdentity("runtime_identity", uuid7(), 1),
        ContextTrustClass.RUNTIME_AUTHORITY,
        "private",
        "runtime",
        ContextRequirement.REQUIRED,
        ContextLayer.STABLE_PREFIX,
        100,
    )
    with pytest.raises(ContextViolation, match="CTX-SOURCE-MISSING"):
        profile.validate((candidate,))
