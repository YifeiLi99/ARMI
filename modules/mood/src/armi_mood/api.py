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
    APPRAISAL = "appraisal"
    HOME_BASE_REFLECTION = "home_base_reflection"


class AppraisalTransition(StrEnum):
    NEW = "new"
    REINFORCE = "reinforce"
    REAPPRAISE = "reappraise"
    RESOLVE = "resolve"


class AppraisalEventPhase(StrEnum):
    ANTICIPATED = "anticipated"
    ONGOING = "ongoing"
    REALIZED = "realized"
    AVERTED = "averted"


class AppraisalAgency(StrEnum):
    SELF = "self"
    OTHER = "other"
    SHARED = "shared"
    CIRCUMSTANCE = "circumstance"
    UNKNOWN = "unknown"


class AppraisalSelfScope(StrEnum):
    NONE = "none"
    ACTION = "action"
    GLOBAL = "global"


class AppraisalConcernTarget(StrEnum):
    SELF_GOAL = "self_goal"
    RELATIONSHIP = "relationship"
    SOCIAL_ORDER = "social_order"


class AppraisalSignificance(StrEnum):
    PERIPHERAL = "peripheral"
    DIRECT = "direct"
    CORE = "core"
    UNKNOWN = "unknown"


class AppraisalDirection(StrEnum):
    MAJOR_SETBACK = "major_setback"
    SETBACK = "setback"
    UNCHANGED = "unchanged"
    PROGRESS = "progress"
    FULFILLED = "fulfilled"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AppraisalExpectedness(StrEnum):
    EXPECTED = "expected"
    SOMEWHAT_UNEXPECTED = "somewhat_unexpected"
    EXPECTATION_BROKEN = "expectation_broken"
    UNKNOWN = "unknown"


class AppraisalCertainty(StrEnum):
    OPEN = "open"
    UNCERTAIN = "uncertain"
    LIKELY = "likely"
    SETTLED = "settled"
    UNKNOWN = "unknown"


class AppraisalQuality(StrEnum):
    STRONGLY_AVERSIVE = "strongly_aversive"
    UNPLEASANT = "unpleasant"
    NEUTRAL = "neutral"
    PLEASANT = "pleasant"
    STRONGLY_PLEASANT = "strongly_pleasant"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AppraisalDemandLevel(StrEnum):
    NONE = "none"
    LIGHT = "light"
    SUBSTANTIAL = "substantial"
    EXTREME = "extreme"
    UNKNOWN = "unknown"


class AppraisalUrgency(StrEnum):
    NONE = "none"
    CAN_WAIT = "can_wait"
    SOON = "soon"
    IMMEDIATE = "immediate"
    UNKNOWN = "unknown"


class AppraisalIntentionality(StrEnum):
    ACCIDENTAL = "accidental"
    UNCLEAR = "unclear"
    DELIBERATE = "deliberate"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class AppraisalResponseAccess(StrEnum):
    NONE = "none"
    INDIRECT = "indirect"
    DIRECT = "direct"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class AppraisalPowerBalance(StrEnum):
    OVERMATCHED = "overmatched"
    LIMITED = "limited"
    BALANCED = "balanced"
    ADVANTAGED = "advantaged"
    UNKNOWN = "unknown"


class AppraisalAdjustment(StrEnum):
    BLOCKED = "blocked"
    DIFFICULT = "difficult"
    MANAGEABLE = "manageable"
    EASY = "easy"
    UNKNOWN = "unknown"


class AppraisalCompatibility(StrEnum):
    VIOLATION = "violation"
    TENSION = "tension"
    ALIGNED = "aligned"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class AppraisalSelfInvolvement(StrEnum):
    NONE = "none"
    LIMITED = "limited"
    IMPORTANT = "important"
    IDENTITY_LEVEL = "identity_level"
    UNKNOWN = "unknown"


class AppraisalTrajectory(StrEnum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    WORSENED = "worsened"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ActionTendency(StrEnum):
    APPROACH = "approach"
    CONNECT = "connect"
    EXPLORE = "explore"
    PROTECT = "protect"
    CONFRONT = "confront"
    WITHDRAW = "withdraw"
    REJECT = "reject"
    REPAIR = "repair"
    CLARIFY = "clarify"
    DISENGAGE = "disengage"
    PAUSE = "pause"


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
class AppraisalConcern:
    target: AppraisalConcernTarget
    significance: AppraisalSignificance
    direction: AppraisalDirection

    def __post_init__(self) -> None:
        if (
            type(self.target) is not AppraisalConcernTarget
            or type(self.significance) is not AppraisalSignificance
            or type(self.direction) is not AppraisalDirection
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class AppraisalDemand:
    urgency: AppraisalUrgency
    effort: AppraisalDemandLevel

    def __post_init__(self) -> None:
        if (
            type(self.urgency) is not AppraisalUrgency
            or type(self.effort) is not AppraisalDemandLevel
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class AppraisalCausality:
    agency: AppraisalAgency
    intentionality: AppraisalIntentionality

    def __post_init__(self) -> None:
        if (
            type(self.agency) is not AppraisalAgency
            or type(self.intentionality) is not AppraisalIntentionality
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class AppraisalCoping:
    response_access: AppraisalResponseAccess
    power_balance: AppraisalPowerBalance
    adjustment: AppraisalAdjustment

    def __post_init__(self) -> None:
        if (
            type(self.response_access) is not AppraisalResponseAccess
            or type(self.power_balance) is not AppraisalPowerBalance
            or type(self.adjustment) is not AppraisalAdjustment
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class AppraisalStandards:
    self_compatibility: AppraisalCompatibility
    norm_compatibility: AppraisalCompatibility
    self_scope: AppraisalSelfScope

    def __post_init__(self) -> None:
        if (
            type(self.self_compatibility) is not AppraisalCompatibility
            or type(self.norm_compatibility) is not AppraisalCompatibility
            or type(self.self_scope) is not AppraisalSelfScope
        ):
            raise MoodViolation("MOOD-APPRAISAL")
        conflict = self.self_compatibility in {
            AppraisalCompatibility.VIOLATION,
            AppraisalCompatibility.TENSION,
            AppraisalCompatibility.MIXED,
        }
        if conflict != (self.self_scope is not AppraisalSelfScope.NONE):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class SemanticAppraisal:
    concerns: tuple[AppraisalConcern, ...]
    expectedness: AppraisalExpectedness
    outcome_certainty: AppraisalCertainty
    intrinsic_quality: AppraisalQuality
    self_involvement: AppraisalSelfInvolvement
    demand: AppraisalDemand | None = None
    causality: AppraisalCausality | None = None
    coping: AppraisalCoping | None = None
    standards: AppraisalStandards | None = None

    def __post_init__(self) -> None:
        if (
            type(self.concerns) is not tuple
            or not 1 <= len(self.concerns) <= 3
            or any(type(item) is not AppraisalConcern for item in self.concerns)
            or len({item.target for item in self.concerns}) != len(self.concerns)
            or type(self.expectedness) is not AppraisalExpectedness
            or type(self.outcome_certainty) is not AppraisalCertainty
            or type(self.intrinsic_quality) is not AppraisalQuality
            or type(self.self_involvement) is not AppraisalSelfInvolvement
            or (self.demand is not None and type(self.demand) is not AppraisalDemand)
            or (
                self.causality is not None
                and type(self.causality) is not AppraisalCausality
            )
            or (self.coping is not None and type(self.coping) is not AppraisalCoping)
            or (
                self.standards is not None
                and type(self.standards) is not AppraisalStandards
            )
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class SemanticAppraisalEvent:
    transition: AppraisalTransition
    previous_episode_id: UUID | None
    phase: AppraisalEventPhase
    gist: str
    appraisal: SemanticAppraisal
    change_from_previous: AppraisalTrajectory | None = None

    def __post_init__(self) -> None:
        if (
            type(self.transition) is not AppraisalTransition
            or type(self.phase) is not AppraisalEventPhase
            or type(self.gist) is not str
            or not self.gist.strip()
            or self.gist != self.gist.strip()
            or "\x00" in self.gist
            or len(self.gist) > 64
            or type(self.appraisal) is not SemanticAppraisal
            or (self.transition is AppraisalTransition.NEW)
            != (self.previous_episode_id is None)
            or (
                self.previous_episode_id is not None
                and (
                    type(self.previous_episode_id) is not UUID
                    or self.previous_episode_id.version != 7
                )
            )
            or (self.transition is AppraisalTransition.NEW)
            != (self.change_from_previous is None)
            or (
                self.change_from_previous is not None
                and type(self.change_from_previous) is not AppraisalTrajectory
            )
        ):
            raise MoodViolation("MOOD-APPRAISAL")


@dataclass(frozen=True, slots=True)
class CandidateMoodDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    expected_version: int
    kind: MoodCandidateKind
    appraisal: SemanticAppraisalEvent | None = None

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class MoodState:
    dynamics_version: str
    derivation_version: str
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
class ActiveAffectiveEpisode:
    episode_id: UUID
    gist: str
    phase: AppraisalEventPhase
    intensity: int


@dataclass(frozen=True, slots=True)
class EffectiveActionTendency:
    tendency: ActionTendency
    intensity: int


@dataclass(frozen=True, slots=True)
class MoodSnapshot:
    current_revision_id: UUID
    version: int
    as_of: datetime
    home_base: VAD
    current: VAD
    active_emotions: tuple[EffectiveEmotion, ...]
    active_episodes: tuple[ActiveAffectiveEpisode, ...] = ()
    action_tendencies: tuple[EffectiveActionTendency, ...] = ()

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
    "ActionTendency",
    "ActiveAffectiveEpisode",
    "AppraisalAdjustment",
    "AppraisalAgency",
    "AppraisalCausality",
    "AppraisalCertainty",
    "AppraisalCompatibility",
    "AppraisalConcern",
    "AppraisalConcernTarget",
    "AppraisalCoping",
    "AppraisalDemand",
    "AppraisalDemandLevel",
    "AppraisalDirection",
    "AppraisalEventPhase",
    "AppraisalExpectedness",
    "AppraisalIntentionality",
    "AppraisalPowerBalance",
    "AppraisalQuality",
    "AppraisalResponseAccess",
    "AppraisalSelfInvolvement",
    "AppraisalSelfScope",
    "AppraisalSignificance",
    "AppraisalStandards",
    "AppraisalTrajectory",
    "AppraisalTransition",
    "AppraisalUrgency",
    "CandidateMoodDraft",
    "EffectiveActionTendency",
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
    "SemanticAppraisal",
    "SemanticAppraisalEvent",
)
