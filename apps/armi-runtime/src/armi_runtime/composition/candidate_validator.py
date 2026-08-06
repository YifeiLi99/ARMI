"""Deterministic S025 candidate validation without authority to commit state."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ActivityAttentionDecisionKind,
    ActivityStatus,
    ActivityWaitingKind,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
    CandidateBasis,
    CandidateComponentDraft,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateLifeMaterialDraft,
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    CandidateOwner,
    CandidateRejection,
    CandidateRelationshipDraft,
    CandidateSleepDecisionDraft,
    CandidateSubjectPromptDraft,
    CandidateValidationId,
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateViolation,
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequestDraft,
    CodexDelegatedWorkScope,
    CodexDelegationDraft,
    CodexTaskSourceId,
    CreatorReplyDraft,
    CreatorSceneReplyScope,
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialRevisionKind,
    LifeMaterialStatus,
    MemoryAccessibility,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemorySourceKind,
    ModelViolation,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipCommitment,
    RelationshipCommitmentEvent,
    RelationshipCommitmentEventKind,
    RelationshipCommitmentStatus,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipIssue,
    RelationshipIssueKind,
    RelationshipIssueStatus,
    RelationshipPartyRole,
    RelationshipStatus,
    SleepDecisionKind,
    SubjectChangeSet,
    WebResearchRequestDraft,
)
from armi_kernel.contracts import Digest

from .activity_attention_candidate_contract import (
    ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    ActivityAttentionCandidate,
    AttentionPauseDecision,
    AttentionProgressDecision,
    AttentionSimpleDecision,
    AttentionTerminalDecision,
    AttentionWaitDecision,
)
from .autonomous_activity_candidate_contract import (
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    AutonomousTerminalDecision,
    StartActivityDecision,
)
from .dialogue_candidate_contract import (
    DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_GROWTH_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_GROWTH_WEB_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION,
    HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION,
    WEB_DIALOGUE_CANDIDATE_VERSION,
    CreatorDialogueCandidate,
    DialogueCommitmentChange,
    DialogueMaterialChange,
    DialogueMaterialChangeV7,
    DialogueMaterialContentChange,
    DialogueMaterialStateChange,
    DialogueMemoryChange,
    DialogueRelationshipChange,
    DialogueReplyDecision,
    DialogueReplyDecisionV5,
    DialogueReplyDecisionV6,
    DialogueReplyDecisionV7,
    DialogueReplyDecisionV8,
    DialogueReplyDecisionV9,
    DialogueReplyDecisionV10,
    DialogueReplyDecisionV11,
    DialogueReplyDecisionV12,
    DialogueReplyDecisionV13,
    DialogueReplyDecisionV14,
    DialogueReplyDecisionV16,
    DialogueTerminalDecision,
    DialogueTerminalDecisionV5,
    DialogueTerminalDecisionV6,
    DialogueTerminalDecisionV7,
    DialogueTerminalDecisionV8,
    DialogueTerminalDecisionV9,
    DialogueTerminalDecisionV10,
    DialogueTerminalDecisionV11,
    DialogueTerminalDecisionV12,
    DialogueTerminalDecisionV13,
    DialogueTerminalDecisionV14,
    DialogueTerminalDecisionV16,
    DialogueWebResearchDecision,
    DialogueWebResearchDecisionV8,
    DialogueWebResearchDecisionV10,
    DialogueWebResearchDecisionV12,
    DialogueWebResearchDecisionV14,
    DialogueWebResearchDecisionV16,
)
from .model_contract import (
    ActionChoiceProposal,
    CodexDelegationPayload,
    CognitionCandidate,
    CognitionCandidateV5,
    CognitionCandidateV6,
    CognitionCandidateV7,
    ComponentChangeProposal,
    CreatorReplyPayload,
    CreatorSceneReplyRequestPayload,
    ExperienceProposal,
    FormalNoActionPayload,
    MemoryChangeProposal,
    MindState,
    RuntimeBoundCreatorReplyPayload,
    SelfState,
    WebResearchRequestProposal,
    parse_candidate,
)
from .sleep_decision_candidate_contract import (
    SLEEP_DECISION_CANDIDATE_VERSION,
    SleepDecisionCandidate,
)

CANDIDATE_POLICY_VERSION = "armi.cognition-candidate-policy.v3"
CANDIDATE_VALIDATOR_IDENTITY = "armi.candidate-validator.deterministic-v1"
CHANGE_SET_VERSION = "armi.subject-change-set.v3"
WEB_CHANGE_SET_VERSION = "armi.subject-change-set.v4"
CODEX_CHANGE_SET_VERSION = "armi.subject-change-set.v5"
RUNTIME_BOUND_CHANGE_SET_VERSION = "armi.subject-change-set.v6"
ACTIVITY_CHANGE_SET_VERSION = "armi.subject-change-set.v7"
ACTIVITY_ATTENTION_CHANGE_SET_VERSION = "armi.subject-change-set.v8"
SLEEP_CHANGE_SET_VERSION = "armi.subject-change-set.v9"
MEMORY_CHANGE_SET_VERSION = "armi.subject-change-set.v10"
MEMORY_REVISION_CHANGE_SET_VERSION = "armi.subject-change-set.v11"
RELATIONSHIP_CHANGE_SET_VERSION = "armi.subject-change-set.v13"
MATERIAL_CHANGE_SET_VERSION = "armi.subject-change-set.v15"
PROMPT_CHANGE_SET_VERSION = "armi.subject-change-set.v16"
_CODEX_CAPABILITY_ID = UUID("01985d00-0000-7000-8000-000000000038")


@dataclass(frozen=True, slots=True)
class CandidateMemoryContext:
    memory_id: UUID
    current_revision_id: UUID
    head_version: int
    context_digest: Digest
    fact_class: CandidateFactClass
    source_kind: MemorySourceKind
    summary: str
    uncertainty: str | None
    accessibility: MemoryAccessibility

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID or value.version != 7
                for value in (self.memory_id, self.current_revision_id)
            )
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.context_digest) is not Digest
            or type(self.fact_class) is not CandidateFactClass
            or type(self.source_kind) is not MemorySourceKind
            or type(self.summary) is not str
            or not self.summary
            or type(self.accessibility) is not MemoryAccessibility
            or self.accessibility is MemoryAccessibility.FORGOTTEN
        ):
            raise CandidateViolation("CON-CANDIDATE-MEMORY-CONTEXT")


@dataclass(frozen=True, slots=True)
class CandidateRelationshipCommitmentContext:
    commitment: RelationshipCommitment
    context_digest: Digest | None

    def __post_init__(self) -> None:
        if type(self.commitment) is not RelationshipCommitment or (
            self.context_digest is not None and type(self.context_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-COMMITMENT-CONTEXT")


@dataclass(frozen=True, slots=True)
class CandidateRelationshipContext:
    relationship_id: UUID
    current_revision_id: UUID
    head_version: int
    context_digest: Digest
    facts: tuple[RelationshipFact, ...]
    interpretation: str
    boundaries: tuple[RelationshipBoundary, ...]
    status: RelationshipStatus
    commitments: tuple[CandidateRelationshipCommitmentContext, ...] = ()
    open_issues: tuple[RelationshipIssue, ...] = ()

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID or value.version != 7
                for value in (self.relationship_id, self.current_revision_id)
            )
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.context_digest) is not Digest
            or type(self.facts) is not tuple
            or not self.facts
            or any(type(value) is not RelationshipFact for value in self.facts)
            or not self.interpretation
            or type(self.boundaries) is not tuple
            or any(type(value) is not RelationshipBoundary for value in self.boundaries)
            or type(self.status) is not RelationshipStatus
            or type(self.commitments) is not tuple
            or len(self.commitments) > 16
            or any(
                type(value) is not CandidateRelationshipCommitmentContext
                for value in self.commitments
            )
            or len({value.commitment.commitment_id for value in self.commitments})
            != len(self.commitments)
            or type(self.open_issues) is not tuple
            or len(self.open_issues) > 32
            or any(type(value) is not RelationshipIssue for value in self.open_issues)
            or any(
                commitment_id
                not in {value.commitment.commitment_id for value in self.commitments}
                for issue in self.open_issues
                for commitment_id in issue.commitment_ids
            )
        ):
            raise CandidateViolation("CON-CANDIDATE-RELATIONSHIP-CONTEXT")


@dataclass(frozen=True, slots=True)
class CandidateLifeMaterialContext:
    material_id: UUID
    current_revision_id: UUID
    head_version: int
    context_digest: Digest
    body_digest: Digest
    owner_party_id: UUID
    material_kind: LifeMaterialKind
    title: str
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID or value.version != 7
                for value in (
                    self.material_id,
                    self.current_revision_id,
                    self.owner_party_id,
                )
            )
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.context_digest) is not Digest
            or type(self.body_digest) is not Digest
            or type(self.material_kind) is not LifeMaterialKind
            or type(self.title) is not str
            or not 1 <= len(self.title) <= 256
            or not self.title.strip()
            or "\x00" in self.title
            or type(self.metadata) is not tuple
            or len(self.metadata) > 32
            or any(
                type(key) is not str
                or type(value) is not str
                or "\x00" in key
                or "\x00" in value
                for key, value in self.metadata
            )
            or tuple(sorted(self.metadata)) != self.metadata
            or type(self.material_status) is not LifeMaterialStatus
            or type(self.privacy_status) is not LifeMaterialPrivacyStatus
            or self.privacy_status
            not in {
                LifeMaterialPrivacyStatus.CREATOR_VISIBLE,
                LifeMaterialPrivacyStatus.PRIVATE,
            }
        ):
            raise CandidateViolation("CON-CANDIDATE-MATERIAL-CONTEXT")


@dataclass(frozen=True, slots=True)
class DialogueBoundChanges:
    memory_revision: CandidateMemoryRevisionDraft | None = None
    relationship: CandidateRelationshipDraft | None = None
    material: CandidateLifeMaterialDraft | None = None
    prompt: CandidateSubjectPromptDraft | None = None


@dataclass(frozen=True, slots=True)
class CandidateSubjectPromptContext:
    prompt_document_id: UUID
    current_revision_id: UUID | None
    revision_no: int
    content_digest: Digest | None

    def __post_init__(self) -> None:
        if (
            type(self.prompt_document_id) is not UUID
            or self.prompt_document_id.version != 7
            or (
                self.current_revision_id is not None
                and (
                    type(self.current_revision_id) is not UUID
                    or self.current_revision_id.version != 7
                )
            )
            or type(self.revision_no) is not int
            or self.revision_no < 0
            or (self.current_revision_id is None) != (self.revision_no == 0)
            or (self.current_revision_id is None) != (self.content_digest is None)
            or (
                self.content_digest is not None
                and type(self.content_digest) is not Digest
            )
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-PROMPT-CONTEXT")


@dataclass(frozen=True, slots=True)
class CandidateValidationContext:
    subject_id: UUID
    generation_id: UUID
    episode_id: UUID
    model_attempt_id: UUID
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    scene_id: UUID | None
    creator_party_id: UUID | None
    current_components: tuple[tuple[CandidateOwner, int, bytes], ...]
    purpose: str = "consider_creator_input"
    web_search_active: bool = False
    codex_active: bool = False
    codex_task_sources: tuple[tuple[UUID, Digest, str], ...] = ()
    opportunity_id: UUID | None = None
    current_activity_id: UUID | None = None
    current_activity_revision_id: UUID | None = None
    current_activity_head_version: int | None = None
    current_activity_status: ActivityStatus | None = None
    resource_snapshot_digest: Digest | None = None
    current_memories: tuple[CandidateMemoryContext, ...] = ()
    subject_party_id: UUID | None = None
    current_relationship: CandidateRelationshipContext | None = None
    current_materials: tuple[CandidateLifeMaterialContext, ...] = ()
    current_subject_prompt: CandidateSubjectPromptContext | None = None
    candidate_contract_version: str | None = None

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (
                self.subject_id,
                self.generation_id,
                self.episode_id,
                self.model_attempt_id,
                self.bundle_activation_id,
            )
        ):
            raise CandidateViolation("CON-CANDIDATE-CONTEXT")
        for value in (
            self.scene_id,
            self.creator_party_id,
            self.opportunity_id,
            self.current_activity_id,
            self.current_activity_revision_id,
        ):
            if value is not None and (type(value) is not UUID or value.version != 7):
                raise CandidateViolation("CON-CANDIDATE-CONTEXT")
        if (
            type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-CONTEXT")
        activity_values = (
            self.current_activity_id,
            self.current_activity_revision_id,
            self.current_activity_head_version,
            self.current_activity_status,
            self.resource_snapshot_digest,
        )
        if any(value is not None for value in activity_values) and (
            self.current_activity_id is None
            or self.current_activity_revision_id is None
            or type(self.current_activity_head_version) is not int
            or self.current_activity_head_version <= 0
            or type(self.current_activity_status) is not ActivityStatus
            or type(self.resource_snapshot_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-CONTEXT")
        if type(self.current_memories) is not tuple or any(
            type(value) is not CandidateMemoryContext for value in self.current_memories
        ):
            raise CandidateViolation("CON-CANDIDATE-MEMORY-CONTEXT")
        if self.subject_party_id is not None and (
            type(self.subject_party_id) is not UUID
            or self.subject_party_id.version != 7
        ):
            raise CandidateViolation("CON-CANDIDATE-RELATIONSHIP-CONTEXT")
        if self.current_relationship is not None and (
            type(self.current_relationship) is not CandidateRelationshipContext
            or self.subject_party_id is None
            or self.creator_party_id is None
        ):
            raise CandidateViolation("CON-CANDIDATE-RELATIONSHIP-CONTEXT")
        if type(self.current_materials) is not tuple or any(
            type(value) is not CandidateLifeMaterialContext
            for value in self.current_materials
        ):
            raise CandidateViolation("CON-CANDIDATE-MATERIAL-CONTEXT")
        if (
            self.current_subject_prompt is not None
            and type(self.current_subject_prompt) is not CandidateSubjectPromptContext
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-PROMPT-CONTEXT")
        if self.candidate_contract_version is not None and (
            type(self.candidate_contract_version) is not str
            or not self.candidate_contract_version
        ):
            raise CandidateViolation("CON-CANDIDATE-CONTEXT")


class DeterministicCandidateValidator:
    """Validate candidate v4 into a canonical, not-yet-effective change set."""

    __slots__ = ("_context",)

    def __init__(self, context: CandidateValidationContext) -> None:
        self._context = context

    def validate(
        self,
        candidate_bytes: bytes,
        *,
        bases: tuple[CandidateBasis, ...],
    ) -> CandidateValidationResult:
        if type(candidate_bytes) is not bytes or not candidate_bytes:
            raise CandidateViolation("CANDIDATE-INPUT")
        basis_by_ref = {f"ctx:{basis.ordinal}": basis for basis in bases}
        if len(basis_by_ref) != len(bases):
            raise CandidateViolation("CANDIDATE-BASIS-DUPLICATE")
        try:
            parsed_candidate = parse_candidate(
                candidate_bytes,
                allowed_context_refs=frozenset(basis_by_ref),
                expected_version=(
                    ACTIVITY_ATTENTION_CANDIDATE_VERSION
                    if self._context.purpose == "consider_activity_attention"
                    else AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION
                    if self._context.purpose == "consider_autonomous_life"
                    else SLEEP_DECISION_CANDIDATE_VERSION
                    if self._context.purpose == "consider_sleep"
                    else self._context.candidate_contract_version
                    if self._context.purpose == "consider_creator_input"
                    else None
                ),
            )
        except ModelViolation:
            try:
                raw = cast(dict[str, Any], json.loads(candidate_bytes))
            except UnicodeDecodeError, json.JSONDecodeError:
                raw = None
            code = (
                "CANDIDATE-CONTRACT-OBSOLETE"
                if isinstance(raw, dict)
                and raw.get("schema_version")
                in {
                    "armi.cognition-candidate.v1",
                    "armi.cognition-candidate.v2",
                    "armi.cognition-candidate.v3",
                }
                else "CANDIDATE-CONTRACT"
            )
            return _rejected(code)
        candidate_digest = Digest.from_bytes(
            rfc8785.dumps(cast(Any, parsed_candidate.model_dump(mode="json")))
        )
        if isinstance(parsed_candidate, SleepDecisionCandidate):
            return self._validate_sleep(
                parsed_candidate,
                bases=bases,
                candidate_digest=candidate_digest,
            )
        if isinstance(
            parsed_candidate,
            (
                AttentionSimpleDecision,
                AttentionProgressDecision,
                AttentionWaitDecision,
                AttentionPauseDecision,
                AttentionTerminalDecision,
            ),
        ):
            return self._validate_attention(
                parsed_candidate,
                bases=bases,
                candidate_digest=candidate_digest,
            )
        if isinstance(
            parsed_candidate,
            (StartActivityDecision, AutonomousTerminalDecision),
        ):
            return self._validate_autonomous(
                parsed_candidate,
                bases=bases,
                candidate_digest=candidate_digest,
            )
        if self._context.scene_id is None or self._context.creator_party_id is None:
            return _rejected("CANDIDATE-SCENE-CONTEXT")
        source_version = parsed_candidate.schema_version
        dialogue_bound_changes: DialogueBoundChanges | None = None
        if isinstance(parsed_candidate, CreatorDialogueCandidate):
            candidate, dialogue_bound_changes, expansion_error = (
                _expand_dialogue_candidate(
                    parsed_candidate,
                    bases=bases,
                    context=self._context,
                )
            )
            if candidate is None:
                return _rejected(expansion_error or "CANDIDATE-CONTRACT")
        else:
            candidate = parsed_candidate
        if not self._base_matches(candidate):
            return _rejected("CANDIDATE-BASE-MISMATCH")
        if not _fact_supported(
            candidate.understanding.fact_class,
            tuple(basis_by_ref[ref] for ref in candidate.understanding.basis_refs),
        ):
            return _rejected("CANDIDATE-FACT-CLASS")

        proposals = _all_proposals(candidate)
        formal_no_action = tuple(
            proposal
            for owner, proposal in proposals
            if owner is CandidateOwner.ACTION
            and isinstance(proposal.payload, FormalNoActionPayload)
        )
        if candidate.disposition == "change" and formal_no_action:
            return _rejected("CANDIDATE-DISPOSITION")
        if candidate.disposition != "change" and any(
            owner is not CandidateOwner.ACTION
            or not isinstance(proposal.payload, FormalNoActionPayload)
            for owner, proposal in proposals
        ):
            return _rejected("CANDIDATE-DISPOSITION")
        if candidate.disposition in {"decline", "no_action"}:
            if (
                len(formal_no_action) != 1
                or formal_no_action[0].payload.decision != candidate.disposition
            ):
                return _rejected("CANDIDATE-DISPOSITION")
        elif formal_no_action:
            return _rejected("CANDIDATE-DISPOSITION")

        component_state = {
            owner: (version, canonical)
            for owner, version, canonical in self._context.current_components
        }
        accepted: dict[
            str,
            CandidateExperienceDraft
            | CandidateMemoryDraft
            | CandidateMemoryRevisionDraft
            | CandidateRelationshipDraft
            | CandidateLifeMaterialDraft
            | CandidateSubjectPromptDraft
            | CandidateComponentDraft
            | CapabilityRequestDraft
            | CreatorReplyDraft
            | FormalNoActionDraft
            | WebResearchRequestDraft
            | CodexDelegationDraft,
        ] = {}
        rejected: dict[str, CandidateRejection] = {}
        group_members: dict[str, list[str]] = defaultdict(list)
        group_experiences: set[str] = set()

        for owner, proposal in proposals:
            group_members[proposal.atomic_group_ref].append(proposal.proposal_ref)
            proposal_bases = tuple(basis_by_ref[ref] for ref in proposal.basis_refs)
            failure = _basis_failure(owner, proposal_bases, proposal.payload.fact_class)
            if failure is None and owner is CandidateOwner.EXPERIENCE:
                experience = cast(ExperienceProposal, proposal)
                expected_perspective = (
                    "web_claim"
                    if self._context.purpose == "consider_web_evidence"
                    else "codex_observation"
                    if self._context.purpose == "consider_codex_result"
                    else "creator_claim"
                )
                if experience.payload.source_perspective != expected_perspective:
                    failure = "CANDIDATE-EXPERIENCE-SOURCE"
            if failure is None and owner is CandidateOwner.EXPERIENCE:
                experience = cast(ExperienceProposal, proposal)
                accepted[proposal.proposal_ref] = CandidateExperienceDraft(
                    proposal.proposal_ref,
                    proposal.atomic_group_ref,
                    tuple(basis.ordinal for basis in proposal_bases),
                    CandidateFactClass(experience.payload.fact_class),
                    experience.payload.first_person_gist,
                    experience.payload.uncertainty,
                    experience.payload.privacy_scope,
                )
                group_experiences.add(proposal.atomic_group_ref)
                continue
            if failure is None and owner is CandidateOwner.MEMORY:
                memory = cast(MemoryChangeProposal, proposal)
                source_experiences = tuple(
                    value
                    for value in accepted.values()
                    if isinstance(value, CandidateExperienceDraft)
                    and value.atomic_group_ref == proposal.atomic_group_ref
                )
                if len(source_experiences) != 1:
                    failure = "CANDIDATE-MEMORY-EXPERIENCE"
                elif (
                    source_experiences[0].fact_class.value != memory.payload.fact_class
                ):
                    failure = "CANDIDATE-MEMORY-SOURCE"
                else:
                    source = source_experiences[0]
                    accepted[proposal.proposal_ref] = CandidateMemoryDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        CandidateFactClass(memory.payload.fact_class),
                        source.proposal_ref,
                        _memory_source_kind(
                            CandidateFactClass(memory.payload.fact_class),
                            purpose=self._context.purpose,
                        ),
                        memory.payload.summary,
                    )
                    continue
            if failure is None and owner in {
                CandidateOwner.SELF,
                CandidateOwner.MIND,
                CandidateOwner.LIFE_MODE,
            }:
                component = cast(ComponentChangeProposal, proposal)
                failure = _component_failure(component, proposal_bases, component_state)
                if failure is None:
                    next_bytes = rfc8785.dumps(
                        cast(Any, component.payload.next_state.model_dump(mode="json"))
                    )
                    accepted[proposal.proposal_ref] = CandidateComponentDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        CandidateFactClass(component.payload.fact_class),
                        owner,
                        component.payload.expected_version,
                        next_bytes,
                        Digest.from_bytes(next_bytes),
                    )
                    continue
            if failure is None and owner is CandidateOwner.CAPABILITY:
                capability = proposal
                failure = _capability_failure(
                    capability,
                    proposal_bases,
                    context=self._context,
                )
                if failure is None:
                    payload = capability.payload
                    scope = (
                        CreatorSceneReplyScope(
                            self._context.subject_id,
                            self._context.scene_id,
                            self._context.creator_party_id,
                            payload.valid_for_seconds,
                            payload.max_uses,
                            payload.max_payload_bytes,
                        )
                        if payload.capability_kind == "creator.scene.reply"
                        else CodexDelegatedWorkScope(payload.valid_for_seconds)
                    )
                    accepted[proposal.proposal_ref] = CapabilityRequestDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        CapabilityKind(payload.capability_kind),
                        CapabilityOperation(payload.operation),
                        scope,
                    )
                    continue
            if failure is None and owner is CandidateOwner.ACTION:
                action = cast(ActionChoiceProposal, proposal)
                failure = _action_failure(action, proposal_bases, context=self._context)
                if failure is None and isinstance(
                    action.payload,
                    (CreatorReplyPayload, RuntimeBoundCreatorReplyPayload),
                ):
                    content = action.payload.content.encode("utf-8", errors="strict")
                    accepted[proposal.proposal_ref] = CreatorReplyDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        self._context.subject_id,
                        self._context.scene_id,
                        self._context.creator_party_id,
                        content,
                        Digest.from_bytes(content),
                    )
                    continue
                if failure is None and isinstance(
                    action.payload, FormalNoActionPayload
                ):
                    accepted[proposal.proposal_ref] = FormalNoActionDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        FormalNoActionKind(action.payload.decision),
                        FormalNoActionReason(action.payload.reason_class),
                    )
                    continue
            if failure is None and owner is CandidateOwner.WEB_RESEARCH:
                research = cast(WebResearchRequestProposal, proposal)
                failure = _web_research_failure(
                    research,
                    proposal_bases,
                    active=self._context.web_search_active,
                    purpose=self._context.purpose,
                )
                if failure is None:
                    query_bytes = research.payload.query.encode(
                        "utf-8", errors="strict"
                    )
                    accepted[proposal.proposal_ref] = WebResearchRequestDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        query_bytes,
                        Digest.from_bytes(query_bytes),
                    )
                    continue
            if failure is None and owner is CandidateOwner.CODEX_DELEGATION:
                action = cast(ActionChoiceProposal, proposal)
                payload = cast(CodexDelegationPayload, action.payload)
                failure = _codex_delegation_failure(
                    payload,
                    proposal_bases,
                    context=self._context,
                )
                if failure is None:
                    accepted[proposal.proposal_ref] = CodexDelegationDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        CodexTaskSourceId(UUID(payload.task_source_id)),
                        Digest(payload.task_manifest_digest),
                        payload.validator_id,
                    )
                    continue
            if failure is None:
                failure = "CANDIDATE-OWNER-NOT-ACTIVE"
            rejected[proposal.proposal_ref] = CandidateRejection(
                proposal.proposal_ref,
                proposal.atomic_group_ref,
                tuple(basis.ordinal for basis in proposal_bases),
                CandidateFactClass(proposal.payload.fact_class),
                owner,
                failure,
            )

        if (
            dialogue_bound_changes is not None
            and dialogue_bound_changes.memory_revision is not None
        ):
            memory_revision = dialogue_bound_changes.memory_revision
            group_members[memory_revision.atomic_group_ref].append(
                memory_revision.proposal_ref
            )
            accepted[memory_revision.proposal_ref] = memory_revision
        if (
            dialogue_bound_changes is not None
            and dialogue_bound_changes.relationship is not None
        ):
            relationship = dialogue_bound_changes.relationship
            group_members[relationship.atomic_group_ref].append(
                relationship.proposal_ref
            )
            accepted[relationship.proposal_ref] = relationship
        if (
            dialogue_bound_changes is not None
            and dialogue_bound_changes.material is not None
        ):
            material = dialogue_bound_changes.material
            group_members[material.atomic_group_ref].append(material.proposal_ref)
            accepted[material.proposal_ref] = material
        if (
            dialogue_bound_changes is not None
            and dialogue_bound_changes.prompt is not None
        ):
            prompt = dialogue_bound_changes.prompt
            group_members[prompt.atomic_group_ref].append(prompt.proposal_ref)
            accepted[prompt.proposal_ref] = prompt

        for proposal_ref, draft in tuple(accepted.items()):
            if (
                isinstance(
                    draft, (CandidateComponentDraft, CandidateSubjectPromptDraft)
                )
                and draft.atomic_group_ref not in group_experiences
            ):
                rejected[proposal_ref] = CandidateRejection(
                    proposal_ref,
                    draft.atomic_group_ref,
                    draft.basis_ordinals,
                    draft.fact_class,
                    _draft_owner(draft),
                    "CANDIDATE-EXPERIENCE-REQUIRED",
                )
                accepted.pop(proposal_ref)

        has_codex_request = any(
            isinstance(value, CapabilityRequestDraft)
            and isinstance(value.scope, CodexDelegatedWorkScope)
            for value in accepted.values()
        )
        for proposal_ref, draft in tuple(accepted.items()):
            if isinstance(draft, CodexDelegationDraft) and not has_codex_request:
                rejected[proposal_ref] = CandidateRejection(
                    proposal_ref,
                    draft.atomic_group_ref,
                    draft.basis_ordinals,
                    CandidateFactClass.INFERENCE,
                    CandidateOwner.CODEX_DELEGATION,
                    "CANDIDATE-CODEX-CAPABILITY-REQUEST",
                )
                accepted.pop(proposal_ref)

        failed_groups = {rejection.atomic_group_ref for rejection in rejected.values()}
        for group in failed_groups:
            for proposal_ref in group_members[group]:
                draft = accepted.pop(proposal_ref, None)
                if draft is not None:
                    rejected[proposal_ref] = CandidateRejection(
                        proposal_ref,
                        group,
                        draft.basis_ordinals,
                        _draft_fact_class(draft),
                        _draft_owner(draft),
                        "CANDIDATE-ATOMIC-GROUP",
                    )

        if candidate.disposition == "change" and not accepted:
            return CandidateValidationResult(
                CandidateValidationId(uuid7()),
                CandidateValidationStatus.REJECTED,
                None,
                0,
                len(rejected),
                _primary_rejection(rejected),
            )

        experiences = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateExperienceDraft)
        )
        components = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateComponentDraft)
        )
        memories = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateMemoryDraft)
        )
        memory_revisions = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateMemoryRevisionDraft)
        )
        relationships = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateRelationshipDraft)
        )
        materials = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateLifeMaterialDraft)
        )
        prompts = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CandidateSubjectPromptDraft)
        )
        capability_requests = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CapabilityRequestDraft)
        )
        action_choices = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, (CreatorReplyDraft, FormalNoActionDraft))
        )
        web_research_requests = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, WebResearchRequestDraft)
        )
        codex_delegations = tuple(
            value
            for _, value in sorted(accepted.items())
            if isinstance(value, CodexDelegationDraft)
        )
        rejections = tuple(value for _, value in sorted(rejected.items()))
        disposition = CandidateDisposition(candidate.disposition)
        change_set_version = (
            PROMPT_CHANGE_SET_VERSION
            if prompts
            else MATERIAL_CHANGE_SET_VERSION
            if materials
            else RELATIONSHIP_CHANGE_SET_VERSION
            if relationships
            else MEMORY_REVISION_CHANGE_SET_VERSION
            if memory_revisions
            else MEMORY_CHANGE_SET_VERSION
            if memories
            else WEB_CHANGE_SET_VERSION
            if source_version
            in {
                HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_GROWTH_WEB_DIALOGUE_CANDIDATE_VERSION,
                WEB_DIALOGUE_CANDIDATE_VERSION,
            }
            and web_research_requests
            else RUNTIME_BOUND_CHANGE_SET_VERSION
            if source_version
            in {
                "armi.cognition-candidate.v7",
                HISTORICAL_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_GROWTH_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_GROWTH_WEB_DIALOGUE_CANDIDATE_VERSION,
                DIALOGUE_CANDIDATE_VERSION,
                WEB_DIALOGUE_CANDIDATE_VERSION,
            }
            else CODEX_CHANGE_SET_VERSION
            if source_version == "armi.cognition-candidate.v6"
            else WEB_CHANGE_SET_VERSION
            if source_version == "armi.cognition-candidate.v5"
            else CHANGE_SET_VERSION
        )
        change_set_value = {
            "schema_version": change_set_version,
            "subject_id": str(self._context.subject_id),
            "generation_id": str(self._context.generation_id),
            "episode_id": str(self._context.episode_id),
            "model_attempt_id": str(self._context.model_attempt_id),
            "base": {
                "subject_version": self._context.base_subject_version,
                "state_epoch": self._context.base_state_epoch,
                "bundle_activation_id": str(self._context.bundle_activation_id),
                "context_digest": self._context.context_digest.value,
            },
            "candidate_digest": candidate_digest.value,
            "disposition": disposition.value,
            "experiences": [_experience_wire(item) for item in experiences],
            "components": [_component_wire(item) for item in components],
            "capability_requests": [
                _capability_wire(item) for item in capability_requests
            ],
            "action_choices": [_action_wire(item) for item in action_choices],
            "rejections": [_rejection_wire(item) for item in rejections],
        }
        if change_set_version in {
            MEMORY_CHANGE_SET_VERSION,
            MEMORY_REVISION_CHANGE_SET_VERSION,
            RELATIONSHIP_CHANGE_SET_VERSION,
            MATERIAL_CHANGE_SET_VERSION,
            PROMPT_CHANGE_SET_VERSION,
        }:
            change_set_value["memories"] = [_memory_wire(item) for item in memories]
        if change_set_version in {
            MEMORY_REVISION_CHANGE_SET_VERSION,
            RELATIONSHIP_CHANGE_SET_VERSION,
            MATERIAL_CHANGE_SET_VERSION,
            PROMPT_CHANGE_SET_VERSION,
        }:
            change_set_value["memory_revisions"] = [
                _memory_revision_wire(item) for item in memory_revisions
            ]
        if change_set_version in {
            RELATIONSHIP_CHANGE_SET_VERSION,
            MATERIAL_CHANGE_SET_VERSION,
            PROMPT_CHANGE_SET_VERSION,
        }:
            change_set_value["relationships"] = [
                _relationship_wire(item) for item in relationships
            ]
        if change_set_version in {
            MATERIAL_CHANGE_SET_VERSION,
            PROMPT_CHANGE_SET_VERSION,
        }:
            change_set_value["materials"] = [_material_wire(item) for item in materials]
        if change_set_version == PROMPT_CHANGE_SET_VERSION:
            change_set_value["prompts"] = [_prompt_wire(item) for item in prompts]
        if change_set_version in {
            MEMORY_CHANGE_SET_VERSION,
            MEMORY_REVISION_CHANGE_SET_VERSION,
            RELATIONSHIP_CHANGE_SET_VERSION,
            MATERIAL_CHANGE_SET_VERSION,
            PROMPT_CHANGE_SET_VERSION,
        } or source_version in {
            "armi.cognition-candidate.v5",
            HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION,
            HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION,
            HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION,
            HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION,
            HISTORICAL_GROWTH_WEB_DIALOGUE_CANDIDATE_VERSION,
            WEB_DIALOGUE_CANDIDATE_VERSION,
        }:
            change_set_value["web_research_requests"] = [
                _web_research_wire(item) for item in web_research_requests
            ]
        if (
            change_set_version
            in {
                MEMORY_CHANGE_SET_VERSION,
                MEMORY_REVISION_CHANGE_SET_VERSION,
                RELATIONSHIP_CHANGE_SET_VERSION,
                MATERIAL_CHANGE_SET_VERSION,
                PROMPT_CHANGE_SET_VERSION,
            }
            or source_version
            in {
                DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION,
                HISTORICAL_GROWTH_DIALOGUE_CANDIDATE_VERSION,
                "armi.cognition-candidate.v6",
                "armi.cognition-candidate.v7",
            }
            or (
                source_version
                in {
                    HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                    HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION,
                    HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION,
                    HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION,
                    HISTORICAL_GROWTH_WEB_DIALOGUE_CANDIDATE_VERSION,
                    WEB_DIALOGUE_CANDIDATE_VERSION,
                }
                and not web_research_requests
            )
        ):
            change_set_value["codex_delegations"] = [
                _codex_delegation_wire(item) for item in codex_delegations
            ]
        canonical = rfc8785.dumps(cast(Any, change_set_value))
        change_set = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            self._context.subject_id,
            self._context.generation_id,
            self._context.episode_id,
            self._context.model_attempt_id,
            self._context.base_subject_version,
            self._context.base_state_epoch,
            self._context.bundle_activation_id,
            self._context.context_digest,
            candidate_digest,
            disposition,
            experiences,
            components,
            capability_requests,
            action_choices,
            web_research_requests,
            rejections,
            codex_delegations,
            memories=memories,
            memory_revisions=memory_revisions,
            relationships=relationships,
            materials=materials,
            prompts=prompts,
        )
        status = (
            CandidateValidationStatus.PARTIALLY_ACCEPTED
            if rejections
            else CandidateValidationStatus.ACCEPTED
        )
        return CandidateValidationResult(
            CandidateValidationId(uuid7()),
            status,
            change_set,
            len(accepted),
            len(rejected),
            None,
        )

    def _validate_autonomous(
        self,
        candidate: StartActivityDecision | AutonomousTerminalDecision,
        *,
        bases: tuple[CandidateBasis, ...],
        candidate_digest: Digest,
    ) -> CandidateValidationResult:
        if (
            self._context.purpose != "consider_autonomous_life"
            or self._context.opportunity_id is None
            or self._context.scene_id is not None
            or self._context.creator_party_id is not None
        ):
            return _rejected("CANDIDATE-ACTIVITY-CONTEXT")
        source = next(
            (
                item
                for item in bases
                if item.item_kind == "current_life_opportunity"
                and item.trust_class == "runtime_authority"
                and item.source_ref is not None
            ),
            None,
        )
        if source is None:
            return _rejected("CANDIDATE-ACTIVITY-SOURCE")
        disposition = {
            "start_activity": CandidateDisposition.CHANGE,
            "no_activity": CandidateDisposition.NO_CHANGE,
            "defer": CandidateDisposition.DEFER,
            "need_information": CandidateDisposition.NEED_INFORMATION,
        }[candidate.kind]
        activities: tuple[CandidateActivityDraft, ...] = ()
        if isinstance(candidate, StartActivityDecision):
            activities = (
                CandidateActivityDraft(
                    "proposal:1",
                    "group:1",
                    (source.ordinal,),
                    CandidateFactClass.INFERENCE,
                    uuid7(),
                    candidate.goal,
                    candidate.next_step,
                    ActivityStatus.READY,
                ),
            )
        value = {
            "schema_version": ACTIVITY_CHANGE_SET_VERSION,
            "subject_id": str(self._context.subject_id),
            "generation_id": str(self._context.generation_id),
            "episode_id": str(self._context.episode_id),
            "model_attempt_id": str(self._context.model_attempt_id),
            "base": {
                "subject_version": self._context.base_subject_version,
                "state_epoch": self._context.base_state_epoch,
                "bundle_activation_id": str(self._context.bundle_activation_id),
                "context_digest": self._context.context_digest.value,
            },
            "candidate_digest": candidate_digest.value,
            "disposition": disposition.value,
            "experiences": [],
            "components": [],
            "capability_requests": [],
            "action_choices": [],
            "codex_delegations": [],
            "activities": [_activity_wire(item) for item in activities],
            "rejections": [],
        }
        canonical = rfc8785.dumps(cast(Any, value))
        change_set = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            self._context.subject_id,
            self._context.generation_id,
            self._context.episode_id,
            self._context.model_attempt_id,
            self._context.base_subject_version,
            self._context.base_state_epoch,
            self._context.bundle_activation_id,
            self._context.context_digest,
            candidate_digest,
            disposition,
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            activities,
        )
        return CandidateValidationResult(
            CandidateValidationId(uuid7()),
            CandidateValidationStatus.ACCEPTED,
            change_set,
            len(activities),
            0,
            None,
        )

    def _validate_sleep(
        self,
        candidate: SleepDecisionCandidate,
        *,
        bases: tuple[CandidateBasis, ...],
        candidate_digest: Digest,
    ) -> CandidateValidationResult:
        context = self._context
        if (
            context.purpose != "consider_sleep"
            or context.opportunity_id is None
            or context.scene_id is not None
            or context.creator_party_id is not None
        ):
            return _rejected("CANDIDATE-SLEEP-CONTEXT")
        source = next(
            (
                item
                for item in bases
                if item.item_kind == "current_maintenance_window"
                and item.trust_class == "runtime_authority"
                and item.source_ref is not None
                and item.source_digest is not None
            ),
            None,
        )
        if source is None or source.source_ref is None or source.source_digest is None:
            return _rejected("CANDIDATE-SLEEP-SOURCE")
        decision = CandidateSleepDecisionDraft(
            "proposal:1",
            "group:1",
            (source.ordinal,),
            SleepDecisionKind(candidate.kind),
            source.source_ref,
            source.source_digest,
        )
        disposition = {
            SleepDecisionKind.SLEEP: CandidateDisposition.CHANGE,
            SleepDecisionKind.STAY_AWAKE: CandidateDisposition.NO_CHANGE,
            SleepDecisionKind.DEFER: CandidateDisposition.DEFER,
            SleepDecisionKind.NEED_INFORMATION: CandidateDisposition.NEED_INFORMATION,
        }[decision.decision_kind]
        value = {
            "schema_version": SLEEP_CHANGE_SET_VERSION,
            "subject_id": str(context.subject_id),
            "generation_id": str(context.generation_id),
            "episode_id": str(context.episode_id),
            "model_attempt_id": str(context.model_attempt_id),
            "base": {
                "subject_version": context.base_subject_version,
                "state_epoch": context.base_state_epoch,
                "bundle_activation_id": str(context.bundle_activation_id),
                "context_digest": context.context_digest.value,
            },
            "candidate_digest": candidate_digest.value,
            "disposition": disposition.value,
            "experiences": [],
            "components": [],
            "capability_requests": [],
            "action_choices": [],
            "codex_delegations": [],
            "activities": [],
            "activity_decisions": [],
            "sleep_decisions": [_sleep_decision_wire(decision)],
            "rejections": [],
        }
        canonical = rfc8785.dumps(cast(Any, value))
        change_set = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            context.subject_id,
            context.generation_id,
            context.episode_id,
            context.model_attempt_id,
            context.base_subject_version,
            context.base_state_epoch,
            context.bundle_activation_id,
            context.context_digest,
            candidate_digest,
            disposition,
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (decision,),
        )
        return CandidateValidationResult(
            CandidateValidationId(uuid7()),
            CandidateValidationStatus.ACCEPTED,
            change_set,
            1,
            0,
            None,
        )

    def _validate_attention(
        self,
        candidate: ActivityAttentionCandidate,
        *,
        bases: tuple[CandidateBasis, ...],
        candidate_digest: Digest,
    ) -> CandidateValidationResult:
        context = self._context
        if (
            context.purpose != "consider_activity_attention"
            or context.opportunity_id is None
            or context.scene_id is not None
            or context.creator_party_id is not None
            or context.current_activity_id is None
            or context.current_activity_revision_id is None
            or context.current_activity_head_version is None
            or context.current_activity_status is None
            or context.resource_snapshot_digest is None
        ):
            return _rejected("CANDIDATE-ACTIVITY-ATTENTION-CONTEXT")
        source = next(
            (
                item
                for item in bases
                if item.item_kind == "current_activity"
                and item.trust_class == "runtime_authority"
                and item.source_ref == context.current_activity_revision_id
            ),
            None,
        )
        if source is None:
            return _rejected("CANDIDATE-ACTIVITY-ATTENTION-SOURCE")
        kind = ActivityAttentionDecisionKind(candidate.kind)
        if not _attention_transition_allowed(context.current_activity_status, kind):
            return _rejected("CANDIDATE-ACTIVITY-TRANSITION")
        progress = next_step = waiting = cue = terminal = None
        waiting_kind = None
        delay = None
        if isinstance(candidate, AttentionProgressDecision):
            progress, next_step = candidate.progress_summary, candidate.next_step
        elif isinstance(candidate, AttentionWaitDecision):
            progress = candidate.progress_summary
            next_step = candidate.next_step
            waiting = candidate.waiting_summary
            cue = candidate.resumption_cue
            waiting_kind = ActivityWaitingKind(candidate.condition_kind)
            if (
                waiting_kind is ActivityWaitingKind.TIME
                and candidate.delay_seconds is None
            ):
                return _rejected("CANDIDATE-ACTIVITY-WAIT-DELAY")
            delay = (
                candidate.delay_seconds
                if waiting_kind is ActivityWaitingKind.TIME
                else None
            )
        elif isinstance(candidate, AttentionPauseDecision):
            progress = candidate.progress_summary
            next_step = candidate.next_step
            waiting = "scheduled review"
            cue = candidate.resumption_cue
            waiting_kind = ActivityWaitingKind.SCHEDULED_REVIEW
            delay = candidate.review_after_seconds
        elif isinstance(candidate, AttentionTerminalDecision):
            progress = candidate.progress_summary
            terminal = candidate.terminal_reason
        decision = CandidateActivityDecisionDraft(
            "proposal:1",
            "group:1",
            (source.ordinal,),
            context.current_activity_id,
            context.current_activity_revision_id,
            context.current_activity_head_version,
            context.resource_snapshot_digest,
            kind,
            progress,
            next_step,
            waiting,
            cue,
            waiting_kind,
            delay,
            terminal,
        )
        disposition = (
            CandidateDisposition.CHANGE
            if kind
            not in {
                ActivityAttentionDecisionKind.NO_ACTION,
                ActivityAttentionDecisionKind.DEFER,
                ActivityAttentionDecisionKind.NEED_INFORMATION,
            }
            else CandidateDisposition.NO_ACTION
            if kind is ActivityAttentionDecisionKind.NO_ACTION
            else CandidateDisposition.DEFER
            if kind is ActivityAttentionDecisionKind.DEFER
            else CandidateDisposition.NEED_INFORMATION
        )
        value = {
            "schema_version": ACTIVITY_ATTENTION_CHANGE_SET_VERSION,
            "subject_id": str(context.subject_id),
            "generation_id": str(context.generation_id),
            "episode_id": str(context.episode_id),
            "model_attempt_id": str(context.model_attempt_id),
            "base": {
                "subject_version": context.base_subject_version,
                "state_epoch": context.base_state_epoch,
                "bundle_activation_id": str(context.bundle_activation_id),
                "context_digest": context.context_digest.value,
            },
            "candidate_digest": candidate_digest.value,
            "disposition": disposition.value,
            "experiences": [],
            "components": [],
            "capability_requests": [],
            "action_choices": [],
            "codex_delegations": [],
            "activities": [],
            "activity_decisions": [_activity_decision_wire(decision)],
            "rejections": [],
        }
        canonical = rfc8785.dumps(cast(Any, value))
        change_set = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            context.subject_id,
            context.generation_id,
            context.episode_id,
            context.model_attempt_id,
            context.base_subject_version,
            context.base_state_epoch,
            context.bundle_activation_id,
            context.context_digest,
            candidate_digest,
            disposition,
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (decision,),
        )
        return CandidateValidationResult(
            CandidateValidationId(uuid7()),
            CandidateValidationStatus.ACCEPTED,
            change_set,
            1,
            0,
            None,
        )

    def _base_matches(
        self,
        candidate: (
            CognitionCandidate
            | CognitionCandidateV5
            | CognitionCandidateV6
            | CognitionCandidateV7
        ),
    ) -> bool:
        base = candidate.base
        return (
            base.subject_version == self._context.base_subject_version
            and base.state_epoch == self._context.base_state_epoch
            and base.bundle_activation_id == str(self._context.bundle_activation_id)
            and base.context_digest == self._context.context_digest.value
        )


def _expand_dialogue_candidate(
    source: CreatorDialogueCandidate,
    *,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[
    CognitionCandidateV5 | CognitionCandidateV7 | None,
    DialogueBoundChanges | None,
    str | None,
]:
    evidence = next(
        (
            item
            for item in bases
            if item.item_kind == "current_evidence"
            and item.trust_class == "external_claim"
        ),
        None,
    )
    scene = next(
        (
            item
            for item in bases
            if item.item_kind == "current_scene" and item.source_ref == context.scene_id
        ),
        None,
    )
    if evidence is None:
        return None, None, "CANDIDATE-EVIDENCE-REQUIRED"
    evidence_ref = f"ctx:{evidence.ordinal}"
    scene_ref = None if scene is None else f"ctx:{scene.ordinal}"
    if not isinstance(
        source,
        (
            DialogueReplyDecision,
            DialogueReplyDecisionV5,
            DialogueReplyDecisionV6,
            DialogueReplyDecisionV7,
            DialogueReplyDecisionV8,
            DialogueReplyDecisionV9,
            DialogueReplyDecisionV10,
            DialogueReplyDecisionV11,
            DialogueReplyDecisionV12,
            DialogueReplyDecisionV13,
            DialogueReplyDecisionV14,
            DialogueReplyDecisionV16,
            DialogueTerminalDecision,
            DialogueTerminalDecisionV5,
            DialogueTerminalDecisionV6,
            DialogueTerminalDecisionV7,
            DialogueTerminalDecisionV8,
            DialogueTerminalDecisionV9,
            DialogueTerminalDecisionV10,
            DialogueTerminalDecisionV11,
            DialogueTerminalDecisionV12,
            DialogueTerminalDecisionV13,
            DialogueTerminalDecisionV14,
            DialogueTerminalDecisionV16,
            DialogueWebResearchDecision,
            DialogueWebResearchDecisionV8,
            DialogueWebResearchDecisionV10,
            DialogueWebResearchDecisionV12,
            DialogueWebResearchDecisionV14,
            DialogueWebResearchDecisionV16,
        ),
    ):
        return None, None, "CANDIDATE-CONTRACT"
    decision = source
    summary = {
        "reply": "Creator dialogue reply selected.",
        "decline": "Creator dialogue decline selected.",
        "no_action": "Creator dialogue no action selected.",
        "no_change": "Creator dialogue no change selected.",
        "defer": "Creator dialogue defer selected.",
        "need_information": "Creator dialogue needs information.",
        "web_research": "Creator dialogue selected public Web research.",
    }[decision.kind]
    disposition = decision.kind
    experiences: list[dict[str, Any]] = []
    component_changes: list[dict[str, Any]] = []
    memory_changes: list[dict[str, Any]] = []
    capability_requests: list[dict[str, Any]] = []
    action_choices: list[dict[str, Any]] = []
    memory_revision: CandidateMemoryRevisionDraft | None = None
    relationship: CandidateRelationshipDraft | None = None
    material: CandidateLifeMaterialDraft | None = None
    prompt: CandidateSubjectPromptDraft | None = None
    experience_ref: str | None = None
    understanding_basis_refs = (evidence_ref,)
    if isinstance(
        decision,
        (
            DialogueReplyDecisionV5,
            DialogueReplyDecisionV6,
            DialogueReplyDecisionV7,
            DialogueReplyDecision,
            DialogueReplyDecisionV8,
            DialogueReplyDecisionV9,
            DialogueReplyDecisionV10,
            DialogueReplyDecisionV11,
            DialogueReplyDecisionV12,
            DialogueReplyDecisionV13,
            DialogueReplyDecisionV14,
            DialogueReplyDecisionV16,
        ),
    ):
        catalog = next(
            (
                item
                for item in bases
                if item.item_kind == "capability_catalog"
                and item.trust_class == "policy"
            ),
            None,
        )
        if scene_ref is None:
            return None, None, "CANDIDATE-ACTION-SCENE-BASIS"
        if catalog is None:
            return None, None, "CANDIDATE-ACTION-CAPABILITY-BASIS"
        catalog_ref = f"ctx:{catalog.ordinal}"
        proposal_no = 1
        if decision.experience is not None:
            experience_ref = f"proposal:{proposal_no}"
            experiences.append(
                {
                    "proposal_ref": experience_ref,
                    "atomic_group_ref": "group:1",
                    "basis_refs": (evidence_ref,),
                    "payload": {
                        "proposal_kind": "experiences",
                        "fact_class": "external_claim",
                        "first_person_gist": decision.experience.first_person_gist,
                        "source_perspective": "creator_claim",
                        "uncertainty": decision.experience.uncertainty,
                        "privacy_scope": "private",
                    },
                }
            )
            proposal_no += 1
            if decision.experience.memory_summary is not None:
                memory_changes.append(
                    {
                        "proposal_ref": f"proposal:{proposal_no}",
                        "atomic_group_ref": "group:1",
                        "basis_refs": (evidence_ref,),
                        "payload": {
                            "proposal_kind": "memory_changes",
                            "fact_class": "external_claim",
                            "summary": decision.experience.memory_summary,
                        },
                    }
                )
                proposal_no += 1
        for owner, change, state_type in (
            (CandidateOwner.SELF, getattr(decision, "self_change", None), SelfState),
            (CandidateOwner.MIND, getattr(decision, "mind_change", None), MindState),
        ):
            if change is None:
                continue
            component_change, component_error = _bind_dialogue_component_change(
                owner=owner,
                change=change,
                state_type=state_type,
                proposal_ref=f"proposal:{proposal_no}",
                evidence_ref=evidence_ref,
                bases=bases,
                context=context,
            )
            if component_change is None:
                return (
                    None,
                    None,
                    component_error or "CANDIDATE-COMPONENT-CONTEXT",
                )
            component_changes.append(component_change)
            proposal_no += 1
        if decision.memory_change is not None:
            memory_revision, memory_error = _bind_dialogue_memory_revision(
                decision.memory_change,
                proposal_ref=f"proposal:{proposal_no}",
                evidence=evidence,
                bases=bases,
                context=context,
            )
            if memory_revision is None:
                return None, None, memory_error or "CANDIDATE-MEMORY-CONTEXT"
            proposal_no += 1
        if decision.relationship_change is not None:
            if decision.experience is None:
                return None, None, "CANDIDATE-RELATIONSHIP-EXPERIENCE"
            relationship, relationship_error = _bind_dialogue_relationship(
                decision.relationship_change,
                experience=decision.experience,
                source_experience_ref=experience_ref,
                proposal_ref=f"proposal:{proposal_no}",
                evidence=evidence,
                bases=bases,
                context=context,
            )
            if relationship is None:
                return (
                    None,
                    None,
                    relationship_error or "CANDIDATE-RELATIONSHIP-CONTEXT",
                )
            proposal_no += 1
        material_change = getattr(decision, "material_change", None)
        if material_change is not None:
            material, material_error = _bind_dialogue_material(
                material_change,
                proposal_ref=f"proposal:{proposal_no}",
                evidence=evidence,
                bases=bases,
                context=context,
            )
            if material is None:
                return None, None, material_error or "CANDIDATE-MATERIAL-CONTEXT"
            proposal_no += 1
        subject_prompt_change = getattr(decision, "subject_prompt_change", None)
        if subject_prompt_change is not None:
            prompt, prompt_error = _bind_dialogue_subject_prompt(
                subject_prompt_change,
                proposal_ref=f"proposal:{proposal_no}",
                evidence=evidence,
                bases=bases,
                context=context,
            )
            if prompt is None:
                return None, None, prompt_error or "CANDIDATE-SUBJECT-PROMPT-CONTEXT"
            proposal_no += 1
        shared_bases = (evidence_ref, scene_ref, catalog_ref)
        capability_requests.append(
            {
                "proposal_ref": f"proposal:{proposal_no}",
                "atomic_group_ref": "group:1",
                "basis_refs": shared_bases,
                "payload": {
                    "proposal_kind": "capability_requests",
                    "fact_class": "inference",
                    "capability_kind": "creator.scene.reply",
                    "operation": "send",
                    "audience_scope": "creator",
                    "data_scope": "creator_visible_response",
                    "purpose": "respond_to_creator",
                    "valid_for_seconds": 3600,
                    "max_uses": 1,
                    "max_payload_bytes": len(decision.content.encode("utf-8")),
                },
            }
        )
        proposal_no += 1
        capability_request = getattr(decision, "capability_request", None)
        if capability_request is not None:
            capability_state = next(
                (
                    item
                    for item in bases
                    if f"ctx:{item.ordinal}" == capability_request.capability_ref
                ),
                None,
            )
            if (
                capability_state is None
                or capability_state.section != "capability"
                or not capability_state.item_kind.startswith("capability_state_")
                or capability_state.trust_class != "runtime_authority"
                or capability_state.source_ref != _CODEX_CAPABILITY_ID
            ):
                return None, None, "CANDIDATE-CAPABILITY-STATE-BASIS"
            capability_requests.append(
                {
                    "proposal_ref": f"proposal:{proposal_no}",
                    "atomic_group_ref": "group:2",
                    "basis_refs": (*shared_bases, capability_request.capability_ref),
                    "payload": {
                        "proposal_kind": "capability_requests",
                        "fact_class": "inference",
                        "capability_kind": "codex.delegated-work",
                        "operation": "execute",
                        "workspace_scope": "isolated_ephemeral",
                        "artifact_scope": "explicit_only",
                        "network_access": False,
                        "valid_for_seconds": 3600,
                        "max_uses": 1,
                    },
                }
            )
            proposal_no += 1
        action_choices.append(
            {
                "proposal_ref": f"proposal:{proposal_no}",
                "atomic_group_ref": "group:1",
                "basis_refs": shared_bases,
                "payload": {
                    "proposal_kind": "action_choices",
                    "action_kind": "creator_reply",
                    "fact_class": "subjective_understanding",
                    "capability_kind": "creator.scene.reply",
                    "operation": "send",
                    "audience_scope": "creator",
                    "data_scope": "creator_visible_response",
                    "purpose": "respond_to_creator",
                    "media_type": "text/plain",
                    "content": decision.content,
                },
            }
        )
        disposition = "change"
    elif decision.kind in {"decline", "no_action"}:
        if scene_ref is None:
            return None, None, "CANDIDATE-ACTION-SCENE-BASIS"
        action_choices.append(
            {
                "proposal_ref": "proposal:1",
                "atomic_group_ref": "group:1",
                "basis_refs": (evidence_ref, scene_ref),
                "payload": {
                    "proposal_kind": "action_choices",
                    "action_kind": "formal_no_action",
                    "fact_class": "subjective_understanding",
                    "decision": decision.kind,
                    "reason_class": (
                        "subjective_refusal"
                        if decision.kind == "decline"
                        else "subjective_silence"
                    ),
                },
            }
        )
    elif isinstance(
        decision,
        (
            DialogueWebResearchDecision,
            DialogueWebResearchDecisionV8,
            DialogueWebResearchDecisionV10,
            DialogueWebResearchDecisionV12,
            DialogueWebResearchDecisionV14,
            DialogueWebResearchDecisionV16,
        ),
    ):
        purpose = next(
            (
                item
                for item in bases
                if item.item_kind == "current_purpose" and item.trust_class == "policy"
            ),
            None,
        )
        availability = next(
            (
                item
                for item in bases
                if item.item_kind == "web_search_availability"
                and item.trust_class == "policy"
            ),
            None,
        )
        if purpose is None:
            return None, None, "CANDIDATE-WEB-PURPOSE-BASIS"
        if availability is None:
            return None, None, "CANDIDATE-WEB-AVAILABILITY-BASIS"
        understanding_basis_refs = (
            evidence_ref,
            f"ctx:{purpose.ordinal}",
            f"ctx:{availability.ordinal}",
        )
        try:
            return (
                CognitionCandidateV5.model_validate(
                    {
                        "schema_version": "armi.cognition-candidate.v5",
                        "base": {
                            "subject_version": context.base_subject_version,
                            "state_epoch": context.base_state_epoch,
                            "bundle_activation_id": str(context.bundle_activation_id),
                            "context_digest": context.context_digest.value,
                        },
                        "disposition": "change",
                        "understanding": {
                            "text": summary,
                            "fact_class": "inference",
                            "basis_refs": understanding_basis_refs,
                        },
                        "experiences": (),
                        "component_changes": (),
                        "memory_changes": (),
                        "relationship_changes": (),
                        "activity_changes": (),
                        "capability_requests": (),
                        "action_choices": (),
                        "web_research_requests": (
                            {
                                "proposal_ref": "proposal:1",
                                "atomic_group_ref": "group:1",
                                "basis_refs": understanding_basis_refs,
                                "payload": {
                                    "proposal_kind": "web_research_requests",
                                    "fact_class": "subjective_understanding",
                                    "purpose": "public_web_research",
                                    "operation_class": "search_read_public",
                                    "query": decision.query,
                                },
                            },
                        ),
                        "uncertainties": (),
                        "reason_summary": summary,
                    },
                    strict=True,
                ),
                DialogueBoundChanges(),
                None,
            )
        except Exception:
            return None, None, "CANDIDATE-CONTRACT"
    try:
        return (
            CognitionCandidateV7.model_validate(
                {
                    "schema_version": "armi.cognition-candidate.v7",
                    "base": {
                        "subject_version": context.base_subject_version,
                        "state_epoch": context.base_state_epoch,
                        "bundle_activation_id": str(context.bundle_activation_id),
                        "context_digest": context.context_digest.value,
                    },
                    "disposition": disposition,
                    "understanding": {
                        "text": summary,
                        "fact_class": "inference",
                        "basis_refs": understanding_basis_refs,
                    },
                    "experiences": tuple(experiences),
                    "component_changes": tuple(component_changes),
                    "memory_changes": tuple(memory_changes),
                    "relationship_changes": (),
                    "activity_changes": (),
                    "capability_requests": tuple(capability_requests),
                    "action_choices": tuple(action_choices),
                    "uncertainties": (),
                    "reason_summary": summary,
                },
                strict=True,
            ),
            DialogueBoundChanges(memory_revision, relationship, material, prompt),
            None,
        )
    except Exception:
        return None, None, "CANDIDATE-CONTRACT"


def _bind_dialogue_component_change(
    *,
    owner: CandidateOwner,
    change: Any,
    state_type: type[SelfState] | type[MindState],
    proposal_ref: str,
    evidence_ref: str,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[dict[str, Any] | None, str | None]:
    current = next(
        (
            (version, canonical)
            for current_owner, version, canonical in context.current_components
            if current_owner is owner
        ),
        None,
    )
    basis = next(
        (
            item
            for item in bases
            if item.item_kind == owner.value
            and current is not None
            and item.source_version == current[0]
            and item.source_digest == Digest.from_bytes(current[1])
        ),
        None,
    )
    if current is None or basis is None:
        return None, "CANDIDATE-COMPONENT-CONTEXT"
    try:
        current_state = state_type.model_validate_json(current[1], strict=True)
        next_state = current_state.model_dump(mode="json")
        field_names = (
            (
                "name",
                "self_description",
                "interests",
                "values",
                "preferences",
                "goals",
                "self_narrative",
            )
            if owner is CandidateOwner.SELF
            else (
                "understanding",
                "attention",
                "emotions",
                "thoughts",
                "wishes",
                "motivations",
                "mood",
            )
        )
        for field_name in field_names:
            replacement = getattr(change, field_name, None)
            if replacement is None:
                continue
            next_state[field_name] = (
                list(replacement.values)
                if hasattr(replacement, "values")
                else replacement.value
            )
        validated = state_type.model_validate_json(
            rfc8785.dumps(cast(Any, next_state)), strict=True
        )
    except Exception:
        return None, "CANDIDATE-COMPONENT-STATE"
    return (
        {
            "proposal_ref": proposal_ref,
            "atomic_group_ref": "group:1",
            "basis_refs": (evidence_ref, f"ctx:{basis.ordinal}"),
            "payload": {
                "proposal_kind": "component_changes",
                "fact_class": "subjective_understanding",
                "owner": owner.value,
                "expected_version": current[0],
                "next_state": validated.model_dump(mode="python"),
            },
        },
        None,
    )


def _bind_dialogue_subject_prompt(
    change: Any,
    *,
    proposal_ref: str,
    evidence: CandidateBasis,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[CandidateSubjectPromptDraft | None, str | None]:
    current = context.current_subject_prompt
    self_component = next(
        (
            (version, canonical)
            for owner, version, canonical in context.current_components
            if owner is CandidateOwner.SELF
        ),
        None,
    )
    self_basis = next(
        (
            item
            for item in bases
            if item.item_kind == "self"
            and self_component is not None
            and item.source_version == self_component[0]
            and item.source_digest == Digest.from_bytes(self_component[1])
        ),
        None,
    )
    if current is None or self_component is None or self_basis is None:
        return None, "CANDIDATE-SUBJECT-PROMPT-CONTEXT"
    prompt_basis = None
    if current.current_revision_id is not None:
        prompt_basis = next(
            (
                item
                for item in bases
                if item.item_kind == "subject_prompt"
                and item.source_ref == current.current_revision_id
                and item.source_version == current.revision_no
                and item.source_digest == current.content_digest
                and item.trust_class == "policy"
            ),
            None,
        )
        if prompt_basis is None:
            return None, "CANDIDATE-SUBJECT-PROMPT-CONTEXT"
    methods = {
        "cognition_method": change.cognition_method,
        "expression_method": change.expression_method,
        "reflection_method": change.reflection_method,
    }
    try:
        self_state = SelfState.model_validate_json(self_component[1], strict=True)
        self_document = self_state.model_dump(mode="python")
        self_values = {
            value.strip().casefold()
            for field_name in (
                "name",
                "self_description",
                "interests",
                "values",
                "preferences",
                "goals",
                "self_narrative",
            )
            for value in _nested_text_values(self_document.get(field_name))
            if value.strip()
        }
    except Exception:
        return None, "CANDIDATE-SUBJECT-PROMPT-CONTEXT"
    if any(
        self_value in method.strip().casefold()
        for method in methods.values()
        for self_value in self_values
    ):
        return None, "CANDIDATE-SUBJECT-PROMPT-SELF-DUPLICATE"
    content = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.subject-prompt.v1",
                **methods,
            },
        )
    )
    digest = Digest.from_bytes(content)
    if digest == current.content_digest:
        return None, "CANDIDATE-SUBJECT-PROMPT-UNCHANGED"
    basis_ordinals = (
        evidence.ordinal,
        self_basis.ordinal,
        *((prompt_basis.ordinal,) if prompt_basis is not None else ()),
    )
    return (
        CandidateSubjectPromptDraft(
            proposal_ref,
            "group:1",
            basis_ordinals,
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            current.prompt_document_id,
            current.current_revision_id,
            current.revision_no,
            content,
            digest,
        ),
        None,
    )


def _nested_text_values(value: object) -> tuple[str, ...]:
    if type(value) is str:
        return (value,)
    if type(value) is list:
        return tuple(
            text
            for item in cast(list[object], value)
            for text in _nested_text_values(item)
        )
    if type(value) is dict:
        return tuple(
            text
            for item in cast(dict[object, object], value).values()
            for text in _nested_text_values(item)
        )
    return ()


def _bind_dialogue_material(
    change: DialogueMaterialChange | DialogueMaterialChangeV7,
    *,
    proposal_ref: str,
    evidence: CandidateBasis,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[CandidateLifeMaterialDraft | None, str | None]:
    if context.subject_party_id is None:
        return None, "CANDIDATE-MATERIAL-OWNER"
    if (
        isinstance(change, (DialogueMaterialContentChange, DialogueMaterialChangeV7))
        and change.action == "create"
    ):
        assert change.material_kind is not None
        body_bytes = change.body.encode("utf-8", errors="strict")
        return (
            CandidateLifeMaterialDraft(
                proposal_ref,
                "group:1",
                (evidence.ordinal,),
                _derived_material_id(context.model_attempt_id),
                context.subject_party_id,
                LifeMaterialKind(change.material_kind),
                None,
                0,
                change.title,
                body_bytes,
                Digest.from_bytes(body_bytes),
                tuple(sorted(change.metadata.items())),
                LifeMaterialStatus(change.material_status),
            ),
            None,
        )

    target_basis = next(
        (
            item
            for item in bases
            if f"ctx:{item.ordinal}" == change.material_ref
            and item.section == "material"
            and item.item_kind == "current_material"
            and item.trust_class == "subjective_state"
            and item.source_ref is not None
        ),
        None,
    )
    if target_basis is None:
        return None, "CANDIDATE-MATERIAL-CONTEXT"
    current = next(
        (
            item
            for item in context.current_materials
            if item.material_id == target_basis.source_ref
        ),
        None,
    )
    if current is None or (
        current.head_version != target_basis.source_version
        or current.context_digest != target_basis.source_digest
    ):
        return None, "CANDIDATE-MATERIAL-STALE"
    if current.owner_party_id != context.subject_party_id:
        return None, "CANDIDATE-MATERIAL-OWNER"
    if isinstance(change, (DialogueMaterialContentChange, DialogueMaterialChangeV7)):
        body_bytes = change.body.encode("utf-8", errors="strict")
        body_digest = Digest.from_bytes(body_bytes)
        metadata = tuple(sorted(change.metadata.items()))
        material_status = LifeMaterialStatus(change.material_status)
        if (
            current.title == change.title
            and current.body_digest == body_digest
            and current.metadata == metadata
            and current.material_status is material_status
        ):
            return None, "CANDIDATE-MATERIAL-NO-OP"
        return (
            CandidateLifeMaterialDraft(
                proposal_ref,
                "group:1",
                (evidence.ordinal, target_basis.ordinal),
                current.material_id,
                current.owner_party_id,
                current.material_kind,
                current.current_revision_id,
                current.head_version,
                change.title,
                body_bytes,
                body_digest,
                metadata,
                material_status,
                current.privacy_status.value,
            ),
            None,
        )

    assert isinstance(change, DialogueMaterialStateChange)
    privacy_status = {
        "set_private": LifeMaterialPrivacyStatus.PRIVATE,
        "set_creator_visible": LifeMaterialPrivacyStatus.CREATOR_VISIBLE,
        "delete": LifeMaterialPrivacyStatus.RESTRICTED,
    }[change.action]
    revision_kind = (
        LifeMaterialRevisionKind.DELETED
        if change.action == "delete"
        else LifeMaterialRevisionKind.PRIVACY_CHANGED
    )
    if privacy_status is current.privacy_status:
        return None, "CANDIDATE-MATERIAL-NO-OP"
    return (
        CandidateLifeMaterialDraft(
            proposal_ref,
            "group:1",
            (evidence.ordinal, target_basis.ordinal),
            current.material_id,
            current.owner_party_id,
            current.material_kind,
            current.current_revision_id,
            current.head_version,
            current.title,
            None,
            current.body_digest,
            current.metadata,
            current.material_status,
            privacy_status.value,
            change_kind=revision_kind,
        ),
        None,
    )


def _bind_dialogue_memory_revision(
    change: DialogueMemoryChange,
    *,
    proposal_ref: str,
    evidence: CandidateBasis,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[CandidateMemoryRevisionDraft | None, str | None]:
    basis_by_ref = {f"ctx:{item.ordinal}": item for item in bases}
    target_basis = basis_by_ref.get(change.memory_ref)
    if (
        target_basis is None
        or target_basis.section != "memory"
        or target_basis.item_kind != "current_memory"
        or target_basis.trust_class != "subjective_state"
        or target_basis.source_ref is None
    ):
        return None, "CANDIDATE-MEMORY-CONTEXT"
    current = next(
        (
            item
            for item in context.current_memories
            if item.memory_id == target_basis.source_ref
        ),
        None,
    )
    if current is None or (
        current.head_version != target_basis.source_version
        or current.context_digest != target_basis.source_digest
    ):
        return None, "CANDIDATE-MEMORY-STALE"

    related_memory_id: UUID | None = None
    relation_kind: MemoryRelationKind | None = None
    related_basis: CandidateBasis | None = None
    if change.related_memory_ref is not None:
        related_basis = basis_by_ref.get(change.related_memory_ref)
        if (
            related_basis is None
            or related_basis.section != "memory"
            or related_basis.item_kind != "current_memory"
            or related_basis.source_ref is None
            or not any(
                item.memory_id == related_basis.source_ref
                and item.head_version == related_basis.source_version
                and item.context_digest == related_basis.source_digest
                for item in context.current_memories
            )
        ):
            return None, "CANDIDATE-MEMORY-RELATION"
        related_memory_id = related_basis.source_ref
        assert change.relation_kind is not None
        relation_kind = MemoryRelationKind(change.relation_kind)

    revision_kind = {
        "recall": MemoryRevisionKind.RECALLED,
        "fade": MemoryRevisionKind.FADED,
        "forget": MemoryRevisionKind.FORGOTTEN,
        "reinterpret": MemoryRevisionKind.REINTERPRETED,
    }[change.action]
    accessibility = {
        "recall": MemoryAccessibility.AVAILABLE,
        "fade": MemoryAccessibility.FADED,
        "forget": MemoryAccessibility.FORGOTTEN,
        "reinterpret": current.accessibility,
    }[change.action]
    summary = change.summary if change.summary is not None else current.summary
    uncertainty = (
        change.uncertainty if change.action == "reinterpret" else current.uncertainty
    )
    if change.action == "fade" and current.accessibility is MemoryAccessibility.FADED:
        return None, "CANDIDATE-MEMORY-NO-OP"
    if (
        change.action == "reinterpret"
        and summary == current.summary
        and uncertainty == current.uncertainty
        and related_memory_id is None
    ):
        return None, "CANDIDATE-MEMORY-NO-OP"
    basis_ordinals = [evidence.ordinal, target_basis.ordinal]
    if related_basis is not None:
        basis_ordinals.append(related_basis.ordinal)
    return (
        CandidateMemoryRevisionDraft(
            proposal_ref,
            "group:1",
            tuple(dict.fromkeys(basis_ordinals)),
            current.fact_class,
            current.memory_id,
            current.current_revision_id,
            current.head_version,
            revision_kind,
            accessibility,
            current.source_kind,
            summary,
            uncertainty,
            related_memory_id,
            relation_kind,
        ),
        None,
    )


def _bind_dialogue_relationship(
    change: DialogueRelationshipChange,
    *,
    experience: Any,
    source_experience_ref: str | None,
    proposal_ref: str,
    evidence: CandidateBasis,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[CandidateRelationshipDraft | None, str | None]:
    if (
        source_experience_ref is None
        or context.subject_party_id is None
        or context.creator_party_id is None
    ):
        return None, "CANDIDATE-RELATIONSHIP-CONTEXT"
    current = context.current_relationship
    if current is not None and current.status is RelationshipStatus.ENDED:
        return None, "CANDIDATE-RELATIONSHIP-ENDED"
    current_basis: CandidateBasis | None = None
    if current is not None:
        current_basis = next(
            (
                item
                for item in bases
                if item.section == "relationship"
                and item.item_kind == "current_relationship"
                and item.source_ref == current.relationship_id
                and item.source_version == current.head_version
                and item.source_digest == current.context_digest
                and item.trust_class == "subjective_state"
            ),
            None,
        )
        if current_basis is None:
            return None, "CANDIDATE-RELATIONSHIP-BASIS"

    facts = list(() if current is None else current.facts)
    shared_experience = RelationshipFact(
        RelationshipFactKind.SHARED_EXPERIENCE,
        experience.first_person_gist,
    )
    if shared_experience not in facts:
        facts.append(shared_experience)
    if change.fact is not None:
        fact = RelationshipFact(
            RelationshipFactKind(change.fact.kind),
            change.fact.summary,
        )
        if fact not in facts:
            facts.append(fact)
    if len(facts) > 64:
        return None, "CANDIDATE-RELATIONSHIP-FACT-LIMIT"

    interpretation = (
        change.interpretation
        if change.interpretation is not None
        else None
        if current is None
        else current.interpretation
    )
    if interpretation is None:
        return None, "CANDIDATE-RELATIONSHIP-INTERPRETATION"

    boundaries = {
        (item.party_role, item.kind): item
        for item in (() if current is None else current.boundaries)
    }
    if change.boundary is not None:
        boundary = RelationshipBoundary(
            RelationshipPartyRole(
                "subject" if change.boundary.party == "armi" else "other"
            ),
            RelationshipBoundaryKind(change.boundary.kind),
            RelationshipBoundaryAction(change.boundary.action),
            change.boundary.summary,
        )
        boundaries[(boundary.party_role, boundary.kind)] = boundary
    ordered_boundaries = tuple(
        value
        for _key, value in sorted(
            boundaries.items(),
            key=lambda item: (item[0][0].value, item[0][1].value),
        )
    )
    status = (
        RelationshipStatus.ENDED
        if any(
            value.action is RelationshipBoundaryAction.END_CONTACT
            for value in ordered_boundaries
        )
        else RelationshipStatus.ACTIVE
    )
    commitments = list(
        () if current is None else (item.commitment for item in current.commitments)
    )
    open_issues = list(() if current is None else current.open_issues)
    commitment_event: RelationshipCommitmentEvent | None = None
    commitment_basis_ordinals: tuple[int, ...] = ()
    if change.commitment_change is not None:
        (
            commitments,
            open_issues,
            commitment_event,
            commitment_basis_ordinals,
            commitment_error,
        ) = _bind_dialogue_commitment(
            change.commitment_change,
            commitments=commitments,
            open_issues=open_issues,
            bases=bases,
            context=context,
        )
        if commitment_error is not None:
            return None, commitment_error
    next_facts = tuple(facts)
    if current is not None and (
        next_facts,
        interpretation,
        ordered_boundaries,
        status,
        tuple(commitments),
        tuple(open_issues),
    ) == (
        current.facts,
        current.interpretation,
        current.boundaries,
        current.status,
        tuple(item.commitment for item in current.commitments),
        current.open_issues,
    ):
        return None, "CANDIDATE-RELATIONSHIP-NO-OP"
    basis_ordinals = [evidence.ordinal]
    if current_basis is not None:
        basis_ordinals.append(current_basis.ordinal)
    basis_ordinals.extend(commitment_basis_ordinals)
    return (
        CandidateRelationshipDraft(
            proposal_ref,
            "group:1",
            tuple(basis_ordinals),
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            (
                _derived_relationship_id(context.model_attempt_id)
                if current is None
                else current.relationship_id
            ),
            context.subject_party_id,
            context.creator_party_id,
            None if current is None else current.current_revision_id,
            0 if current is None else current.head_version,
            source_experience_ref,
            next_facts,
            interpretation,
            ordered_boundaries,
            status,
            tuple(commitments),
            tuple(open_issues),
            commitment_event,
        ),
        None,
    )


def _bind_dialogue_commitment(
    change: DialogueCommitmentChange,
    *,
    commitments: list[RelationshipCommitment],
    open_issues: list[RelationshipIssue],
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[
    list[RelationshipCommitment],
    list[RelationshipIssue],
    RelationshipCommitmentEvent | None,
    tuple[int, ...],
    str | None,
]:
    target, target_basis = _commitment_context(
        change.commitment_ref,
        bases=bases,
        context=context,
    )
    if change.action != "establish" and (target is None or target_basis is None):
        return commitments, open_issues, None, (), "CANDIDATE-COMMITMENT-CONTEXT"
    related, related_basis = _commitment_context(
        change.conflicts_with_ref,
        bases=bases,
        context=context,
    )
    if change.conflicts_with_ref is not None and (
        related is None or related_basis is None
    ):
        return commitments, open_issues, None, (), "CANDIDATE-COMMITMENT-CONFLICT"

    event_kind = RelationshipCommitmentEventKind(
        {
            "establish": "established",
            "modify": "modified",
            "fulfill": "fulfilled",
            "withdraw": "withdrawn",
            "forget": "forgotten",
            "violate": "violated",
            "note_conflict": "conflict_noted",
        }[change.action]
    )
    status = RelationshipCommitmentStatus(
        {
            "establish": "active",
            "modify": "active",
            "fulfill": "fulfilled",
            "withdraw": "withdrawn",
            "forget": "forgotten",
            "violate": "violated",
            "note_conflict": target.commitment.status.value if target else "active",
        }[change.action]
    )
    if change.action == "establish":
        commitment_id = _derived_uuid7(
            context.model_attempt_id,
            b"creator-relationship-commitment",
        )
        assert change.party is not None
        assert change.scope is not None
        assert change.content is not None
        next_commitment = RelationshipCommitment(
            commitment_id,
            RelationshipPartyRole("subject" if change.party == "armi" else "other"),
            change.scope,
            change.content,
            status,
            event_kind,
            change.event_summary,
        )
        commitments.append(next_commitment)
    else:
        assert target is not None
        commitment_id = target.commitment.commitment_id
        if change.action not in {"note_conflict"} and (
            target.commitment.status is not RelationshipCommitmentStatus.ACTIVE
        ):
            return (
                commitments,
                open_issues,
                None,
                (),
                "CANDIDATE-COMMITMENT-TERMINAL",
            )
        next_commitment = RelationshipCommitment(
            commitment_id,
            target.commitment.party_role,
            change.scope if change.scope is not None else target.commitment.scope,
            change.content if change.content is not None else target.commitment.content,
            status,
            event_kind,
            change.event_summary,
        )
        commitments[commitments.index(target.commitment)] = next_commitment

    event = RelationshipCommitmentEvent(
        commitment_id,
        event_kind,
        change.event_summary,
        (
            related.commitment.commitment_id
            if change.action == "note_conflict" and related is not None
            else None
        ),
    )
    conflict_ids: tuple[UUID, ...] | None = None
    issue_kind: RelationshipIssueKind | None = None
    if change.action == "violate":
        conflict_ids = (commitment_id,)
        issue_kind = RelationshipIssueKind.COMMITMENT_VIOLATION
    elif related is not None:
        conflict_ids = tuple(
            sorted(
                (commitment_id, related.commitment.commitment_id),
                key=str,
            )
        )
        issue_kind = RelationshipIssueKind.CONTRADICTORY_COMMITMENTS
    if (
        conflict_ids is not None
        and issue_kind is not None
        and not any(
            item.kind is issue_kind and item.commitment_ids == conflict_ids
            for item in open_issues
        )
    ):
        open_issues.append(
            RelationshipIssue(
                _derived_uuid7(
                    context.model_attempt_id,
                    b"creator-relationship-issue\0"
                    + issue_kind.value.encode("ascii")
                    + b"\0"
                    + b"".join(value.bytes for value in conflict_ids),
                ),
                issue_kind,
                conflict_ids,
                change.event_summary,
                RelationshipIssueStatus.OPEN,
            )
        )
    if len(commitments) > 16 or len(open_issues) > 32:
        return commitments, open_issues, None, (), "CANDIDATE-COMMITMENT-LIMIT"
    ordinals = tuple(
        dict.fromkeys(
            item.ordinal for item in (target_basis, related_basis) if item is not None
        )
    )
    return commitments, open_issues, event, ordinals, None


def _commitment_context(
    reference: str | None,
    *,
    bases: tuple[CandidateBasis, ...],
    context: CandidateValidationContext,
) -> tuple[CandidateRelationshipCommitmentContext | None, CandidateBasis | None]:
    if reference is None or context.current_relationship is None:
        return None, None
    basis = next(
        (
            item
            for item in bases
            if f"ctx:{item.ordinal}" == reference
            and item.section == "relationship"
            and item.item_kind == "current_relationship_commitment"
            and item.trust_class == "subjective_state"
            and item.source_ref is not None
        ),
        None,
    )
    if basis is None:
        return None, None
    commitment = next(
        (
            item
            for item in context.current_relationship.commitments
            if item.commitment.commitment_id == basis.source_ref
            and basis.source_version == context.current_relationship.head_version
            and item.context_digest is not None
            and item.context_digest == basis.source_digest
        ),
        None,
    )
    return commitment, basis if commitment is not None else None


def _derived_relationship_id(model_attempt_id: UUID) -> UUID:
    """Bind a stable UUIDv7 identity without giving the model identity authority."""

    return _derived_uuid7(model_attempt_id, b"creator-relationship")


def _derived_material_id(model_attempt_id: UUID) -> UUID:
    return _derived_uuid7(model_attempt_id, b"life-material")


def _derived_uuid7(model_attempt_id: UUID, label: bytes) -> UUID:
    digest = sha256(model_attempt_id.bytes + b"\0" + label).digest()
    raw = bytearray(model_attempt_id.bytes[:6] + digest[:10])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _all_proposals(
    candidate: (
        CognitionCandidate
        | CognitionCandidateV5
        | CognitionCandidateV6
        | CognitionCandidateV7
    ),
) -> tuple[tuple[CandidateOwner, Any], ...]:
    return (
        *((CandidateOwner.EXPERIENCE, item) for item in candidate.experiences),
        *(
            (CandidateOwner(item.payload.owner), item)
            for item in candidate.component_changes
        ),
        *((CandidateOwner.MEMORY, item) for item in candidate.memory_changes),
        *(
            (CandidateOwner.RELATIONSHIP, item)
            for item in candidate.relationship_changes
        ),
        *((CandidateOwner.ACTIVITY, item) for item in candidate.activity_changes),
        *((CandidateOwner.CAPABILITY, item) for item in candidate.capability_requests),
        *(
            (
                CandidateOwner.CODEX_DELEGATION
                if isinstance(item.payload, CodexDelegationPayload)
                else CandidateOwner.ACTION,
                item,
            )
            for item in candidate.action_choices
        ),
        *(
            (CandidateOwner.WEB_RESEARCH, item)
            for item in getattr(candidate, "web_research_requests", ())
        ),
    )


def _basis_failure(
    owner: CandidateOwner,
    bases: tuple[CandidateBasis, ...],
    fact_class: str,
) -> str | None:
    if not bases:
        return "CANDIDATE-BASIS-MISSING"
    if not _fact_supported(fact_class, bases):
        return "CANDIDATE-FACT-CLASS"
    if owner is CandidateOwner.EXPERIENCE and not any(
        basis.item_kind == "current_evidence" and basis.trust_class == "external_claim"
        for basis in bases
    ):
        return "CANDIDATE-EVIDENCE-REQUIRED"
    if owner is not CandidateOwner.EXPERIENCE and all(
        basis.trust_class == "policy" for basis in bases
    ):
        return "CANDIDATE-POLICY-NOT-FACT"
    return None


def _fact_supported(fact_class: str, bases: tuple[CandidateBasis, ...]) -> bool:
    trusts = {basis.trust_class for basis in bases}
    if fact_class == "objective_fact":
        return bool(trusts) and trusts <= {"runtime_authority"}
    if fact_class == "external_claim":
        return "external_claim" in trusts
    if fact_class == "subjective_understanding":
        return bool(trusts & {"subjective_state", "external_claim"})
    if fact_class == "inference":
        return bool(trusts)
    return fact_class == "unknown"


def _component_failure(
    proposal: ComponentChangeProposal,
    bases: tuple[CandidateBasis, ...],
    current: dict[CandidateOwner, tuple[int, bytes]],
) -> str | None:
    owner = CandidateOwner(proposal.payload.owner)
    expected = current.get(owner)
    if expected is None:
        return "CANDIDATE-OWNER-NOT-ACTIVE"
    version, current_bytes = expected
    if proposal.payload.expected_version != version:
        return "CANDIDATE-VERSION-MISMATCH"
    if not any(
        basis.item_kind == owner.value
        and basis.source_version == version
        and basis.source_digest == Digest.from_bytes(current_bytes)
        for basis in bases
    ):
        return "CANDIDATE-COMPONENT-BASIS"
    next_state = proposal.payload.next_state.model_dump(mode="json")
    schema_owner = {
        "armi.self.v1": CandidateOwner.SELF,
        "armi.mind.v1": CandidateOwner.MIND,
        "armi.life-mode.v1": CandidateOwner.LIFE_MODE,
    }.get(str(next_state.get("schema_version")))
    if schema_owner is not owner:
        return "CANDIDATE-OWNER-MISMATCH"
    next_bytes = rfc8785.dumps(cast(Any, next_state))
    if next_bytes == current_bytes:
        return "CANDIDATE-NO-OP"
    if owner is CandidateOwner.LIFE_MODE:
        return "CANDIDATE-LIFE-MODE-TRANSITION-NOT-ACTIVE"
    return None


def _capability_failure(
    proposal: Any,
    bases: tuple[CandidateBasis, ...],
    *,
    context: CandidateValidationContext,
) -> str | None:
    payload = proposal.payload
    if payload.fact_class not in {"subjective_understanding", "inference"}:
        return "CANDIDATE-CAPABILITY-FACT"
    if not any(
        basis.section == "capability"
        and basis.item_kind == "capability_catalog"
        and basis.trust_class == "policy"
        for basis in bases
    ):
        return "CANDIDATE-CAPABILITY-BASIS"
    if not any(
        basis.item_kind == "current_scene" and basis.source_ref == context.scene_id
        for basis in bases
    ):
        return "CANDIDATE-CAPABILITY-SCENE-BASIS"
    if not any(
        basis.item_kind in {"current_evidence", "codex_task_source"}
        and basis.trust_class == "external_claim"
        for basis in bases
    ):
        return "CANDIDATE-CAPABILITY-EVIDENCE-BASIS"
    if payload.capability_kind == "creator.scene.reply":
        if isinstance(payload, CreatorSceneReplyRequestPayload) and (
            UUID(payload.subject_id) != context.subject_id
            or UUID(payload.scene_id) != context.scene_id
            or UUID(payload.creator_party_id) != context.creator_party_id
        ):
            return "CANDIDATE-CAPABILITY-SCOPE"
        return None
    if payload.capability_kind == "codex.delegated-work":
        capability_states = tuple(
            basis for basis in bases if basis.item_kind.startswith("capability_state_")
        )
        if capability_states:
            if (
                len(capability_states) != 1
                or capability_states[0].section != "capability"
                or capability_states[0].trust_class != "runtime_authority"
                or capability_states[0].source_ref != _CODEX_CAPABILITY_ID
            ):
                return "CANDIDATE-CAPABILITY-STATE-BASIS"
            status = capability_states[0].item_kind.removeprefix("capability_state_")
            if status in {"pending", "granted", "limited"}:
                return "CANDIDATE-CAPABILITY-DUPLICATE"
            if status not in {"unauthorized", "denied", "revoked", "expired"}:
                return "CANDIDATE-CAPABILITY-STATE"
        return None
    return "CANDIDATE-CAPABILITY-UNKNOWN"


def _action_failure(
    proposal: Any,
    bases: tuple[CandidateBasis, ...],
    *,
    context: CandidateValidationContext,
) -> str | None:
    payload = proposal.payload
    if payload.fact_class not in {"subjective_understanding", "inference"}:
        return "CANDIDATE-ACTION-FACT"
    if not any(
        basis.item_kind == "current_scene" and basis.source_ref == context.scene_id
        for basis in bases
    ):
        return "CANDIDATE-ACTION-SCENE-BASIS"
    if not any(
        basis.item_kind == "current_evidence" and basis.trust_class == "external_claim"
        for basis in bases
    ):
        return "CANDIDATE-ACTION-EVIDENCE-BASIS"
    if isinstance(payload, (CreatorReplyPayload, RuntimeBoundCreatorReplyPayload)):
        if (
            context.current_relationship is not None
            and context.current_relationship.status is RelationshipStatus.ENDED
        ):
            return "CANDIDATE-RELATIONSHIP-BOUNDARY"
        if not any(
            basis.section == "capability"
            and basis.item_kind == "capability_catalog"
            and basis.trust_class == "policy"
            for basis in bases
        ):
            return "CANDIDATE-ACTION-CAPABILITY-BASIS"
        if isinstance(payload, CreatorReplyPayload) and (
            UUID(payload.subject_id) != context.subject_id
            or UUID(payload.scene_id) != context.scene_id
            or UUID(payload.creator_party_id) != context.creator_party_id
        ):
            return "CANDIDATE-ACTION-SCOPE"
        return None
    expected_reason = {
        "decline": "subjective_refusal",
        "no_action": "subjective_silence",
    }[payload.decision]
    return (
        None
        if payload.reason_class == expected_reason
        else "CANDIDATE-NO-ACTION-REASON"
    )


def _web_research_failure(
    proposal: WebResearchRequestProposal,
    bases: tuple[CandidateBasis, ...],
    *,
    active: bool,
    purpose: str,
) -> str | None:
    if not active:
        return "CANDIDATE-WEB-NOT-ACTIVE"
    if purpose != "consider_creator_input":
        return "CANDIDATE-WEB-RECURSION-FORBIDDEN"
    if proposal.payload.fact_class not in {"subjective_understanding", "inference"}:
        return "CANDIDATE-WEB-FACT"
    if not any(
        basis.item_kind == "current_evidence" and basis.trust_class == "external_claim"
        for basis in bases
    ):
        return "CANDIDATE-WEB-EVIDENCE-BASIS"
    if not any(
        basis.item_kind == "current_purpose" and basis.trust_class == "policy"
        for basis in bases
    ):
        return "CANDIDATE-WEB-PURPOSE-BASIS"
    if not any(
        basis.item_kind == "web_search_availability" and basis.trust_class == "policy"
        for basis in bases
    ):
        return "CANDIDATE-WEB-AVAILABILITY-BASIS"
    lowered = proposal.payload.query.casefold()
    if "http://" in lowered or "https://" in lowered:
        return "CANDIDATE-WEB-URL-FORBIDDEN"
    return None


def _codex_delegation_failure(
    payload: CodexDelegationPayload,
    bases: tuple[CandidateBasis, ...],
    *,
    context: CandidateValidationContext,
) -> str | None:
    if not context.codex_active:
        return "CANDIDATE-CODEX-NOT-ACTIVE"
    source_id = UUID(payload.task_source_id)
    source = next(
        (item for item in context.codex_task_sources if item[0] == source_id),
        None,
    )
    if source is None:
        return "CANDIDATE-CODEX-TASK-SOURCE"
    if (
        source[1].value != payload.task_manifest_digest
        or source[2] != payload.validator_id
    ):
        return "CANDIDATE-CODEX-TASK-IDENTITY"
    if not any(
        basis.item_kind == "codex_task_source"
        and basis.source_ref == source_id
        and basis.source_digest == source[1]
        for basis in bases
    ):
        return "CANDIDATE-CODEX-TASK-BASIS"
    if not any(
        basis.section == "capability"
        and basis.item_kind == "capability_catalog"
        and basis.trust_class == "policy"
        for basis in bases
    ):
        return "CANDIDATE-CODEX-CAPABILITY-BASIS"
    return None


def _attention_transition_allowed(
    status: ActivityStatus, decision: ActivityAttentionDecisionKind
) -> bool:
    passive = {
        ActivityAttentionDecisionKind.NO_ACTION,
        ActivityAttentionDecisionKind.DEFER,
        ActivityAttentionDecisionKind.NEED_INFORMATION,
    }
    if decision in passive:
        return status in {
            ActivityStatus.READY,
            ActivityStatus.IN_PROGRESS,
            ActivityStatus.WAITING,
            ActivityStatus.PAUSED,
            ActivityStatus.RESUMING,
        }
    return decision in {
        ActivityStatus.READY: {ActivityAttentionDecisionKind.ENGAGE},
        ActivityStatus.IN_PROGRESS: {
            ActivityAttentionDecisionKind.PROGRESS,
            ActivityAttentionDecisionKind.WAIT,
            ActivityAttentionDecisionKind.PAUSE,
            ActivityAttentionDecisionKind.COMPLETE,
            ActivityAttentionDecisionKind.ABANDON,
        },
        ActivityStatus.WAITING: {ActivityAttentionDecisionKind.RESUME},
        ActivityStatus.PAUSED: {ActivityAttentionDecisionKind.RESUME},
        ActivityStatus.RESUMING: {ActivityAttentionDecisionKind.ENGAGE},
    }.get(status, set())


def _rejected(code: str) -> CandidateValidationResult:
    return CandidateValidationResult(
        CandidateValidationId(uuid7()),
        CandidateValidationStatus.REJECTED,
        None,
        0,
        0,
        code,
    )


def _primary_rejection(rejected: dict[str, CandidateRejection]) -> str:
    return (
        sorted(value.code for value in rejected.values())[0]
        if rejected
        else "CANDIDATE-NO-VALID-PROPOSAL"
    )


def _draft_owner(
    draft: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateMemoryRevisionDraft
    | CandidateRelationshipDraft
    | CandidateLifeMaterialDraft
    | CandidateSubjectPromptDraft
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft,
) -> CandidateOwner:
    if isinstance(draft, CandidateExperienceDraft):
        return CandidateOwner.EXPERIENCE
    if isinstance(draft, (CandidateMemoryDraft, CandidateMemoryRevisionDraft)):
        return CandidateOwner.MEMORY
    if isinstance(draft, CandidateRelationshipDraft):
        return CandidateOwner.RELATIONSHIP
    if isinstance(draft, CandidateLifeMaterialDraft):
        return CandidateOwner.MATERIAL
    if isinstance(draft, CandidateSubjectPromptDraft):
        return CandidateOwner.PROMPT
    if isinstance(draft, CapabilityRequestDraft):
        return CandidateOwner.CAPABILITY
    if isinstance(draft, (CreatorReplyDraft, FormalNoActionDraft)):
        return CandidateOwner.ACTION
    if isinstance(draft, WebResearchRequestDraft):
        return CandidateOwner.WEB_RESEARCH
    if isinstance(draft, CodexDelegationDraft):
        return CandidateOwner.CODEX_DELEGATION
    return draft.owner


def _draft_fact_class(
    draft: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateMemoryRevisionDraft
    | CandidateRelationshipDraft
    | CandidateLifeMaterialDraft
    | CandidateSubjectPromptDraft
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft,
) -> CandidateFactClass:
    if isinstance(
        draft, (CapabilityRequestDraft, CreatorReplyDraft, FormalNoActionDraft)
    ):
        return CandidateFactClass.INFERENCE
    if isinstance(draft, (WebResearchRequestDraft, CodexDelegationDraft)):
        return CandidateFactClass.INFERENCE
    if isinstance(draft, CandidateLifeMaterialDraft):
        return CandidateFactClass.SUBJECTIVE_UNDERSTANDING
    if isinstance(draft, CandidateSubjectPromptDraft):
        return draft.fact_class
    return draft.fact_class


def _experience_wire(value: CandidateExperienceDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "first_person_gist": value.first_person_gist,
        "uncertainty": value.uncertainty,
        "privacy_scope": value.privacy_scope,
    }


def _memory_wire(value: CandidateMemoryDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "source_experience_ref": value.source_experience_ref,
        "source_kind": value.source_kind.value,
        "summary": value.summary,
        "mechanism_identity": value.mechanism_identity,
        "privacy_scope": value.privacy_scope,
    }


def _memory_revision_wire(
    value: CandidateMemoryRevisionDraft,
) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "memory_id": str(value.memory_id),
        "current_revision_id": str(value.current_revision_id),
        "expected_head_version": value.expected_head_version,
        "revision_kind": value.revision_kind.value,
        "accessibility": value.accessibility.value,
        "source_kind": value.source_kind.value,
        "summary": value.summary,
        "uncertainty": value.uncertainty,
        "related_memory_id": (
            None if value.related_memory_id is None else str(value.related_memory_id)
        ),
        "relation_kind": (
            None if value.relation_kind is None else value.relation_kind.value
        ),
        "mechanism_identity": value.mechanism_identity,
        "mechanism_config_identity": value.mechanism_config_identity,
        "privacy_scope": value.privacy_scope,
    }


def _relationship_wire(value: CandidateRelationshipDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "relationship_id": str(value.relationship_id),
        "subject_party_id": str(value.subject_party_id),
        "other_party_id": str(value.other_party_id),
        "current_revision_id": (
            None
            if value.current_revision_id is None
            else str(value.current_revision_id)
        ),
        "expected_head_version": value.expected_head_version,
        "source_experience_ref": value.source_experience_ref,
        "facts": [
            {"kind": item.kind.value, "summary": item.summary} for item in value.facts
        ],
        "interpretation": value.interpretation,
        "boundaries": [
            {
                "party_role": item.party_role.value,
                "kind": item.kind.value,
                "action": item.action.value,
                "summary": item.summary,
            }
            for item in value.boundaries
        ],
        "commitments": [
            {
                "commitment_id": str(item.commitment_id),
                "party_role": item.party_role.value,
                "scope": item.scope,
                "content": item.content,
                "status": item.status.value,
                "last_event_kind": item.last_event_kind.value,
                "last_event_summary": item.last_event_summary,
            }
            for item in value.commitments
        ],
        "open_issues": [
            {
                "issue_id": str(item.issue_id),
                "kind": item.kind.value,
                "commitment_ids": [str(value) for value in item.commitment_ids],
                "summary": item.summary,
                "status": item.status.value,
            }
            for item in value.open_issues
        ],
        "commitment_event": (
            None
            if value.commitment_event is None
            else {
                "commitment_id": str(value.commitment_event.commitment_id),
                "kind": value.commitment_event.kind.value,
                "summary": value.commitment_event.summary,
                "related_commitment_id": (
                    None
                    if value.commitment_event.related_commitment_id is None
                    else str(value.commitment_event.related_commitment_id)
                ),
            }
        ),
        "status": value.status.value,
        "scope": value.scope,
        "mechanism_identity": value.mechanism_identity,
        "privacy_scope": value.privacy_scope,
    }


def _material_wire(value: CandidateLifeMaterialDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "material_id": str(value.material_id),
        "owner_party_id": str(value.owner_party_id),
        "material_kind": value.material_kind.value,
        "current_revision_id": (
            None
            if value.current_revision_id is None
            else str(value.current_revision_id)
        ),
        "expected_head_version": value.expected_head_version,
        "title": value.title,
        "body": (
            None
            if value.body_bytes is None
            else value.body_bytes.decode("utf-8", errors="strict")
        ),
        "body_digest": value.body_digest.value,
        "metadata": dict(value.metadata),
        "material_status": value.material_status.value,
        "privacy_status": value.privacy_status,
        "revision_kind": value.revision_kind.value,
        "source_kind": value.source_kind,
    }


def _memory_source_kind(
    fact_class: CandidateFactClass,
    *,
    purpose: str,
) -> MemorySourceKind:
    if fact_class is CandidateFactClass.INFERENCE:
        return MemorySourceKind.INFERRED
    if fact_class is CandidateFactClass.UNKNOWN:
        return MemorySourceKind.UNKNOWN
    if purpose in {"consider_web_evidence", "consider_codex_result"}:
        return MemorySourceKind.QUERIED
    if fact_class is CandidateFactClass.EXTERNAL_CLAIM:
        return MemorySourceKind.REPORTED
    return MemorySourceKind.EXPERIENCED


def _activity_wire(value: CandidateActivityDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "activity_id": str(value.activity_id),
        "activity_kind": value.activity_kind,
        "goal": value.goal,
        "next_safe_step": value.next_safe_step,
        "status": value.status.value,
        "privacy_scope": value.privacy_scope,
    }


def _activity_decision_wire(
    value: CandidateActivityDecisionDraft,
) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "activity_id": str(value.activity_id),
        "current_revision_id": str(value.current_revision_id),
        "expected_head_version": value.expected_head_version,
        "resource_snapshot_digest": value.resource_snapshot_digest.value,
        "decision_kind": value.decision_kind.value,
        "progress_summary": value.progress_summary,
        "next_safe_step": value.next_safe_step,
        "waiting_summary": value.waiting_summary,
        "resumption_cue": value.resumption_cue,
        "waiting_kind": (
            None if value.waiting_kind is None else value.waiting_kind.value
        ),
        "delay_seconds": value.delay_seconds,
        "terminal_reason": value.terminal_reason,
    }


def _sleep_decision_wire(value: CandidateSleepDecisionDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "decision_kind": value.decision_kind.value,
        "cycle_anchor_ref": str(value.cycle_anchor_ref),
        "source_digest": value.source_digest.value,
    }


def _web_research_wire(value: WebResearchRequestDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "purpose": value.purpose,
        "operation_class": value.operation_class,
        "query": value.query_bytes.decode("utf-8", errors="strict"),
        "query_digest": value.query_digest.value,
    }


def _codex_delegation_wire(value: CodexDelegationDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "task_source_id": str(value.task_source_id.value),
        "task_manifest_digest": value.task_manifest_digest.value,
        "validator_id": value.validator_id,
        "capability_kind": value.capability_kind,
        "operation": value.operation,
        "purpose": value.purpose,
    }


def _component_wire(value: CandidateComponentDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "owner": value.owner.value,
        "expected_version": value.expected_version,
        "next_state": json.loads(value.canonical_next_state),
        "next_state_digest": value.next_state_digest.value,
    }


def _prompt_wire(value: CandidateSubjectPromptDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "prompt_document_id": str(value.prompt_document_id),
        "current_revision_id": (
            None
            if value.current_revision_id is None
            else str(value.current_revision_id)
        ),
        "expected_revision_no": value.expected_revision_no,
        "content": json.loads(value.content_bytes),
        "content_digest": value.content_digest.value,
    }


def _capability_wire(value: CapabilityRequestDraft) -> dict[str, object]:
    scope = value.scope
    if isinstance(scope, CreatorSceneReplyScope):
        scope_value: dict[str, object] = {
            "subject_id": str(scope.subject_id),
            "scene_id": str(scope.scene_id),
            "creator_party_id": str(scope.creator_party_id),
            "audience_scope": scope.audience_scope,
            "data_scope": scope.data_scope,
            "purpose": scope.purpose,
            "valid_for_seconds": scope.valid_for_seconds,
            "max_uses": scope.max_uses,
            "max_payload_bytes": scope.max_payload_bytes,
        }
    else:
        scope_value = {
            "workspace_scope": scope.workspace_scope,
            "artifact_scope": scope.artifact_scope,
            "network_access": scope.network_access,
            "max_uses": scope.max_uses,
            "valid_for_seconds": scope.valid_for_seconds,
        }
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "capability_kind": value.capability.value,
        "operation": value.operation.value,
        "scope": scope_value,
    }


def _rejection_wire(value: CandidateRejection) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "owner": value.owner.value,
        "code": value.code,
    }


def _action_wire(value: CreatorReplyDraft | FormalNoActionDraft) -> dict[str, object]:
    common: dict[str, object] = {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
    }
    if isinstance(value, CreatorReplyDraft):
        return {
            **common,
            "action_kind": "creator_reply",
            "subject_id": str(value.subject_id),
            "scene_id": str(value.scene_id),
            "creator_party_id": str(value.creator_party_id),
            "capability_kind": value.capability_kind,
            "operation": value.operation,
            "audience_scope": value.audience_scope,
            "data_scope": value.data_scope,
            "purpose": value.purpose,
            "media_type": value.media_type,
            "content": value.content_bytes.decode("utf-8"),
            "content_digest": value.content_digest.value,
        }
    return {
        **common,
        "action_kind": "formal_no_action",
        "decision": value.kind.value,
        "reason_class": value.reason.value,
    }


__all__ = (
    "ACTIVITY_CHANGE_SET_VERSION",
    "CANDIDATE_POLICY_VERSION",
    "CANDIDATE_VALIDATOR_IDENTITY",
    "CHANGE_SET_VERSION",
    "CODEX_CHANGE_SET_VERSION",
    "MATERIAL_CHANGE_SET_VERSION",
    "PROMPT_CHANGE_SET_VERSION",
    "RUNTIME_BOUND_CHANGE_SET_VERSION",
    "CandidateLifeMaterialContext",
    "CandidateMemoryContext",
    "CandidateRelationshipContext",
    "CandidateSubjectPromptContext",
    "CandidateValidationContext",
    "DeterministicCandidateValidator",
)
