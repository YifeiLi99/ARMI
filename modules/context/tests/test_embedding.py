from __future__ import annotations

from pathlib import Path
from typing import TypeVar
from uuid import uuid7

import pytest
from armi_context._embedding import (
    EMBEDDING_BINDING_ID,
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

ROOT = Path(__file__).resolve().parents[3]
MODEL_BINDINGS = ROOT / "configs/model-bindings.yaml"
_ResultT = TypeVar("_ResultT")


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
