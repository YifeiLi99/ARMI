"""Technology-neutral cognition candidate validation contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

_CODE = re.compile(r"^(?:CON|CANDIDATE)-[A-Z0-9-]+$", re.ASCII)
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$", re.ASCII)


class CandidateDisposition(StrEnum):
    CHANGE = "change"
    NO_CHANGE = "no_change"
    DEFER = "defer"
    DECLINE = "decline"
    NO_ACTION = "no_action"
    NEED_INFORMATION = "need_information"


class CandidateFactClass(StrEnum):
    OBJECTIVE_FACT = "objective_fact"
    EXTERNAL_CLAIM = "external_claim"
    SUBJECTIVE_UNDERSTANDING = "subjective_understanding"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class CandidateOwnerIdentity(str):
    """Validated opaque owner token; the kernel does not enumerate owners."""

    def __new__(cls, value: str) -> CandidateOwnerIdentity:
        if type(value) is not str or _TOKEN.fullmatch(value) is None:
            raise CandidateViolation("CON-CANDIDATE-OWNER")
        return str.__new__(cls, value)

    @property
    def value(self) -> str:
        return str(self)


class CandidateViolation(RuntimeError):
    """Expose a stable candidate failure without candidate content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("candidate violation code is invalid")
        self.code = code
        super().__init__("cognition candidate validation failed")

    def __str__(self) -> str:
        return f"{self.code}: cognition candidate validation failed"


@dataclass(frozen=True, slots=True)
class CandidateValidationId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise CandidateViolation("CON-CANDIDATE-VALIDATION-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CandidateBasis:
    ordinal: int
    section: str
    item_kind: str
    source_ref: UUID | None
    source_version: int | None
    trust_class: str
    privacy_scope: str

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 999
            or type(self.section) is not str
            or _TOKEN.fullmatch(self.section) is None
            or type(self.item_kind) is not str
            or _TOKEN.fullmatch(self.item_kind) is None
            or type(self.trust_class) is not str
            or self.trust_class
            not in {"runtime_authority", "subjective_state", "external_claim", "policy"}
            or type(self.privacy_scope) is not str
            or self.privacy_scope not in {"internal", "private", "restricted"}
        ):
            raise CandidateViolation("CON-CANDIDATE-BASIS")
        identity = (self.source_ref, self.source_version)
        if all(value is None for value in identity):
            return
        if (
            type(self.source_ref) is not UUID
            or self.source_ref.version != 7
            or type(self.source_version) is not int
            or self.source_version < 0
        ):
            raise CandidateViolation("CON-CANDIDATE-BASIS")


@dataclass(frozen=True, slots=True)
class CandidateExperienceDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    first_person_gist: str
    uncertainty: str | None
    privacy_scope: str

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or type(self.first_person_gist) is not str
            or not 1 <= len(self.first_person_gist) <= 1024
            or (
                self.uncertainty is not None
                and (
                    type(self.uncertainty) is not str
                    or not 1 <= len(self.uncertainty) <= 512
                )
            )
            or self.privacy_scope != "private"
        ):
            raise CandidateViolation("CON-CANDIDATE-EXPERIENCE")


@dataclass(frozen=True, slots=True)
class CandidateOwnerDraft:
    """Opaque proposal handed from a business owner to the subject pipeline."""

    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    owner: str
    canonical_payload: bytes

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or type(self.owner) is not str
            or _TOKEN.fullmatch(self.owner) is None
            or type(self.canonical_payload) is not bytes
            or not self.canonical_payload
        ):
            raise CandidateViolation("CON-CANDIDATE-OWNER-DRAFT")


@dataclass(frozen=True, slots=True)
class CandidateRejection:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    owner: CandidateOwnerIdentity
    code: str

    def __post_init__(self) -> None:
        if (
            _REF.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.fact_class) is not CandidateFactClass
            or type(self.owner) is not CandidateOwnerIdentity
            or _CODE.fullmatch(self.code) is None
        ):
            raise CandidateViolation("CON-CANDIDATE-REJECTION")
        _validate_proposal(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
        )


def _validate_proposal(
    proposal_ref: str,
    atomic_group_ref: str,
    basis_ordinals: tuple[int, ...],
) -> None:
    if (
        type(proposal_ref) is not str
        or _REF.fullmatch(proposal_ref) is None
        or type(atomic_group_ref) is not str
        or _GROUP.fullmatch(atomic_group_ref) is None
        or type(basis_ordinals) is not tuple
        or not 1 <= len(basis_ordinals) <= 8
        or any(
            type(value) is not int or not 1 <= value <= 999 for value in basis_ordinals
        )
        or len(set(basis_ordinals)) != len(basis_ordinals)
    ):
        raise CandidateViolation("CON-CANDIDATE-PROPOSAL")


__all__ = (
    "CandidateBasis",
    "CandidateDisposition",
    "CandidateExperienceDraft",
    "CandidateFactClass",
    "CandidateOwnerDraft",
    "CandidateOwnerIdentity",
    "CandidateRejection",
    "CandidateValidationId",
    "CandidateViolation",
)
