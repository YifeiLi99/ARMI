"""Candidate validation results owned by the cognition module."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_capability.api import CapabilityRequestDraft
from armi_expression.api import ResponseChoiceDraft
from armi_kernel.application import (
    CandidateBasis,
    CandidateDisposition,
    CandidateExactLifeQueryDraft,
    CandidateExperienceDraft,
    CandidateOwnerDraft,
    CandidateRejection,
    CandidateValidationId,
    CandidateViolation,
    CodexDelegationDraft,
)
from armi_kernel.contracts import Digest
from armi_web_observation.api import WebResearchRequestDraft

_CODE = re.compile(r"^(?:CON|CANDIDATE)-[A-Z0-9-]+$", re.ASCII)


class CandidateValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SubjectChangeSet:
    canonical_bytes: bytes
    subject_id: UUID
    generation_id: UUID
    episode_id: UUID
    model_attempt_id: UUID
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    disposition: CandidateDisposition
    experiences: tuple[CandidateExperienceDraft, ...]
    capability_requests: tuple[CapabilityRequestDraft, ...]
    action_choices: tuple[ResponseChoiceDraft, ...]
    web_research_requests: tuple[WebResearchRequestDraft, ...]
    rejections: tuple[CandidateRejection, ...]
    codex_delegations: tuple[CodexDelegationDraft, ...] = ()
    owner_drafts: tuple[CandidateOwnerDraft, ...] = ()
    exact_life_queries: tuple[CandidateExactLifeQueryDraft, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.canonical_bytes) is not bytes
            or not self.canonical_bytes
            or any(
                type(value) is not UUID or value.version != 7
                for value in (
                    self.subject_id,
                    self.generation_id,
                    self.episode_id,
                    self.model_attempt_id,
                    self.bundle_activation_id,
                )
            )
            or type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
            or type(self.disposition) is not CandidateDisposition
        ):
            raise CandidateViolation("CON-CANDIDATE-CHANGE-SET")


@dataclass(frozen=True, slots=True)
class CandidateValidationResult:
    validation_id: CandidateValidationId
    status: CandidateValidationStatus
    change_set: SubjectChangeSet | None
    accepted_count: int
    rejected_count: int
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            type(self.validation_id) is not CandidateValidationId
            or type(self.status) is not CandidateValidationStatus
            or type(self.accepted_count) is not int
            or self.accepted_count < 0
            or type(self.rejected_count) is not int
            or self.rejected_count < 0
        ):
            raise CandidateViolation("CON-CANDIDATE-RESULT")
        rejected = self.status is CandidateValidationStatus.REJECTED
        if rejected != (self.change_set is None):
            raise CandidateViolation("CON-CANDIDATE-RESULT")
        if rejected:
            if (
                type(self.error_code) is not str
                or _CODE.fullmatch(self.error_code) is None
            ):
                raise CandidateViolation("CON-CANDIDATE-RESULT")
        elif self.error_code is not None:
            raise CandidateViolation("CON-CANDIDATE-RESULT")


@runtime_checkable
class CandidateValidator(Protocol):
    def validate(
        self,
        candidate_bytes: bytes,
        *,
        bases: tuple[CandidateBasis, ...],
    ) -> CandidateValidationResult:
        """Validate untrusted model material without applying subject state."""
        ...


__all__ = (
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "SubjectChangeSet",
)
