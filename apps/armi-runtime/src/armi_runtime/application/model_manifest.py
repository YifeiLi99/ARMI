"""Strict shared shape of the model manifest consumed by model adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from armi_kernel import load_yaml_file
from pydantic import BaseModel, ConfigDict, Field

Positive = Annotated[int, Field(gt=0)]
NonNegative = Annotated[int, Field(ge=0)]


class ManifestSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PrimaryModelSettings(ManifestSection):
    provider: str
    api_base: str
    model_id: str
    version_policy: str
    profile: str
    request_contract_version: str
    response_contract_version: str
    response_model_identity_required: bool
    credential_identity: str
    credential_locator: str
    credential_purpose: str
    pricing_snapshot_id: str
    input_token_limit: Positive
    output_token_limit: Positive
    timeout_seconds: Positive
    input_microyuan_per_million: NonNegative
    output_microyuan_per_million: NonNegative
    attempt_cost_limit_microyuan: Positive


class VoiceModelSettings(ManifestSection):
    provider: str
    api_base: str
    model_id: str
    version_policy: str
    profile: str
    request_contract_version: str
    response_contract_version: str
    credential_identity: str
    credential_locator: str
    credential_purpose: str
    output_token_limit: Positive
    timeout_seconds: Positive
    thinking: Literal["disabled"]
    tools: Literal["disabled"]
    startup_compatibility_check: Literal["strict_minimal_json"]


class PurposeModelSettings(ManifestSection):
    profile: str
    response_contract_version: str
    output_token_limit: Positive


class EmbeddingModelSettings(ManifestSection):
    provider: str
    model_id: str
    model_revision: str
    model_sha256: str
    model_binding: str
    version_policy: str
    dimensions: Positive
    timeout_seconds: Positive
    pooling: str
    normalization: str
    query_instruction: str
    retrieval_profile: str
    dense_ann_candidates: Positive
    dense_final_candidates: Positive
    hnsw_ef_search: Positive
    lexical_candidates: Positive
    lexical_final_candidates: Positive
    dense_min_similarity: Annotated[float, Field(ge=0, le=1)]
    lexical_min_similarity: Annotated[float, Field(ge=0, le=1)]
    fusion_rrf_k: Positive
    document_batch_size: Positive


class RecognitionModelSettings(ManifestSection):
    api_base: str
    document_model_id: str
    image_model_id: str
    video_model_id: str
    output_token_limit: Positive
    image_output_token_limit: Positive
    sticker_output_token_limit: Positive
    timeout_seconds: Positive
    speech_submit_url: str
    speech_query_url: str
    speech_resource_id: str
    speech_model_name: str
    speech_model_version: str
    speech_timeout_seconds: Positive
    speech_poll_interval_seconds: Positive


class ModelManifest(ManifestSection):
    schema_version: Literal["armi.model-bindings.v2"]
    active_binding: str
    bindings: Annotated[list[PrimaryModelSettings], Field(min_length=1, max_length=1)]
    voice_binding: VoiceModelSettings
    purpose_profiles: dict[str, PurposeModelSettings]
    embedding: EmbeddingModelSettings
    external_content_recognition: RecognitionModelSettings


def load_model_manifest(path: Path) -> ModelManifest:
    """Validate shape here; each owner continues to enforce its semantic contract."""
    return ModelManifest.model_validate(load_yaml_file(path))


__all__ = ("ModelManifest", "load_model_manifest")
