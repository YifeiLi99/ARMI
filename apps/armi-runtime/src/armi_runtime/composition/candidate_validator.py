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
    ModelViolation,
    SubjectChangeSet,
)
from armi_kernel.contracts import Digest

from .model_contract import (
    CognitionCandidate,
    ComponentChangeProposal,
    ExperienceProposal,
    parse_candidate,
)

CANDIDATE_POLICY_VERSION = "armi.cognition-candidate-policy.v1"
CANDIDATE_VALIDATOR_IDENTITY = "armi.candidate-validator.deterministic-v1"
CHANGE_SET_VERSION = "armi.subject-change-set.v1"


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
    current_components: tuple[tuple[CandidateOwner, int, bytes], ...]

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
        if (
            type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-CONTEXT")


class DeterministicCandidateValidator:
    """Validate candidate v2 into a canonical, not-yet-effective change set."""

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
                and raw.get("schema_version") == "armi.cognition-candidate.v1"
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
        if candidate.disposition != "change" and proposals:
            return _rejected("CANDIDATE-DISPOSITION")

        component_state = {
            owner: (version, canonical)
            for owner, version, canonical in self._context.current_components
        }
        accepted: dict[str, CandidateExperienceDraft | CandidateComponentDraft] = {}
        rejected: dict[str, CandidateRejection] = {}
        group_members: dict[str, list[str]] = defaultdict(list)
        group_experiences: set[str] = set()

        for owner, proposal in proposals:
            group_members[proposal.atomic_group_ref].append(proposal.proposal_ref)
            proposal_bases = tuple(basis_by_ref[ref] for ref in proposal.basis_refs)
            failure = _basis_failure(owner, proposal_bases, proposal.payload.fact_class)
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

        failed_groups = {rejection.atomic_group_ref for rejection in rejected.values()}
        for group in failed_groups:
            for proposal_ref in group_members[group]:
                draft = accepted.pop(proposal_ref, None)
                if draft is not None:
                    rejected[proposal_ref] = CandidateRejection(
                        proposal_ref,
                        group,
                        draft.basis_ordinals,
                        draft.fact_class,
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
        rejections = tuple(value for _, value in sorted(rejected.items()))
        disposition = CandidateDisposition(candidate.disposition)
        change_set_value = {
            "schema_version": CHANGE_SET_VERSION,
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
            "rejections": [_rejection_wire(item) for item in rejections],
        }
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
            rejections,
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

    def _base_matches(self, candidate: CognitionCandidate) -> bool:
        base = candidate.base
        return (
            base.subject_version == self._context.base_subject_version
            and base.state_epoch == self._context.base_state_epoch
            and base.bundle_activation_id == str(self._context.bundle_activation_id)
            and base.context_digest == self._context.context_digest.value
        )


def _all_proposals(
    candidate: CognitionCandidate,
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
        *((CandidateOwner.ACTION, item) for item in candidate.action_intents),
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
    draft: CandidateExperienceDraft | CandidateComponentDraft,
) -> CandidateOwner:
    return (
        CandidateOwner.EXPERIENCE
        if isinstance(draft, CandidateExperienceDraft)
        else draft.owner
    )


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


def _rejection_wire(value: CandidateRejection) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "owner": value.owner.value,
        "code": value.code,
    }


__all__ = (
    "CANDIDATE_POLICY_VERSION",
    "CANDIDATE_VALIDATOR_IDENTITY",
    "CHANGE_SET_VERSION",
    "CandidateValidationContext",
    "DeterministicCandidateValidator",
)
