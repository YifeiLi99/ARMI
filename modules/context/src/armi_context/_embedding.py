"""Fixed contracts for rebuildable Context semantic-recall projections."""

from __future__ import annotations

from .api import (
    EMBEDDING_BINDING_ID,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_MODEL_SHA256,
    EMBEDDING_QUERY_INSTRUCTION,
    EMBEDDING_QUERY_MAX_CHARS,
    SEMANTIC_RECALL_PROFILE_ID,
    load_embedding_binding,
)

LIFE_MATERIAL_CHUNK_TARGET = 600
LIFE_MATERIAL_CHUNK_CHARS = 800
LIFE_MATERIAL_CHUNK_OVERLAP = 80
RECALL_MIN_SIMILARITY = 0.30
RECALL_MIN_LEXICAL_SIMILARITY = 0.30
RECALL_RRF_K = 60
RECALL_DENSE_ANN_LIMIT = 256
RECALL_CANDIDATE_LIMIT = 32
RECALL_HNSW_EF_SEARCH = 256
RECALL_LEXICAL_CANDIDATE_LIMIT = 128
RECALL_MEMORY_LIMIT = 4
RECALL_MATERIAL_LIMIT = 2
QUERY_MAX_CHARS = EMBEDDING_QUERY_MAX_CHARS
DOCUMENT_BATCH_SIZE = 8


def chunk_life_material(text: str) -> tuple[str, ...]:
    if type(text) is not str or not text:
        return ()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ()
    paragraphs = tuple(
        part.strip() for part in normalized.split("\n\n") if part.strip()
    )
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > LIFE_MATERIAL_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            step = LIFE_MATERIAL_CHUNK_CHARS - LIFE_MATERIAL_CHUNK_OVERLAP
            for start in range(0, len(paragraph), step):
                remaining = len(paragraph) - start
                if start and remaining <= LIFE_MATERIAL_CHUNK_OVERLAP:
                    break
                chunks.append(paragraph[start : start + LIFE_MATERIAL_CHUNK_CHARS])
            continue
        combined = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(combined) > LIFE_MATERIAL_CHUNK_CHARS or (
            len(current) >= LIFE_MATERIAL_CHUNK_TARGET and current
        ):
            chunks.append(current)
            current = paragraph
        else:
            current = combined
    if current:
        chunks.append(current)
    return tuple(chunks)


def material_retrieval_text(title: str, material_kind: str, chunk: str) -> str:
    return f"Title: {title[:100]}\nType: {material_kind}\nContent: {chunk}"


__all__ = (
    "DOCUMENT_BATCH_SIZE",
    "EMBEDDING_BINDING_ID",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_REVISION",
    "EMBEDDING_MODEL_SHA256",
    "EMBEDDING_QUERY_INSTRUCTION",
    "QUERY_MAX_CHARS",
    "RECALL_CANDIDATE_LIMIT",
    "RECALL_DENSE_ANN_LIMIT",
    "RECALL_HNSW_EF_SEARCH",
    "RECALL_LEXICAL_CANDIDATE_LIMIT",
    "RECALL_MATERIAL_LIMIT",
    "RECALL_MEMORY_LIMIT",
    "RECALL_MIN_LEXICAL_SIMILARITY",
    "RECALL_MIN_SIMILARITY",
    "RECALL_RRF_K",
    "SEMANTIC_RECALL_PROFILE_ID",
    "chunk_life_material",
    "load_embedding_binding",
    "material_retrieval_text",
)
