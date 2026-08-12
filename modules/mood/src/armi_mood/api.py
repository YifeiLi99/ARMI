"""Stable public contract of the mood owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLTransaction


class MoodViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MOOD-"):
            raise ValueError("mood violation code is invalid")
        self.code = code
        super().__init__("mood operation failed")

    def __str__(self) -> str:
        return f"{self.code}: mood operation failed"


@dataclass(frozen=True, slots=True)
class CandidateMoodDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    expected_version: int
    canonical_next_state: bytes

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class MoodHead:
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class MoodAdminComponent:
    kind: str
    version: int
    privacy_scope: str
    payload: object | None


@dataclass(frozen=True, slots=True)
class MoodCorrectionHead:
    current_revision_id: UUID
    current_version: int
    current_payload: object
    maximum_version: int


@runtime_checkable
class MoodReadPort(Protocol):
    async def current(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodHead: ...

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...


def default_mood_read() -> MoodReadPort:
    from ._application import MoodApplication
    from ._postgresql import PostgreSQLMoodOwner

    return PostgreSQLMoodOwner(MoodApplication())


@runtime_checkable
class MoodCognitionPort(Protocol):
    def bind(self, value: CandidateMoodDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateMoodDraft: ...


def default_mood_cognition() -> MoodCognitionPort:
    from ._application import MoodApplication

    return MoodApplication()


@runtime_checkable
class MoodCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...


@runtime_checkable
class MoodBirthPort(Protocol):
    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


def default_mood_birth() -> MoodBirthPort:
    from ._application import MoodApplication
    from ._postgresql import PostgreSQLMoodOwner

    return PostgreSQLMoodOwner(MoodApplication())


@runtime_checkable
class MoodAdminReadPort(Protocol):
    def current_component(self, *, private: bool) -> MoodAdminComponent | None: ...


@runtime_checkable
class MoodAdminCorrectionPort(Protocol):
    def current_head(
        self,
        transaction: Any,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> MoodCorrectionHead | None: ...

    def revision(
        self,
        transaction: Any,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
    ) -> tuple[UUID, int] | None: ...

    def replace(
        self,
        transaction: Any,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
        version: int,
        previous_revision_id: str,
        replacement: object,
    ) -> bool: ...

    def repair_head(
        self,
        transaction: Any,
        *,
        subject_id: str,
        kind: str,
        current_revision_id: str,
        current_version: int,
        target_revision_id: str,
        target_version: int,
    ) -> bool: ...

    def find_current(
        self, transaction: Any, *, kind: str
    ) -> tuple[UUID, int] | None: ...


__all__ = (
    "CandidateMoodDraft",
    "MoodAdminComponent",
    "MoodAdminCorrectionPort",
    "MoodAdminReadPort",
    "MoodBirthPort",
    "MoodCognitionPort",
    "MoodCommitPort",
    "MoodCorrectionHead",
    "MoodHead",
    "MoodReadPort",
    "MoodViolation",
    "default_mood_birth",
    "default_mood_cognition",
    "default_mood_read",
)
