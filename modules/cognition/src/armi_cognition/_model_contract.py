"""Frozen S024 model binding, request, and candidate wire contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast
from uuid import UUID

import rfc8785
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    ModelBinding,
    ModelRequest,
    ModelViolation,
    PriceCatalog,
    UsageQuantity,
    UsageUnit,
    estimate_cost,
)
from armi_kernel.contracts import NONBLANK_TEXT_PATTERN, Digest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from ._activity_internal_work_contract import (
    InternalWorkAbandonDecision,
    InternalWorkCompleteDecision,
    InternalWorkNoResultDecision,
    InternalWorkProgressDecision,
)
from ._autonomous_activity_contract import (
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    AutonomousActivityCandidate,
    AutonomousCodexDecision,
    AutonomousLifeQueryDecision,
    AutonomousTerminalDecision,
    AutonomousVisualObservationDecision,
    AutonomousWaitDecision,
    StartActivityDecision,
    autonomous_activity_candidate_schema,
    parse_autonomous_activity_candidate,
)
from ._creator_cognitive_act_contract import (
    CREATOR_COGNITIVE_ACT_VERSION,
    CREATOR_VOICE_ACT_VERSION,
    CreatorCognitiveActCandidate,
    creator_cognitive_act_schema,
    creator_voice_act_schema,
    parse_creator_cognitive_act,
    parse_creator_voice_act,
)
from ._focus.api import (
    ConcernChange,
)
from ._prompt_instructions import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    GENERIC_COGNITION_INSTRUCTIONS,
    MEMORY_MAINTENANCE_INSTRUCTIONS,
    SLEEP_DECISION_INSTRUCTIONS,
    SUBJECT_SELF_CHECK_INSTRUCTIONS,
    VISUAL_OBSERVATION_INSTRUCTIONS,
)

if TYPE_CHECKING:
    from ._reflection_contract import OwnerReflectionCandidate
from ._maintenance_contract import (
    MAINTENANCE_WORK_CANDIDATE_VERSION,
    MaintenanceWorkCandidate,
    MemoryMaintenanceChange,
    MemoryMaintenanceNoChange,
    SelfCheckIssueFound,
    SelfCheckNoIssue,
    maintenance_work_candidate_schema,
    parse_maintenance_work_candidate,
)
from ._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OtherHumanDialogueCandidate,
    parse_other_human_dialogue_candidate_value,
)
from ._other_human_contract import (
    candidate_schema as other_human_candidate_schema,
)
from ._sleep_contract import (
    SLEEP_DECISION_CANDIDATE_VERSION,
    SleepDecisionCandidate,
    parse_sleep_decision_candidate,
    sleep_decision_candidate_schema,
)
from ._strict_model_json import strict_model_value
from ._visual_observation_contract import (
    VISUAL_OBSERVATION_CANDIDATE_VERSION,
    VisualObservationCandidate,
    parse_visual_observation_candidate,
    visual_observation_candidate_schema,
)

MODEL_BINDING_VERSION = "armi.model-bindings"
MODEL_REQUEST_VERSION = "armi.model-request"
CANDIDATE_VERSION = "armi.cognition-candidate"
ACTIVE_MODEL_ID = "qwen3.8-flash"
ACTIVE_MODEL_ADAPTER = "armi.model-adapter.qwen-responses"
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
Summary = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN)
]
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


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CandidateBase(_StrictModel, frozen=True):
    subject_version: Annotated[int, Field(ge=0)]
    state_epoch: Annotated[int, Field(ge=0)]
    bundle_activation_id: Uuid7Value
    context_digest: DigestValue


class CandidateUnderstanding(_StrictModel, frozen=True):
    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN),
    ]
    fact_class: FactClass
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)


class SelfState(_StrictModel, frozen=True):
    schema_kind: Literal["armi.self"]
    identity_kind: Literal["electronic_person"]
    creator_role_awareness: Literal["unique_primary_creator"]
    name: (
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=128, pattern=NONBLANK_TEXT_PATTERN
            ),
        ]
        | None
    )
    self_description: (
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=2048, pattern=NONBLANK_TEXT_PATTERN
            ),
        ]
        | None
    )
    interests: tuple[Summary, ...] = Field(max_length=16)
    values: tuple[Summary, ...] = Field(max_length=16)
    preferences: tuple[Summary, ...] = Field(max_length=16)
    goals: tuple[Summary, ...] = Field(max_length=16)
    self_narrative: (
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=2048, pattern=NONBLANK_TEXT_PATTERN
            ),
        ]
        | None
    )
    tensions: tuple[Summary, ...] = Field(max_length=16)


class LifeModeState(_StrictModel, frozen=True):
    schema_kind: Literal["armi.life-mode"]
    mode: Literal["awake"]
    active_activities: tuple[str, ...] = Field(max_length=0)


class ExperiencePayload(_StrictModel, frozen=True):
    proposal_kind: Literal["experiences"]
    fact_class: FactClass
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN),
    ]
    source_perspective: Literal["creator_claim", "web_claim", "codex_observation"]
    uncertainty: Summary | None = None
    privacy_scope: Literal["private"]


class ComponentChangePayload(_StrictModel, frozen=True):
    proposal_kind: Literal["component_changes"]
    fact_class: FactClass
    owner: Literal["self", "life_mode"]
    expected_version: Annotated[int, Field(gt=0)]
    next_state: SelfState | LifeModeState


class SelfChangePayload(ComponentChangePayload, frozen=True):
    owner: Literal["self"]
    next_state: SelfState


class LifeModeChangePayload(ComponentChangePayload, frozen=True):
    owner: Literal["life_mode"]
    next_state: LifeModeState


type ComponentChangeWire = Annotated[
    SelfChangePayload | LifeModeChangePayload,
    Field(discriminator="owner"),
]


class MemoryChangePayload(_StrictModel, frozen=True):
    proposal_kind: Literal["memory_changes"]
    fact_class: FactClass
    summary: Summary


class RelationshipChangePayload(_StrictModel, frozen=True):
    proposal_kind: Literal["relationship_changes"]
    fact_class: FactClass
    summary: Summary


class ActivityChangePayload(_StrictModel, frozen=True):
    proposal_kind: Literal["activity_changes"]
    fact_class: FactClass
    summary: Summary


class RuntimeBoundCreatorReplyPayload(_StrictModel, frozen=True):
    """Reply choice carrying content but no authority-owned identities."""

    proposal_kind: Literal["action_choices"]
    action_kind: Literal["creator_reply"]
    fact_class: FactClass
    capability_kind: Literal["creator.scene.reply"]
    operation: Literal["send"]
    audience_scope: Literal["creator"]
    data_scope: Literal["creator_visible_response"]
    purpose: Literal["respond_to_creator"]
    media_type: Literal["text/plain"]
    content: Annotated[
        str,
        StringConstraints(
            min_length=1, max_length=65536, pattern=NONBLANK_TEXT_PATTERN
        ),
    ]


class FormalNoActionPayload(_StrictModel, frozen=True):
    proposal_kind: Literal["action_choices"]
    action_kind: Literal["formal_no_action"]
    fact_class: FactClass
    decision: Literal["decline", "no_action"]
    reason_class: Literal["subjective_refusal", "subjective_silence"]


class CodexDelegationPayload(_StrictModel, frozen=True):
    proposal_kind: Literal["action_choices"]
    action_kind: Literal["codex_delegation"]
    fact_class: Literal["subjective_understanding", "inference"]
    task_source_id: Uuid7Value
    task_manifest_digest: DigestValue
    capability_kind: Literal["codex.delegated-work"]
    operation: Literal["execute"]
    purpose: Literal["delegate_codex_work"]


type ActionChoicePayload = Annotated[
    RuntimeBoundCreatorReplyPayload | FormalNoActionPayload | CodexDelegationPayload,
    Field(discriminator="action_kind"),
]


class ExperienceProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ExperiencePayload


class ComponentChangeProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ComponentChangeWire


class MemoryChangeProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: MemoryChangePayload


class RelationshipChangeProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: RelationshipChangePayload


class ActivityChangeProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ActivityChangePayload


class ActionChoiceProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: ActionChoicePayload


class VisualObservationRequestPayload(_StrictModel, frozen=True):
    proposal_kind: Literal["visual_observation_requests"]
    fact_class: Literal["inference"]
    source_kind: Literal["camera", "screen"]


class VisualObservationRequestProposal(_StrictModel, frozen=True):
    proposal_ref: ProposalRef
    atomic_group_ref: AtomicGroupRef
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
    payload: VisualObservationRequestPayload


class CandidateUncertainty(_StrictModel, frozen=True):
    uncertainty_ref: UncertaintyRef
    basis_refs: tuple[ContextRef, ...] = Field(max_length=8)
    fact_class: Literal["unknown"]
    summary: Summary


class CognitionCandidate(_StrictModel, frozen=True):
    concern_changes: tuple[ConcernChange, ...] = Field(default=(), max_length=4)
    schema_kind: Literal["armi.cognition-candidate"]
    base: CandidateBase
    disposition: Literal[
        "change",
        "no_change",
        "defer",
        "decline",
        "no_action",
        "need_information",
    ]
    understanding: CandidateUnderstanding
    experiences: tuple[ExperienceProposal, ...] = Field(max_length=4)
    component_changes: tuple[ComponentChangeProposal, ...] = Field(max_length=4)
    memory_changes: tuple[MemoryChangeProposal, ...] = Field(max_length=4)
    relationship_changes: tuple[RelationshipChangeProposal, ...] = Field(max_length=4)
    activity_changes: tuple[ActivityChangeProposal, ...] = Field(max_length=4)
    action_choices: tuple[ActionChoiceProposal, ...] = Field(max_length=2)
    visual_observation_requests: tuple[VisualObservationRequestProposal, ...] = Field(
        default=(), max_length=1
    )
    uncertainties: tuple[CandidateUncertainty, ...] = Field(max_length=8)
    reason_summary: Summary


_CANDIDATE_ADAPTER = TypeAdapter(CognitionCandidate)


def candidate_schema(
    version: str = CANDIDATE_VERSION,
    *,
    purpose: str | None = None,
) -> dict[str, Any]:
    if version == "armi.owner-reflection-candidate":
        from ._reflection_contract import owner_reflection_schema

        return cast(
            dict[str, Any],
            owner_reflection_schema(
                target=None if purpose is None else purpose.removeprefix("reflect_")
            ),
        )
    if version == CREATOR_COGNITIVE_ACT_VERSION:
        return cast(dict[str, Any], creator_cognitive_act_schema())
    if version == CREATOR_VOICE_ACT_VERSION:
        return cast(dict[str, Any], creator_voice_act_schema())
    if version == MAINTENANCE_WORK_CANDIDATE_VERSION:
        return maintenance_work_candidate_schema(purpose=purpose)
    if version == SLEEP_DECISION_CANDIDATE_VERSION:
        return sleep_decision_candidate_schema()
    if version == AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION:
        return autonomous_activity_candidate_schema()
    if version == VISUAL_OBSERVATION_CANDIDATE_VERSION:
        return visual_observation_candidate_schema()
    if version == OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION:
        return other_human_candidate_schema(version)
    if version == CANDIDATE_VERSION:
        return _CANDIDATE_ADAPTER.json_schema()
    raise ModelViolation("MODEL-BINDING")


def parse_candidate(
    value: bytes | dict[str, Any],
    *,
    allowed_context_refs: frozenset[str],
    expected_version: str | None = None,
    purpose: str | None = None,
) -> (
    MaintenanceWorkCandidate
    | AutonomousActivityCandidate
    | SleepDecisionCandidate
    | CreatorCognitiveActCandidate
    | OwnerReflectionCandidate
    | OtherHumanDialogueCandidate
    | VisualObservationCandidate
    | CognitionCandidate
):
    try:
        raw: object = json.loads(value) if isinstance(value, bytes) else value
        candidate_object = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        if (
            candidate_object is not None
            and expected_version == CREATOR_COGNITIVE_ACT_VERSION
        ):
            candidate = parse_creator_cognitive_act(
                candidate_object,
                allowed_context_refs=allowed_context_refs,
            )
        elif (
            candidate_object is not None
            and expected_version == CREATOR_VOICE_ACT_VERSION
        ):
            candidate = parse_creator_voice_act(
                candidate_object,
                allowed_context_refs=allowed_context_refs,
            )
        elif (
            candidate_object is not None
            and expected_version == "armi.owner-reflection-candidate"
        ):
            from ._reflection_contract import parse_owner_reflection

            return parse_owner_reflection(
                candidate_object,
                allowed_context_refs=allowed_context_refs,
                target=None if purpose is None else purpose.removeprefix("reflect_"),
            )
        elif (
            candidate_object is not None
            and expected_version == MAINTENANCE_WORK_CANDIDATE_VERSION
        ):
            maintenance_value = dict(candidate_object)
            maintenance_value.pop("schema_kind", None)
            candidate = parse_maintenance_work_candidate(
                maintenance_value, purpose=purpose
            )
        elif (
            candidate_object is not None
            and expected_version == SLEEP_DECISION_CANDIDATE_VERSION
        ):
            sleep_value = dict(candidate_object)
            sleep_value.pop("schema_kind", None)
            candidate = parse_sleep_decision_candidate(sleep_value)
        elif (
            candidate_object is not None
            and expected_version == AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION
        ):
            autonomous_value = dict(candidate_object)
            autonomous_value.pop("schema_kind", None)
            candidate = parse_autonomous_activity_candidate(autonomous_value)
        elif (
            candidate_object is not None
            and expected_version == VISUAL_OBSERVATION_CANDIDATE_VERSION
        ):
            visual_value = dict(candidate_object)
            visual_value.pop("schema_kind", None)
            return parse_visual_observation_candidate(visual_value)
        elif (
            candidate_object is not None
            and expected_version == OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
        ):
            other_human_value = dict(candidate_object)
            other_human_value.pop("schema_kind", None)
            candidate = parse_other_human_dialogue_candidate_value(
                other_human_value,
                allowed_context_refs=allowed_context_refs,
                expected_version=expected_version,
            )
        elif expected_version in (None, CANDIDATE_VERSION):
            candidate = _CANDIDATE_ADAPTER.validate_python(
                strict_model_value(cast(object, raw)), strict=True
            )
        else:
            raise ModelViolation("MODEL-RESPONSE-SCHEMA")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ModelViolation,
        ValueError,
    ) as error:
        raise ModelViolation("MODEL-RESPONSE-SCHEMA") from error
    if isinstance(
        candidate, (CreatorCognitiveActCandidate, OtherHumanDialogueCandidate)
    ):
        return candidate
    appraisal = getattr(candidate, "appraisal", None)
    if appraisal is not None:
        appraisal_refs = set(appraisal.basis_refs)
        if appraisal.episode_ref is not None:
            appraisal_refs.add(appraisal.episode_ref)
        if not appraisal_refs.issubset(allowed_context_refs):
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    if isinstance(
        candidate,
        (
            MemoryMaintenanceNoChange,
            MemoryMaintenanceChange,
            SelfCheckNoIssue,
            SelfCheckIssueFound,
        ),
    ):
        refs = {
            value
            for value in (
                getattr(candidate, "memory_ref", None),
                getattr(candidate, "related_memory_ref", None),
            )
            if value is not None
        }
        if not refs.issubset(allowed_context_refs):
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
        return candidate
    if isinstance(
        candidate,
        (
            InternalWorkProgressDecision,
            InternalWorkCompleteDecision,
            InternalWorkAbandonDecision,
            InternalWorkNoResultDecision,
        ),
    ):
        material_change = getattr(candidate, "material_change", None)
        material_ref = getattr(material_change, "material_ref", None)
        if material_ref is not None and material_ref not in allowed_context_refs:
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
        return candidate
    if isinstance(candidate, SleepDecisionCandidate):
        return candidate
    if isinstance(candidate, StartActivityDecision):
        for text_value in (candidate.goal, candidate.next_step):
            try:
                encoded = text_value.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None
            if not encoded or b"\x00" in encoded or not text_value.strip():
                raise ModelViolation("MODEL-RESPONSE-LIMIT")
        return candidate
    if isinstance(
        candidate,
        (
            AutonomousTerminalDecision,
            AutonomousCodexDecision,
            AutonomousVisualObservationDecision,
            AutonomousLifeQueryDecision,
            AutonomousWaitDecision,
        ),
    ):
        return candidate
    proposals = (
        *candidate.experiences,
        *candidate.component_changes,
        *candidate.memory_changes,
        *candidate.relationship_changes,
        *candidate.activity_changes,
        *candidate.action_choices,
        *getattr(candidate, "visual_observation_requests", ()),
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
        if isinstance(proposal.payload, RuntimeBoundCreatorReplyPayload):
            try:
                encoded = proposal.payload.content.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None
            if (
                not encoded
                or len(encoded) > 65536
                or b"\x00" in encoded
                or not proposal.payload.content.strip()
            ):
                raise ModelViolation("MODEL-RESPONSE-LIMIT")
    if any(count > 8 for count in group_counts.values()):
        raise ModelViolation("MODEL-RESPONSE-LIMIT")
    if not set(candidate.understanding.basis_refs).issubset(allowed_context_refs):
        raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    for uncertainty in candidate.uncertainties:
        if not set(uncertainty.basis_refs).issubset(allowed_context_refs):
            raise ModelViolation("MODEL-RESPONSE-REFERENCE")
    return candidate


def load_active_binding(
    path: Path | None = None,
) -> ModelBinding:
    manifest_path = path or Path("configs/model-bindings.yaml")
    try:
        value = cast(dict[str, Any], load_yaml_file(manifest_path))
        binding = cast(list[dict[str, Any]], value["bindings"])[0]
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    if (
        value.get("schema_kind") != MODEL_BINDING_VERSION
        or not _supported_text_binding(value.get("active_binding"), binding)
        or binding.get("version_policy") != ACTIVE_VERSION_POLICY
        or binding.get("response_contract_kind") != CANDIDATE_VERSION
        or binding.get("response_model_identity_required") is not True
        or len(value.get("bindings", ())) != 1
        or value.get("purpose_profiles")
        != {
            "consider_creator_input": {
                "profile": "creator_cognitive_act",
                "response_contract_kind": CREATOR_COGNITIVE_ACT_VERSION,
                "output_token_limit": 2048,
            },
            "consider_codex_result": {
                "profile": "codex_result",
                "response_contract_kind": CREATOR_COGNITIVE_ACT_VERSION,
                "output_token_limit": 4096,
            },
            "consider_codex_task": {
                "profile": "codex_task",
                "response_contract_kind": CANDIDATE_VERSION,
                "output_token_limit": 1024,
            },
            "consider_life_query_result": {
                "profile": "creator_cognitive_act",
                "response_contract_kind": CREATOR_COGNITIVE_ACT_VERSION,
                "output_token_limit": 2048,
            },
            "consider_other_human_input": {
                "profile": "other_human_dialogue",
                "response_contract_kind": OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
                "output_token_limit": 2048,
            },
            "consider_autonomous_life": {
                "profile": "autonomous_activity",
                "response_contract_kind": AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
                "output_token_limit": 4096,
            },
            "consider_sleep": {
                "profile": "sleep_decision",
                "response_contract_kind": SLEEP_DECISION_CANDIDATE_VERSION,
                "output_token_limit": 256,
            },
            "consider_visual_observation": {
                "profile": "visual_observation",
                "response_contract_kind": VISUAL_OBSERVATION_CANDIDATE_VERSION,
                "output_token_limit": 768,
            },
            "consider_requested_visual_observation": {
                "profile": "creator_cognitive_act",
                "response_contract_kind": CREATOR_COGNITIVE_ACT_VERSION,
                "output_token_limit": 2048,
            },
            "maintain_subjective_memory": {
                "profile": "memory_maintenance",
                "response_contract_kind": MAINTENANCE_WORK_CANDIDATE_VERSION,
                "output_token_limit": 1024,
            },
            "perform_subject_self_check": {
                "profile": "subject_self_check",
                "response_contract_kind": MAINTENANCE_WORK_CANDIDATE_VERSION,
                "output_token_limit": 1024,
            },
            "reflect_self": {
                "profile": "reflect_self",
                "response_contract_kind": "armi.owner-reflection-candidate",
                "output_token_limit": 2048,
            },
            "reflect_focus": {
                "profile": "reflect_focus",
                "response_contract_kind": "armi.owner-reflection-candidate",
                "output_token_limit": 2048,
            },
            "reflect_prompt": {
                "profile": "reflect_prompt",
                "response_contract_kind": "armi.owner-reflection-candidate",
                "output_token_limit": 1024,
            },
        }
    ):
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return _binding_from_manifest(binding)


def _supported_text_binding(adapter: object, binding: dict[str, Any]) -> bool:
    provider = binding.get("provider")
    if not isinstance(provider, str) or not isinstance(binding.get("model_id"), str):
        return False
    identities = {
        "qwen": (
            "armi.model-adapter.qwen-responses",
            "model.qwen_api_key",
            "model.request.qwen",
            "armi.model.qwen-api-key.v1",
        ),
        "deepseek": (
            "armi.model-adapter.deepseek-responses",
            "model.deepseek_api_key",
            "model.request.deepseek",
            "armi.model.deepseek-api-key.v1",
        ),
    }
    models = {
        # Supported Responses models; backend candidate validation is shared.
        "qwen": {
            "qwen3.8-flash",
            "qwen3.8-max",
            "qwen3.7-flash",
            "qwen3.7-plus",
            "qwen3.7-max",
        },
        "deepseek": {"deepseek-flash", "deepseek-v4-pro"},
    }
    return (
        provider in identities
        and (
            adapter,
            binding.get("credential_locator"),
            binding.get("credential_purpose"),
            binding.get("credential_identity"),
        )
        == identities[provider]
        and binding.get("model_id") in models[provider]
    )


def load_purpose_binding(
    purpose: str,
    path: Path | None = None,
) -> ModelBinding:
    if type(purpose) is not str or not purpose:
        raise ModelViolation("MODEL-BINDING")
    manifest_path = path or Path("configs/model-bindings.yaml")
    try:
        value = cast(dict[str, Any], load_yaml_file(manifest_path))
        base = cast(list[dict[str, Any]], value["bindings"])[0]
        profile = cast(dict[str, dict[str, Any]], value["purpose_profiles"]).get(
            purpose
        )
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    load_active_binding(
        manifest_path,
    )
    if profile is None:
        raise ModelViolation("MODEL-BINDING")
    return _binding_from_manifest({**base, **profile})


def load_voice_binding(path: Path | None = None) -> ModelBinding:
    """Load the dedicated strict compact voice binding from the v2 manifest."""
    manifest_path = path or Path("configs/model-bindings.yaml")
    try:
        value = cast(dict[str, Any], load_yaml_file(manifest_path))
        base = cast(list[dict[str, Any]], value["bindings"])[0]
        voice = cast(dict[str, Any], value["voice_binding"])
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    if (
        value.get("schema_kind") != MODEL_BINDING_VERSION
        or voice.get("response_contract_kind") != CREATOR_VOICE_ACT_VERSION
        or voice.get("output_token_limit") != 512
        or voice.get("thinking") != "disabled"
        or voice.get("tools") != "disabled"
    ):
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return _binding_from_manifest({**base, **voice})


def _binding_from_manifest(binding: dict[str, Any]) -> ModelBinding:
    return ModelBinding(
        provider=binding["provider"],
        api_base=binding["api_base"],
        model_id=binding["model_id"],
        version_policy=binding["version_policy"],
        response_model_identity_required=binding["response_model_identity_required"],
        profile=binding["profile"],
        response_contract_kind=binding["response_contract_kind"],
        credential_identity=binding["credential_identity"],
        input_token_limit=binding["input_token_limit"],
        output_token_limit=binding["output_token_limit"],
        timeout_seconds=binding["timeout_seconds"],
        attempt_cost_limit_microyuan=binding["attempt_cost_limit_microyuan"],
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
    value: dict[str, object] = {
        "schema_kind": MODEL_REQUEST_VERSION,
        "binding": {
            "provider": binding.provider,
            "model_id": binding.model_id,
            "profile": binding.profile,
            "version_policy": binding.version_policy,
            "response_contract_kind": binding.response_contract_kind,
        },
        "context_digest": context_digest.value,
        "compiled_context": compiled_value,
        "output_contract": {
            "schema_kind": binding.response_contract_kind,
        },
    }
    value["candidate_base"] = {
        "subject_version": base_subject_version,
        "state_epoch": base_state_epoch,
        "bundle_activation_id": str(bundle_activation_id),
        "context_digest": context_digest.value,
    }
    value["included_context_refs"] = list(included_context_refs)
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
    prices: PriceCatalog,
) -> ModelRequest:
    estimate = estimate_cost(
        quantities=(
            UsageQuantity(UsageUnit.INPUT_TOKENS, input_tokens),
            UsageQuantity(UsageUnit.CACHED_INPUT_TOKENS, 0),
            UsageQuantity(UsageUnit.OUTPUT_TOKENS, binding.output_token_limit),
        ),
        required_units=(
            UsageUnit.INPUT_TOKENS,
            UsageUnit.CACHED_INPUT_TOKENS,
            UsageUnit.OUTPUT_TOKENS,
        ),
        snapshot=prices.select(
            provider=binding.provider,
            model=binding.model_id,
            service="generation",
            at=datetime.now(UTC),
        ),
    )
    if input_tokens > binding.input_token_limit or (
        estimate.known_microyuan is not None
        and estimate.known_microyuan > binding.attempt_cost_limit_microyuan
    ):
        raise ModelViolation("MODEL-BUDGET")
    return ModelRequest(
        request_bytes,
        context_digest,
        input_tokens,
        binding.output_token_limit,
    )


__all__ = (
    "ACTIVE_MODEL_ADAPTER",
    "ACTIVE_MODEL_ID",
    "ACTIVE_VERSION_POLICY",
    "AUTONOMOUS_ACTIVITY_INSTRUCTIONS",
    "CANDIDATE_VERSION",
    "GENERIC_COGNITION_INSTRUCTIONS",
    "MAINTENANCE_WORK_CANDIDATE_VERSION",
    "MEMORY_MAINTENANCE_INSTRUCTIONS",
    "MODEL_BINDING_VERSION",
    "MODEL_REQUEST_VERSION",
    "SLEEP_DECISION_CANDIDATE_VERSION",
    "SLEEP_DECISION_INSTRUCTIONS",
    "SUBJECT_SELF_CHECK_INSTRUCTIONS",
    "VISUAL_OBSERVATION_INSTRUCTIONS",
    "CodexDelegationPayload",
    "CognitionCandidate",
    "RuntimeBoundCreatorReplyPayload",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "load_active_binding",
    "load_purpose_binding",
    "load_voice_binding",
    "parse_candidate",
)
