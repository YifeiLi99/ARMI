"""Deterministic S025 candidate validation without authority to commit state."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    CandidateBasis,
    CandidateComponentDraft,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwner,
    CandidateRejection,
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
    ModelViolation,
    SubjectChangeSet,
    WebResearchRequestDraft,
)
from armi_kernel.contracts import Digest

from .model_contract import (
    ActionChoiceProposal,
    CodexDelegationPayload,
    CognitionCandidate,
    CognitionCandidateV5,
    CognitionCandidateV6,
    ComponentChangeProposal,
    CreatorReplyPayload,
    ExperienceProposal,
    FormalNoActionPayload,
    WebResearchRequestProposal,
    parse_candidate,
)

CANDIDATE_POLICY_VERSION = "armi.cognition-candidate-policy.v1"
CANDIDATE_VALIDATOR_IDENTITY = "armi.candidate-validator.deterministic-v1"
CHANGE_SET_VERSION = "armi.subject-change-set.v3"
WEB_CHANGE_SET_VERSION = "armi.subject-change-set.v4"
CODEX_CHANGE_SET_VERSION = "armi.subject-change-set.v5"


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
    scene_id: UUID
    creator_party_id: UUID
    current_components: tuple[tuple[CandidateOwner, int, bytes], ...]
    purpose: str = "consider_creator_input"
    web_search_active: bool = False
    codex_active: bool = False
    codex_task_sources: tuple[tuple[UUID, Digest, str], ...] = ()

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (
                self.subject_id,
                self.generation_id,
                self.episode_id,
                self.model_attempt_id,
                self.bundle_activation_id,
                self.scene_id,
                self.creator_party_id,
            )
        ):
            raise CandidateViolation("CON-CANDIDATE-CONTEXT")
        if (
            type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
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
            candidate = parse_candidate(
                candidate_bytes,
                allowed_context_refs=frozenset(basis_by_ref),
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
            rfc8785.dumps(cast(Any, candidate.model_dump(mode="json")))
        )
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
                            UUID(payload.subject_id),
                            UUID(payload.scene_id),
                            UUID(payload.creator_party_id),
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
                if failure is None and isinstance(action.payload, CreatorReplyPayload):
                    content = action.payload.content.encode("utf-8", errors="strict")
                    accepted[proposal.proposal_ref] = CreatorReplyDraft(
                        proposal.proposal_ref,
                        proposal.atomic_group_ref,
                        tuple(basis.ordinal for basis in proposal_bases),
                        UUID(action.payload.subject_id),
                        UUID(action.payload.scene_id),
                        UUID(action.payload.creator_party_id),
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

        for proposal_ref, draft in tuple(accepted.items()):
            if (
                isinstance(draft, CandidateComponentDraft)
                and draft.atomic_group_ref not in group_experiences
            ):
                rejected[proposal_ref] = CandidateRejection(
                    proposal_ref,
                    draft.atomic_group_ref,
                    draft.basis_ordinals,
                    draft.fact_class,
                    draft.owner,
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
        change_set_value = {
            "schema_version": (
                CODEX_CHANGE_SET_VERSION
                if candidate.schema_version == "armi.cognition-candidate.v6"
                else WEB_CHANGE_SET_VERSION
                if candidate.schema_version == "armi.cognition-candidate.v5"
                else CHANGE_SET_VERSION
            ),
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
        if candidate.schema_version == "armi.cognition-candidate.v5":
            change_set_value["web_research_requests"] = [
                _web_research_wire(item) for item in web_research_requests
            ]
        if candidate.schema_version == "armi.cognition-candidate.v6":
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

    def _base_matches(
        self,
        candidate: CognitionCandidate | CognitionCandidateV5 | CognitionCandidateV6,
    ) -> bool:
        base = candidate.base
        return (
            base.subject_version == self._context.base_subject_version
            and base.state_epoch == self._context.base_state_epoch
            and base.bundle_activation_id == str(self._context.bundle_activation_id)
            and base.context_digest == self._context.context_digest.value
        )


def _all_proposals(
    candidate: CognitionCandidate | CognitionCandidateV5 | CognitionCandidateV6,
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
        basis.item_kind == owner.value and basis.source_version == version
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
        if (
            UUID(payload.subject_id) != context.subject_id
            or UUID(payload.scene_id) != context.scene_id
            or UUID(payload.creator_party_id) != context.creator_party_id
        ):
            return "CANDIDATE-CAPABILITY-SCOPE"
        return None
    if payload.capability_kind == "codex.delegated-work":
        return None
    return "CANDIDATE-CAPABILITY-UNKNOWN"


def _action_failure(
    proposal: ActionChoiceProposal,
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
    if isinstance(payload, CreatorReplyPayload):
        if not any(
            basis.section == "capability"
            and basis.item_kind == "capability_catalog"
            and basis.trust_class == "policy"
            for basis in bases
        ):
            return "CANDIDATE-ACTION-CAPABILITY-BASIS"
        if (
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
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft,
) -> CandidateOwner:
    if isinstance(draft, CandidateExperienceDraft):
        return CandidateOwner.EXPERIENCE
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
    "CANDIDATE_POLICY_VERSION",
    "CANDIDATE_VALIDATOR_IDENTITY",
    "CHANGE_SET_VERSION",
    "CODEX_CHANGE_SET_VERSION",
    "CandidateValidationContext",
    "DeterministicCandidateValidator",
)
