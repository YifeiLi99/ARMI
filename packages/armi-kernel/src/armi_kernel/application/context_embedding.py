"""Technology-neutral contracts for rebuildable Context embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model import ModelViolation

EMBEDDING_DIMENSIONS = 1024


class RecallStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NO_RELEVANT_RESULT = "no_relevant_result"


@dataclass(frozen=True, slots=True)
class EmbeddingBinding:
    provider: str
    api_base: str
    model_id: str
    model_binding: str
    dimensions: int
    timeout_seconds: int
    credential_identity: str
    credential_locator: str
    credential_purpose: str


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    vector: tuple[float, ...]
    provider_request_id: str | None
    input_tokens: int | None

    def __post_init__(self) -> None:
        if len(self.vector) != EMBEDDING_DIMENSIONS:
            raise ModelViolation("MODEL-EMBEDDING-DIMENSIONS")


__all__ = (
    "EMBEDDING_DIMENSIONS",
    "EmbeddingBinding",
    "EmbeddingResponse",
    "RecallStatus",
)
