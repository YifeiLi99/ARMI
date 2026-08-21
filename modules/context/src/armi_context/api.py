"""Public contracts for Context compilation, recall and preparation."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from uuid import UUID

from armi_kernel import load_yaml_file
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    ArtifactRegistration,
    CandidateBasis,
    CognitiveEpisodeId,
    ModelViolation,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, Instant, Purpose, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_CODE = re.compile(r"^CTX-[A-Z0-9-]+$", re.ASCII)


class ContextViolation(RuntimeError):
    """Expose one stable Context failure without source content or adapter detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("context violation code is invalid")
        self.code = code
        super().__init__("context operation failed")

    def __str__(self) -> str:
        return f"{self.code}: context operation failed"


class ContextSection(StrEnum):
    RUNTIME_TRUTH = "runtime_truth"
    PURPOSE = "purpose"
    SELF = "self"
    MIND = "mind"
    MOOD = "mood"
    LIFE_MODE = "life_mode"
    SCENE = "scene"
    RELATIONSHIP = "relationship"
    MEMORY = "memory"
    ACTIVITY = "activity"
    MATERIAL = "material"
    EVIDENCE = "evidence"
    CAPABILITY = "capability"
    PROMPT = "prompt"


class ContextRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class ContextLayer(StrEnum):
    STABLE_PREFIX = "stable_prefix"
    SCOPE_CONTEXT = "scope_context"
    CONVERSATION_HISTORY = "conversation_history"
    TURN_TAIL = "turn_tail"


class ContextItemDisposition(StrEnum):
    INCLUDED = "included"
    EXCLUDED_POLICY = "excluded_policy"
    EXCLUDED_BUDGET = "excluded_budget"
    UNAVAILABLE = "unavailable"
    READ_FAILED = "read_failed"


class ContextTrustClass(StrEnum):
    RUNTIME_AUTHORITY = "runtime_authority"
    SUBJECTIVE_STATE = "subjective_state"
    EXTERNAL_CLAIM = "external_claim"
    POLICY = "policy"


@dataclass(frozen=True, slots=True)
class ContextSourceIdentity:
    kind: str
    reference: UUID | None
    version: int | None

    def __post_init__(self) -> None:
        _require_token(self.kind)
        present = (self.reference is not None, self.version is not None)
        if any(present) and not all(present):
            raise ContextViolation("CTX-SOURCE-IDENTITY")
        if self.reference is not None:
            _require_uuid7(self.reference)
            if type(self.version) is not int or self.version < 0:
                raise ContextViolation("CTX-SOURCE-IDENTITY")


@dataclass(frozen=True, slots=True)
class ContextItemCandidate:
    section: ContextSection
    item_kind: str
    source: ContextSourceIdentity
    trust_class: ContextTrustClass
    privacy_scope: str
    content: str | None
    requirement: ContextRequirement
    layer: ContextLayer
    relevance: int
    business_time: Instant | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.section) is not ContextSection
            or type(self.source) is not ContextSourceIdentity
            or type(self.trust_class) is not ContextTrustClass
            or type(self.requirement) is not ContextRequirement
            or type(self.layer) is not ContextLayer
        ):
            raise ContextViolation("CTX-ITEM")
        _require_token(self.item_kind)
        _require_token(self.privacy_scope)
        if type(self.relevance) is not int or not 0 <= self.relevance <= 100:
            raise ContextViolation("CTX-ITEM")
        if self.business_time is not None and type(self.business_time) is not Instant:
            raise ContextViolation("CTX-ITEM")
        if self.content is None:
            if (
                self.source.reference is not None
                or self.requirement is ContextRequirement.REQUIRED
            ):
                raise ContextViolation("CTX-ITEM")
            if (
                type(self.unavailable_reason) is not str
                or _CODE.fullmatch(self.unavailable_reason) is None
            ):
                raise ContextViolation("CTX-ITEM")
        elif self.unavailable_reason is not None:
            raise ContextViolation("CTX-ITEM")
        try:
            self.content.encode("utf-8", errors="strict") if self.content else b""
        except UnicodeEncodeError:
            raise ContextViolation("CTX-UNICODE") from None

    @property
    def required(self) -> bool:
        return self.requirement is ContextRequirement.REQUIRED


@dataclass(frozen=True, slots=True)
class ContextRequest:
    purpose: Purpose
    subject_id: UUID
    scene_id: UUID | None
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    policy_version: str
    mechanism_identity: str
    max_items: int
    max_item_bytes: int
    max_compiled_bytes: int
    items: tuple[ContextItemCandidate, ...]

    def __post_init__(self) -> None:
        if type(self.purpose) is not Purpose:
            raise ContextViolation("CTX-REQUEST")
        for value in (self.subject_id, self.bundle_activation_id):
            _require_uuid7(value)
        if self.scene_id is not None:
            _require_uuid7(self.scene_id)
        for value in (self.base_subject_version, self.base_state_epoch):
            if type(value) is not int or value < 0:
                raise ContextViolation("CTX-REQUEST")
        _require_token(self.policy_version)
        _require_token(self.mechanism_identity)
        if (
            type(self.max_items) is not int
            or not 1 <= self.max_items <= 1024
            or type(self.max_item_bytes) is not int
            or self.max_item_bytes <= 0
            or type(self.max_compiled_bytes) is not int
            or self.max_compiled_bytes <= 0
        ):
            raise ContextViolation("CTX-BUDGET")
        if type(self.items) is not tuple or any(
            type(item) is not ContextItemCandidate for item in self.items
        ):
            raise ContextViolation("CTX-REQUEST")


@dataclass(frozen=True, slots=True)
class ContextItemResult:
    candidate: ContextItemCandidate
    ordinal: int
    disposition: ContextItemDisposition
    content_bytes: int
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.candidate) is not ContextItemCandidate
            or type(self.ordinal) is not int
            or self.ordinal <= 0
            or type(self.disposition) is not ContextItemDisposition
            or type(self.content_bytes) is not int
            or self.content_bytes < 0
        ):
            raise ContextViolation("CTX-RESULT")
        if self.reason_code is not None and _CODE.fullmatch(self.reason_code) is None:
            raise ContextViolation("CTX-RESULT")


@dataclass(frozen=True, slots=True)
class CompiledContext:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if type(self.canonical_bytes) is not bytes or not self.canonical_bytes:
            raise ContextViolation("CTX-COMPILED")


@dataclass(frozen=True, slots=True)
class ContextResult:
    manifest_bytes: bytes
    compiled: CompiledContext
    items: tuple[ContextItemResult, ...]

    def __post_init__(self) -> None:
        if (
            type(self.manifest_bytes) is not bytes
            or not self.manifest_bytes
            or type(self.compiled) is not CompiledContext
            or type(self.items) is not tuple
            or any(type(item) is not ContextItemResult for item in self.items)
        ):
            raise ContextViolation("CTX-RESULT")


@runtime_checkable
class ContextCompiler(Protocol):
    def compile(self, request: ContextRequest) -> ContextResult:
        """Compile only the supplied immutable snapshot."""
        ...


EMBEDDING_DIMENSIONS = 1024
EMBEDDING_BINDING_ID = "armi.embedding.qwen3-0_6b-q8_0-local-1024.v1"
EMBEDDING_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0"
EMBEDDING_MODEL_REVISION = "370f27d7550e0def9b39c1f16d3fbaa13aa67728"
EMBEDDING_MODEL_SHA256 = (
    "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439"
)
EMBEDDING_QUERY_INSTRUCTION = (
    "Instruct: Given the current cognitive context, retrieve personally relevant "
    "memories and life materials that help understand or respond to it.\nQuery:"
)
EMBEDDING_QUERY_MAX_CHARS = 700
SEMANTIC_RECALL_PROFILE_ID = "armi.semantic-recall.hybrid-hnsw-gist-exact-rerank.v3"


class RecallStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NO_RELEVANT_RESULT = "no_relevant_result"


@dataclass(frozen=True, slots=True)
class EmbeddingBinding:
    provider: str
    model_id: str
    model_revision: str
    model_sha256: str
    model_binding: str
    dimensions: int
    timeout_seconds: int
    pooling: str
    normalization: str
    query_instruction: str
    retrieval_profile: str
    dense_ann_candidates: int
    dense_final_candidates: int
    hnsw_ef_search: int
    lexical_candidates: int
    lexical_final_candidates: int
    dense_min_similarity: float
    lexical_min_similarity: float
    fusion_rrf_k: int
    document_batch_size: int


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    vector: tuple[float, ...]
    provider_request_id: str | None
    input_tokens: int | None

    def __post_init__(self) -> None:
        if len(self.vector) != EMBEDDING_DIMENSIONS:
            raise ModelViolation("MODEL-EMBEDDING-DIMENSIONS")


@runtime_checkable
class EmbeddingPort(Protocol):
    async def embed_query(self, text: str) -> EmbeddingResponse: ...

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[EmbeddingResponse, ...]: ...

    async def close(self) -> None: ...


def load_embedding_binding(path: Path) -> EmbeddingBinding:
    try:
        value = cast(dict[str, object], load_yaml_file(path)["embedding"])
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    expected = {
        "provider": "local_llama_cpp",
        "model_id": EMBEDDING_MODEL_ID,
        "model_revision": EMBEDDING_MODEL_REVISION,
        "model_sha256": EMBEDDING_MODEL_SHA256,
        "model_binding": EMBEDDING_BINDING_ID,
        "version_policy": "fixed_revision_and_sha256",
        "dimensions": EMBEDDING_DIMENSIONS,
        "timeout_seconds": 10,
        "pooling": "last",
        "normalization": "l2",
        "query_instruction": EMBEDDING_QUERY_INSTRUCTION,
        "retrieval_profile": SEMANTIC_RECALL_PROFILE_ID,
        "dense_ann_candidates": 256,
        "dense_final_candidates": 32,
        "hnsw_ef_search": 256,
        "lexical_candidates": 128,
        "lexical_final_candidates": 32,
        "dense_min_similarity": 0.40,
        "lexical_min_similarity": 0.30,
        "fusion_rrf_k": 60,
        "document_batch_size": 8,
    }
    if value != expected:
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return EmbeddingBinding(
        provider=cast(str, value["provider"]),
        model_id=cast(str, value["model_id"]),
        model_revision=cast(str, value["model_revision"]),
        model_sha256=cast(str, value["model_sha256"]),
        model_binding=cast(str, value["model_binding"]),
        dimensions=cast(int, value["dimensions"]),
        timeout_seconds=cast(int, value["timeout_seconds"]),
        pooling=cast(str, value["pooling"]),
        normalization=cast(str, value["normalization"]),
        query_instruction=cast(str, value["query_instruction"]),
        retrieval_profile=cast(str, value["retrieval_profile"]),
        dense_ann_candidates=cast(int, value["dense_ann_candidates"]),
        dense_final_candidates=cast(int, value["dense_final_candidates"]),
        hnsw_ef_search=cast(int, value["hnsw_ef_search"]),
        lexical_candidates=cast(int, value["lexical_candidates"]),
        lexical_final_candidates=cast(int, value["lexical_final_candidates"]),
        dense_min_similarity=cast(float, value["dense_min_similarity"]),
        lexical_min_similarity=cast(float, value["lexical_min_similarity"]),
        fusion_rrf_k=cast(int, value["fusion_rrf_k"]),
        document_batch_size=cast(int, value["document_batch_size"]),
    )


@runtime_checkable
class ContextArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...

    async def retained_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef | None: ...


@runtime_checkable
class ContextWakeupPort(Protocol):
    def notify(self, channel: str) -> None: ...

    def version(self, channel: str) -> int: ...

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: asyncio.Event,
        timeout_seconds: float,
    ) -> int: ...


@runtime_checkable
class ContextRuntimePort(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def stop(self) -> None: ...

    async def select_once(self) -> CognitiveEpisodeId | None: ...

    async def run_selector(self) -> None: ...

    async def run_worker(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ContextDialogueItem:
    timeline_item_id: UUID
    source_version: int
    speaker: str
    text: str
    occurred_at: datetime
    modality: str
    speaker_label: str | None = None

    def __post_init__(self) -> None:
        _require_uuid7(self.timeline_item_id)
        if (
            type(self.source_version) is not int
            or self.source_version <= 0
            or self.speaker not in {"creator", "other_human", "armi"}
            or type(self.text) is not str
            or not self.text.strip()
            or len(self.text.encode("utf-8")) > 65536
            or type(self.occurred_at) is not datetime
            or self.modality not in {"text", "live_voice"}
            or (
                self.speaker_label is not None
                and (not self.speaker_label.strip() or len(self.speaker_label) > 256)
            )
        ):
            raise ContextViolation("CTX-DIALOGUE")


@runtime_checkable
class ContextDialogueReadPort(Protocol):
    async def recent_creator_dialogue(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None = None,
        before_time: datetime | None = None,
        limit: int = 8,
    ) -> tuple[ContextDialogueItem, ...]: ...

    async def recent_other_human_dialogue(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None = None,
        before_time: datetime | None = None,
        limit: int = 8,
    ) -> tuple[ContextDialogueItem, ...]: ...


@runtime_checkable
class ContextVoiceResponseReadPort(Protocol):
    async def completed_response_text(
        self, transaction: PostgreSQLTransaction, *, turn_id: UUID
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ContextExperienceState:
    experience_id: UUID
    fact_class: str
    first_person_gist: str
    occurred_at: datetime
    accepted_at: datetime
    source_perspective: str
    uncertainty: str | None
    maintenance_source: bool


@dataclass(frozen=True, slots=True)
class ContextEpisodeState:
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    mechanism_identity: str
    trace_id: TraceId
    life_query_intent_id: UUID | None = None
    life_query_result_artifact_id: UUID | None = None
    experience_context: tuple[ContextExperienceState, ...] = ()


@runtime_checkable
class ContextEpisodePort(Protocol):
    async def context_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> ContextEpisodeState: ...

    async def mark_context_prepared(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        manifest_artifact_id: UUID,
        compiled_artifact_id: UUID,
        context_digest: Digest,
    ) -> ContextEpisodeState: ...

    async def fail_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        error_code: str,
    ) -> ContextEpisodeState: ...


@dataclass(frozen=True, slots=True)
class ContextRuntimeSubjectSnapshot:
    subject_id: UUID
    subject_version: int
    state_epoch: int
    generation_id: UUID
    bundle_activation_id: UUID


@runtime_checkable
class ContextRuntimeSubjectPort(Protocol):
    async def current_subject(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> ContextRuntimeSubjectSnapshot: ...


@runtime_checkable
class ContextSelectionPort(Protocol):
    async def select_once(self) -> CognitiveEpisodeId | None: ...


@dataclass(frozen=True, slots=True)
class ContextModelReference:
    ordinal: int
    section: str
    item_kind: str


@dataclass(frozen=True, slots=True)
class ContextBudgetExclusion:
    ordinal: int
    section: str
    item_kind: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ContextCandidateBasisSnapshot:
    context_item_id: UUID
    basis: CandidateBasis


@runtime_checkable
class ContextCognitionReadPort(Protocol):
    async def model_references(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> tuple[
        tuple[ContextModelReference, ...], tuple[ContextBudgetExclusion, ...]
    ]: ...

    async def candidate_bases(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> tuple[ContextCandidateBasisSnapshot, ...]: ...


@runtime_checkable
class ContextEmbeddingRuntimePort(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def stop(self) -> None: ...

    async def run_worker(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ContextProjectionSourceRef:
    source_kind: str
    source_ref: UUID

    def __post_init__(self) -> None:
        _require_token(self.source_kind)
        _require_uuid7(self.source_ref)


@runtime_checkable
class ContextProjectionInvalidationPort(Protocol):
    async def invalidate(
        self,
        transaction: PostgreSQLTransaction,
        sources: tuple[ContextProjectionSourceRef, ...],
    ) -> None: ...


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ContextViolation("CTX-ID")


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ContextViolation("CTX-TOKEN")


__all__ = (
    "EMBEDDING_BINDING_ID",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_REVISION",
    "EMBEDDING_MODEL_SHA256",
    "EMBEDDING_QUERY_INSTRUCTION",
    "EMBEDDING_QUERY_MAX_CHARS",
    "SEMANTIC_RECALL_PROFILE_ID",
    "CognitiveEpisodeId",
    "CompiledContext",
    "ContextArtifactCatalogPort",
    "ContextBudgetExclusion",
    "ContextCandidateBasisSnapshot",
    "ContextCognitionReadPort",
    "ContextCompiler",
    "ContextDialogueItem",
    "ContextDialogueReadPort",
    "ContextEmbeddingRuntimePort",
    "ContextEpisodePort",
    "ContextEpisodeState",
    "ContextExperienceState",
    "ContextItemCandidate",
    "ContextItemDisposition",
    "ContextItemResult",
    "ContextLayer",
    "ContextModelReference",
    "ContextProjectionInvalidationPort",
    "ContextProjectionSourceRef",
    "ContextRequest",
    "ContextRequirement",
    "ContextResult",
    "ContextRuntimePort",
    "ContextRuntimeSubjectPort",
    "ContextRuntimeSubjectSnapshot",
    "ContextSection",
    "ContextSelectionPort",
    "ContextSourceIdentity",
    "ContextTrustClass",
    "ContextViolation",
    "ContextVoiceResponseReadPort",
    "ContextWakeupPort",
    "EmbeddingBinding",
    "EmbeddingPort",
    "EmbeddingResponse",
    "RecallStatus",
    "load_embedding_binding",
)
