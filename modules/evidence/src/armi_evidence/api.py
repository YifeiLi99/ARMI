"""Public contracts for accepted external evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransactionAccess


class EvidenceViolation(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{code}: evidence operation failed")


def _require_uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise EvidenceViolation(code)


@dataclass(frozen=True, slots=True)
class EvidenceId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "EVIDENCE-ID")

    def __str__(self) -> str:
        return str(self.value)


class EvidenceSourceKind(StrEnum):
    CREATOR_INPUT = "creator_input"
    OTHER_HUMAN_INPUT = "other_human_input"
    WEB_SEARCH = "web_search"
    CODEX_TASK_SOURCE = "codex_task_source"
    CODEX_RESULT = "codex_result"


class EvidencePrivacyScope(StrEnum):
    CREATOR_VISIBLE = "creator_visible"
    PRIVATE = "private"


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceDraft:
    evidence_id: EvidenceId
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID | None
    artifact_id: UUID
    source_kind: EvidenceSourceKind
    privacy_scope: EvidencePrivacyScope
    interaction_id: UUID | None = None
    web_observation_request_id: UUID | None = None
    observation_attempt_id: UUID | None = None
    codex_task_source_id: UUID | None = None
    codex_verification_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.evidence_id) is not EvidenceId:
            raise EvidenceViolation("EVIDENCE-ID")
        if type(self.source_kind) is not EvidenceSourceKind:
            raise EvidenceViolation("EVIDENCE-SOURCE-KIND")
        if type(self.privacy_scope) is not EvidencePrivacyScope:
            raise EvidenceViolation("EVIDENCE-PRIVACY")
        _require_uuid7(self.subject_id, "EVIDENCE-SUBJECT")
        _require_uuid7(self.scene_id, "EVIDENCE-SCENE")
        if self.context_party_id is not None:
            _require_uuid7(self.context_party_id, "EVIDENCE-PARTY")
        _require_uuid7(self.artifact_id, "EVIDENCE-ARTIFACT")
        identities = (
            self.interaction_id,
            self.web_observation_request_id,
            self.observation_attempt_id,
            self.codex_task_source_id,
            self.codex_verification_id,
        )
        for identity in identities:
            if identity is not None:
                _require_uuid7(identity, "EVIDENCE-SOURCE-ID")
        expected = {
            EvidenceSourceKind.CREATOR_INPUT: (True, False, False, False, False),
            EvidenceSourceKind.OTHER_HUMAN_INPUT: (True, False, False, False, False),
            EvidenceSourceKind.WEB_SEARCH: (False, True, True, False, False),
            EvidenceSourceKind.CODEX_TASK_SOURCE: (False, False, False, True, False),
            EvidenceSourceKind.CODEX_RESULT: (False, False, False, False, True),
        }[self.source_kind]
        if tuple(value is not None for value in identities) != expected:
            raise EvidenceViolation("EVIDENCE-SOURCE-SHAPE")


@dataclass(frozen=True, slots=True)
class ExperienceEvidenceLink:
    experience_id: UUID
    evidence_id: EvidenceId
    context_item_id: UUID
    ordinal: int

    def __post_init__(self) -> None:
        _require_uuid7(self.experience_id, "EVIDENCE-LINK-EXPERIENCE")
        if type(self.evidence_id) is not EvidenceId:
            raise EvidenceViolation("EVIDENCE-LINK-EVIDENCE")
        _require_uuid7(self.context_item_id, "EVIDENCE-LINK-CONTEXT")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= 8:
            raise EvidenceViolation("EVIDENCE-LINK-ORDINAL")


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    evidence_id: EvidenceId
    received_at: datetime


@runtime_checkable
class EvidenceWritePort(Protocol):
    async def accept(
        self,
        transaction: PostgreSQLTransactionAccess,
        draft: EvidenceDraft,
    ) -> EvidenceId: ...

    async def link_experience(
        self,
        transaction: PostgreSQLTransactionAccess,
        link: ExperienceEvidenceLink,
    ) -> None: ...


@runtime_checkable
class EvidenceReadPort(Protocol):
    async def snapshot(
        self,
        transaction: PostgreSQLTransactionAccess,
        *,
        evidence_id: EvidenceId,
    ) -> EvidenceSnapshot: ...

    async def find_by_interaction(
        self,
        transaction: PostgreSQLTransactionAccess,
        *,
        interaction_id: UUID,
    ) -> EvidenceId | None: ...


__all__ = (
    "EvidenceDraft",
    "EvidenceId",
    "EvidencePrivacyScope",
    "EvidenceReadPort",
    "EvidenceSnapshot",
    "EvidenceSourceKind",
    "EvidenceViolation",
    "EvidenceWritePort",
    "ExperienceEvidenceLink",
)
