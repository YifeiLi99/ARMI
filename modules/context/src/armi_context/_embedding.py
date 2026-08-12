"""Fixed contracts for rebuildable Context semantic-recall projections."""

from __future__ import annotations

from pathlib import Path

from armi_kernel import load_yaml_file
from armi_kernel.application import ModelViolation

from .api import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBinding,
    EmbeddingResponse,
    RecallStatus,
)

EMBEDDING_BINDING_ID = "armi.embedding.volcengine-ark-doubao-vision-250615-v1"
EMBEDDING_MODEL_ID = "doubao-embedding-vision-250615"
LIFE_MATERIAL_CHUNK_CHARS = 1500
LIFE_MATERIAL_CHUNK_OVERLAP = 150
RECALL_MIN_SIMILARITY = 0.60
RECALL_MEMORY_LIMIT = 4
RECALL_MATERIAL_LIMIT = 2


def load_embedding_binding(path: Path) -> EmbeddingBinding:
    manifest_path = path
    try:
        value = load_yaml_file(manifest_path)["embedding"]
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    expected = {
        "provider": "volcengine_ark",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "model_id": EMBEDDING_MODEL_ID,
        "model_binding": EMBEDDING_BINDING_ID,
        "version_policy": "fixed_model_id",
        "dimensions": EMBEDDING_DIMENSIONS,
        "timeout_seconds": 60,
        "credential_identity": "armi.model.ark-api-key.v1",
        "credential_locator": "model.ark_api_key",
        "credential_purpose": "model.embedding",
    }
    if value != expected:
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return EmbeddingBinding(
        provider=value["provider"],
        api_base=value["api_base"],
        model_id=value["model_id"],
        model_binding=value["model_binding"],
        dimensions=value["dimensions"],
        timeout_seconds=value["timeout_seconds"],
        credential_identity=value["credential_identity"],
        credential_locator=value["credential_locator"],
        credential_purpose=value["credential_purpose"],
    )


def chunk_life_material(text: str) -> tuple[str, ...]:
    if type(text) is not str or not text:
        return ()
    step = LIFE_MATERIAL_CHUNK_CHARS - LIFE_MATERIAL_CHUNK_OVERLAP
    return tuple(
        text[start : start + LIFE_MATERIAL_CHUNK_CHARS]
        for start in range(0, len(text), step)
        if text[start : start + LIFE_MATERIAL_CHUNK_CHARS]
    )


__all__ = (
    "EMBEDDING_BINDING_ID",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL_ID",
    "RECALL_MATERIAL_LIMIT",
    "RECALL_MEMORY_LIMIT",
    "RECALL_MIN_SIMILARITY",
    "EmbeddingBinding",
    "EmbeddingResponse",
    "RecallStatus",
    "chunk_life_material",
    "load_embedding_binding",
)
