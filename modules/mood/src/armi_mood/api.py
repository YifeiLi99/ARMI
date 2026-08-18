"""Stable public contract of the mood owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction


class MoodViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MOOD-"):
            raise ValueError("mood violation code is invalid")
        self.code = code
        super().__init__("mood operation failed")

    def __str__(self) -> str:
        return f"{self.code}: mood operation failed"


class EmotionFamily(StrEnum):
    JOY = "joy"
    CONTENTMENT = "contentment"
    INTEREST = "interest"
    HOPE = "hope"
    RELIEF = "relief"
    AFFECTION = "affection"
    GRATITUDE = "gratitude"
    PRIDE = "pride"
    SURPRISE = "surprise"
    SADNESS = "sadness"
    FEAR = "fear"
    ANXIETY = "anxiety"
    ANGER = "anger"
    FRUSTRATION = "frustration"
    DISGUST = "disgust"
    SHAME = "shame"
    GUILT = "guilt"
    JEALOUSY = "jealousy"
    BOREDOM = "boredom"
    CONFUSION = "confusion"


class MoodCandidateKind(StrEnum):
    EVENT = "event"
    HOME_BASE_REFLECTION = "home_base_reflection"


@dataclass(frozen=True, slots=True)
class VAD:
    valence: int
    arousal: int
    dominance: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or not -100 <= value <= 100
            for value in (self.valence, self.arousal, self.dominance)
        ):
            raise MoodViolation("MOOD-VAD")


@dataclass(frozen=True, slots=True)
class EmotionComponent:
    family: EmotionFamily
    nuance: str
    vad: VAD
    intensity: int

    def __post_init__(self) -> None:
        if (
            type(self.family) is not EmotionFamily
            or type(self.nuance) is not str
            or not self.nuance.strip()
            or self.nuance != self.nuance.strip()
            or "\x00" in self.nuance
            or len(self.nuance) > 64
            or type(self.intensity) is not int
            or not 5 <= self.intensity <= 100
            or self.intensity % 5
            or any(value % 5 for value in self.vad_values)
        ):
            raise MoodViolation("MOOD-COMPONENT")

    @property
    def vad_values(self) -> tuple[int, int, int]:
        return (self.vad.valence, self.vad.arousal, self.vad.dominance)


@dataclass(frozen=True, slots=True)
class AffectiveEvent:
    importance: int
    components: tuple[EmotionComponent, ...]

    def __post_init__(self) -> None:
        if (
            type(self.importance) is not int
            or not 5 <= self.importance <= 100
            or self.importance % 5
            or type(self.components) is not tuple
            or not 1 <= len(self.components) <= 3
            or any(type(item) is not EmotionComponent for item in self.components)
        ):
            raise MoodViolation("MOOD-EVENT")


@dataclass(frozen=True, slots=True)
class CandidateMoodDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    expected_version: int
    kind: MoodCandidateKind
    event: AffectiveEvent | None = None
    target_home_base: VAD | None = None

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class MoodState:
    dynamics_version: str
    home_base: VAD


@dataclass(frozen=True, slots=True)
class MoodHead:
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class EffectiveEmotion:
    family: EmotionFamily
    nuance: str
    intensity: int


@dataclass(frozen=True, slots=True)
class MoodSnapshot:
    current_revision_id: UUID
    version: int
    as_of: datetime
    home_base: VAD
    current: VAD
    active_emotions: tuple[EffectiveEmotion, ...]

    @property
    def current_vad(self) -> VAD:
        return self.current


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

    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodSnapshot: ...

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...


@runtime_checkable
class MoodCognitionPort(Protocol):
    def bind(self, value: CandidateMoodDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateMoodDraft: ...


@runtime_checkable
class MoodCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool: ...


@runtime_checkable
class MoodBirthPort(Protocol):
    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


@runtime_checkable
class MoodAdminReadPort(Protocol):
    def current_component(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MoodAdminComponent | None: ...


@runtime_checkable
class MoodAdminCorrectionPort(Protocol):
    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> MoodCorrectionHead | None: ...

    def revision(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
    ) -> tuple[UUID, int] | None: ...

    def replace(
        self,
        transaction: PostgreSQLAdminTransaction,
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
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        current_revision_id: str,
        current_version: int,
        target_revision_id: str,
        target_version: int,
    ) -> bool: ...

    def find_current(
        self, transaction: PostgreSQLAdminTransaction, *, kind: str
    ) -> tuple[UUID, int] | None: ...


__all__ = (
    "VAD",
    "AffectiveEvent",
    "CandidateMoodDraft",
    "EffectiveEmotion",
    "EmotionComponent",
    "EmotionFamily",
    "MoodAdminComponent",
    "MoodAdminCorrectionPort",
    "MoodAdminReadPort",
    "MoodBirthPort",
    "MoodCandidateKind",
    "MoodCognitionPort",
    "MoodCommitPort",
    "MoodCorrectionHead",
    "MoodHead",
    "MoodReadPort",
    "MoodSnapshot",
    "MoodState",
    "MoodViolation",
)
