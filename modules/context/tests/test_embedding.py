from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast
from uuid import uuid7

import pytest
from armi_context._embedding import (
    EMBEDDING_BINDING_ID,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_MODEL_SHA256,
    LIFE_MATERIAL_CHUNK_CHARS,
    LIFE_MATERIAL_CHUNK_OVERLAP,
    chunk_life_material,
    load_embedding_binding,
)
from armi_context._embedding_postgresql import (
    PostgreSQLContextEmbeddingRepository,
    RecalledContext,
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
    RecallStatus,
)

ROOT = Path(__file__).resolve().parents[3]
MODEL_BINDINGS = ROOT / "configs/model-bindings.yaml"
_ResultT = TypeVar("_ResultT")


def test_embedding_binding_is_fixed_and_local() -> None:
    binding = load_embedding_binding(MODEL_BINDINGS)
    assert binding.model_binding == EMBEDDING_BINDING_ID
    assert binding.model_id == EMBEDDING_MODEL_ID
    assert binding.model_revision == EMBEDDING_MODEL_REVISION
    assert binding.model_sha256 == EMBEDDING_MODEL_SHA256
    assert binding.dimensions == 1024
    assert binding.provider == "local_llama_cpp"
    assert binding.pooling == "last"
    assert binding.normalization == "l2"
    assert binding.document_batch_size == 8
    assert binding.retrieval_profile == (
        "armi.semantic-recall.hybrid-hnsw-gist-exact-rerank.v3"
    )
    assert binding.dense_ann_candidates == 256
    assert binding.dense_final_candidates == 32
    assert binding.hnsw_ef_search == 256
    assert binding.lexical_candidates == 128
    assert binding.lexical_final_candidates == 32
    assert binding.dense_min_similarity == 0.40


def test_dense_and_lexical_candidates_use_two_read_transactions() -> None:
    class UnitOfWorkContext:
        async def __aenter__(self) -> Any:
            return SimpleNamespace(transaction=object())

        async def __aexit__(self, *args: object) -> None:
            del args

    class Factory:
        def __init__(self) -> None:
            self.calls = 0

        def unit_of_work(self, *, read_only: bool = False) -> UnitOfWorkContext:
            assert read_only
            self.calls += 1
            return UnitOfWorkContext()

    class Repository(PostgreSQLContextEmbeddingRepository):
        def __init__(self) -> None:
            super().__init__(cast(Any, object()), cast(Any, object()))
            self.active = 0
            self.maximum_active = 0
            self.both_started = asyncio.Event()

        async def _candidate_probe(self) -> list[tuple[object, ...]]:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            if self.active == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), timeout=1)
            await asyncio.sleep(0)
            self.active -= 1
            return []

        async def _dense_candidate_rows(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return await self._candidate_probe()

        async def _lexical_candidate_rows(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return await self._candidate_probe()

        async def recall(self, *args: Any, **kwargs: Any) -> RecalledContext:
            del args
            assert kwargs["_candidate_rows"] == ([], [])
            return RecalledContext(RecallStatus.NO_RELEVANT_RESULT, (), ())

    async def exercise() -> tuple[RecalledContext, int, int]:
        repository = Repository()
        factory = Factory()
        result = await repository.recall_parallel(
            cast(Any, factory),
            subject_id=uuid7(),
            life_generation_id=uuid7(),
            query_text="蓝色设备编号",
            query_vector=tuple(0.0 for _ in range(1024)),
        )
        return result, repository.maximum_active, factory.calls

    result, maximum_active, calls = asyncio.run(exercise())
    assert result.status is RecallStatus.NO_RELEVANT_RESULT
    assert maximum_active == 2
    assert calls == 3


def test_life_material_chunking_is_deterministic_with_fixed_overlap() -> None:
    text = "x" * 2900
    chunks = chunk_life_material(text)
    assert tuple(map(len, chunks)) == (800, 800, 800, 740)
    assert (
        chunks[0][-LIFE_MATERIAL_CHUNK_OVERLAP:]
        == chunks[1][:LIFE_MATERIAL_CHUNK_OVERLAP]
    )
    assert LIFE_MATERIAL_CHUNK_CHARS == 800
    assert chunk_life_material(text) == chunks


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
