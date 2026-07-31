"""Frozen S024 model binding, request, and candidate wire contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import ModelBinding, ModelRequest, ModelViolation
from armi_kernel.contracts import Digest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

MODEL_BINDING_VERSION = "armi.model-bindings.v1"
MODEL_REQUEST_VERSION = "armi.model-request.v1"
CANDIDATE_VERSION = "armi.cognition-candidate.v2"
ACTIVE_MODEL_ID = "doubao-seed-evolving"
ACTIVE_MODEL_ADAPTER = "armi.model-adapter.volcengine-ark-responses-v1"
ACTIVE_VERSION_POLICY = "provider_evolving_alias"

ProposalRef = Annotated[
    str,
    StringConstraints(pattern=r"^proposal:[1-9][0-9]{0,2}$", max_length=12),
]
ContextRef = Annotated[
    str,
    StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7),
]
UncertaintyRef = Annotated[
    str,
    StringConstraints(pattern=r"^uncertainty:[1-9][0-9]{0,2}$", max_length=18),
]
AtomicGroupRef = Annotated[
    str,
    StringConstraints(pattern=r"^group:[1-9][0-9]{0,2}$", max_length=9),
]
Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]
DigestValue = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$", max_length=71),
]
Uuid7Value = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        max_length=36,
    ),
]
FactClass = Literal[
    "objective_fact",
    "external_claim",
    "subjective_understanding",
    "inference",
    "unknown",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CandidateBase(_StrictModel):
    subject_version: Annotated[int, Field(ge=0)]
    state_epoch: Annotated[int, Field(ge=0)]
    bundle_activation_id: Uuid7Value
    context_digest: DigestValue


class CandidateUnderstanding(_StrictModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    fact_class: FactClass
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)


class SelfState(_StrictModel):
    schema_version: Literal["armi.self.v1"]
    identity_kind: Literal["electronic_person"]
    creator_role_awareness: Literal["unique_primary_creator"]
    name: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    self_description: (
        Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None
    )
    interests: tuple[Summary, ...] = Field(max_length=16)
    values: tuple[Summary, ...] = Field(max_length=16)
    preferences: tuple[Summary, ...] = Field(max_length=16)
    goals: tuple[Summary, ...] = Field(max_length=16)
    self_narrative: (
        Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None
    )
    tensions: tuple[Summary, ...] = Field(max_length=16)


class MindState(_StrictModel):
    schema_version: Literal["armi.mind.v1"]
    understanding: tuple[Summary, ...] = Field(max_length=16)
    attention: tuple[Summary, ...] = Field(max_length=16)
    emotions: tuple[Summary, ...] = Field(max_length=16)
    thoughts: tuple[Summary, ...] = Field(max_length=16)
    wishes: tuple[Summary, ...] = Field(max_length=16)
    motivations: tuple[Summary, ...] = Field(max_length=16)
    mood: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None


class LifeModeState(_StrictModel):
    schema_version: Literal["armi.life-mode.v1"]
    mode: Literal["awake"]
    active_activities: tuple[str, ...] = Field(max_length=0)


class ExperiencePayload(_StrictModel):
    proposal_kind: Literal["experiences"]
    fact_class: FactClass
    first_person_gist: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    source_perspective: Literal["creator_claim"]
    uncertainty: Summary | None
    privacy_scope: Literal["private"]


class ComponentChangePayload(_StrictModel):
    proposal_kind: Literal["component_changes"]
    fact_class: FactClass
    owner: Literal["self", "mind", "life_mode"]
    expected_version: Annotated[int, Field(gt=0)]
    next_state: SelfState | MindState | LifeModeState


class MemoryChangePayload(_StrictModel):
    proposal_kind: Literal["memory_changes"]
    fact_class: FactClass
    summary: Summary


class RelationshipChangePayload(_StrictModel):
    proposal_kind: Literal["relationship_changes"]
    fact_class: FactClass
    summary: Summary


class ActivityChangePayload(_StrictModel):
    proposal_kind: Literal["activity_changes"]
    fact_class: FactClass
    summary: Summary


class CapabilityRequestPayload(_StrictModel):
    proposal_kind: Literal["capability_requests"]
    fact_class: FactClass
    summary: Summary


class ActionIntentPayload(_StrictModel):
    proposal_kind: Literal["action_intents"]
    fact_class: FactClass
    summary: Summary


class ExperienceProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ExperiencePayload


class ComponentChangeProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ComponentChangePayload


class MemoryChangeProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: MemoryChangePayload


class RelationshipChangeProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: RelationshipChangePayload


class ActivityChangeProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ActivityChangePayload


class CapabilityRequestProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: CapabilityRequestPayload


class ActionIntentProposal(_StrictModel):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ActionIntentPayload


class CandidateUncertainty(_StrictModel):
    uncertainty_ref: UncertaintyRef
    basis_refs: tuple[ContextRef, ...] = Field(max_length=8)
    fact_class: Literal["unknown"]
    summary: Summary


class CognitionCandidate(_StrictModel):
    schema_version: Literal["armi.cognition-candidate.v2"]
    base: CandidateBase
    disposition: Literal[
        "change",
        "no_change",
        "defer",
        "decline",
        "need_information",
    ]
    understanding: CandidateUnderstanding
    experiences: tuple[ExperienceProposal, ...] = Field(max_length=4)
    component_changes: tuple[ComponentChangeProposal, ...] = Field(max_length=4)
    memory_changes: tuple[MemoryChangeProposal, ...] = Field(max_length=4)
    relationship_changes: tuple[RelationshipChangeProposal, ...] = Field(max_length=4)
    activity_changes: tuple[ActivityChangeProposal, ...] = Field(max_length=4)
    capability_requests: tuple[CapabilityRequestProposal, ...] = Field(max_length=4)
    action_intents: tuple[ActionIntentProposal, ...] = Field(max_length=4)
    uncertainties: tuple[CandidateUncertainty, ...] = Field(max_length=8)
    reason_summary: Summary


_CANDIDATE_ADAPTER = TypeAdapter(CognitionCandidate)


def candidate_schema() -> dict[str, Any]:
    return _CANDIDATE_ADAPTER.json_schema()


def parse_candidate(
    value: bytes,
    *,
    allowed_context_refs: frozenset[str],
) -> CognitionCandidate:
    try:
        candidate = _CANDIDATE_ADAPTER.validate_json(value, strict=True)
    except Exception:
        raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None
    proposals = (
        *candidate.experiences,
        *candidate.component_changes,
        *candidate.memory_changes,
        *candidate.relationship_changes,
        *candidate.activity_changes,
        *candidate.capability_requests,
        *candidate.action_intents,
    )
    if len(proposals) > 16:
        raise ModelViolation("MODEL-RESPONSE-LIMIT")
    proposal_refs = [proposal.proposal_ref for proposal in proposals]
    if len(proposal_refs) != len(set(proposal_refs)):
        raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    group_counts: dict[str, int] = {}
    for proposal in proposals:
        if not set(proposal.basis_refs).issubset(allowed_context_refs):
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
        group_counts[proposal.atomic_group_ref] = (
            group_counts.get(proposal.atomic_group_ref, 0) + 1
        )
    if any(count > 8 for count in group_counts.values()):
        raise ModelViolation("MODEL-RESPONSE-LIMIT")
    if not set(candidate.understanding.basis_refs).issubset(allowed_context_refs):
        raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    for uncertainty in candidate.uncertainties:
        if not set(uncertainty.basis_refs).issubset(allowed_context_refs):
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    return candidate


def load_active_binding(path: Path | None = None) -> ModelBinding:
    manifest_path = path or (
        Path(__file__).parent / "runtime_resources/model-bindings.manifest.json"
    )
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        binding = value["bindings"][0]
    except OSError, KeyError, TypeError, json.JSONDecodeError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    if (
        value.get("schema_version") != MODEL_BINDING_VERSION
        or value.get("active_binding") != ACTIVE_MODEL_ADAPTER
        or binding.get("model_id") != ACTIVE_MODEL_ID
        or binding.get("version_policy") != ACTIVE_VERSION_POLICY
        or binding.get("response_model_identity_required") is not True
        or len(value.get("bindings", ())) != 1
    ):
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return ModelBinding(
        provider=binding["provider"],
        api_base=binding["api_base"],
        model_id=binding["model_id"],
        version_policy=binding["version_policy"],
        response_model_identity_required=binding["response_model_identity_required"],
        profile=binding["profile"],
        request_contract_version=binding["request_contract_version"],
        response_contract_version=binding["response_contract_version"],
        pricing_snapshot_id=binding["pricing_snapshot_id"],
        credential_identity=binding["credential_identity"],
        input_token_limit=binding["input_token_limit"],
        output_token_limit=binding["output_token_limit"],
        timeout_seconds=binding["timeout_seconds"],
        max_attempts=binding["max_attempts"],
        input_microyuan_per_million=binding["input_microyuan_per_million"],
        output_microyuan_per_million=binding["output_microyuan_per_million"],
        attempt_cost_limit_microyuan=binding["attempt_cost_limit_microyuan"],
        episode_cost_limit_microyuan=binding["episode_cost_limit_microyuan"],
    )


def build_request_bytes(
    *,
    binding: ModelBinding,
    compiled_context: bytes,
    context_digest: Digest,
    base_subject_version: int,
    base_state_epoch: int,
    bundle_activation_id: UUID,
    included_context_refs: tuple[dict[str, object], ...],
) -> bytes:
    try:
        compiled_value = json.loads(compiled_context)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ModelViolation("MODEL-CONTEXT") from None
    value = {
        "schema_version": MODEL_REQUEST_VERSION,
        "binding": {
            "provider": binding.provider,
            "model_id": binding.model_id,
            "profile": binding.profile,
            "binding_digest": binding.digest.value,
        },
        "context_digest": context_digest.value,
        "candidate_base": {
            "subject_version": base_subject_version,
            "state_epoch": base_state_epoch,
            "bundle_activation_id": str(bundle_activation_id),
            "context_digest": context_digest.value,
        },
        "included_context_refs": list(included_context_refs),
        "compiled_context": compiled_value,
        "output_contract": {
            "schema_version": CANDIDATE_VERSION,
            "schema_digest": Digest.from_bytes(
                rfc8785.dumps(cast(Any, candidate_schema()))
            ).value,
        },
    }
    try:
        return rfc8785.dumps(cast(Any, value)) + b"\n"
    except TypeError, UnicodeEncodeError:
        raise ModelViolation("MODEL-REQUEST") from None


def checked_model_request(
    *,
    binding: ModelBinding,
    request_bytes: bytes,
    context_digest: Digest,
    input_tokens: int,
) -> ModelRequest:
    estimated = binding.estimate_cost_microyuan(
        input_tokens=input_tokens,
        output_tokens=binding.output_token_limit,
    )
    if (
        input_tokens > binding.input_token_limit
        or estimated > binding.attempt_cost_limit_microyuan
    ):
        raise ModelViolation("MODEL-BUDGET")
    return ModelRequest(
        request_bytes,
        Digest.from_bytes(request_bytes),
        context_digest,
        input_tokens,
        binding.output_token_limit,
    )


__all__ = (
    "ACTIVE_MODEL_ADAPTER",
    "ACTIVE_MODEL_ID",
    "ACTIVE_VERSION_POLICY",
    "CANDIDATE_VERSION",
    "MODEL_BINDING_VERSION",
    "MODEL_REQUEST_VERSION",
    "CognitionCandidate",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "load_active_binding",
    "parse_candidate",
)
