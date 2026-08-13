"""Stable public contract of the life-material owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactRef, CandidateOwnerDraft
from armi_kernel.contracts import Instant
from armi_runtime_foundation import PostgreSQLTransaction

from ._domain import valid_metadata

CREATOR_LIFE_MATERIAL_PROJECTION_VERSION = "creator-life-material.v1"
MATERIAL_CANDIDATE_VERSION = "armi.material-candidate.v1"
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class LifeMaterialKind(StrEnum):
    DIARY = "diary"
    WORK = "work"
    COLLECTION = "collection"
    DRAFT = "draft"


class LifeMaterialStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class LifeMaterialRevisionKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    PRIVACY_CHANGED = "privacy_changed"
    DELETED = "deleted"


class LifeMaterialPrivacyStatus(StrEnum):
    CREATOR_VISIBLE = "creator_visible"
    PRIVATE = "private"
    SHARED = "shared"
    RESTRICTED = "restricted"


class MaterialViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MATERIAL-"):
            raise ValueError("material violation code is invalid")
        self.code = code
        super().__init__("life-material operation failed")

    def __str__(self) -> str:
        return f"{self.code}: life-material operation failed"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


@dataclass(frozen=True, slots=True)
class CandidateLifeMaterialDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    material_id: UUID
    owner_party_id: UUID
    material_kind: LifeMaterialKind
    current_revision_id: UUID | None
    expected_head_version: int
    title: str
    body_bytes: bytes | None
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: str = "creator_visible"
    source_kind: str = "subject_cognition"
    change_kind: LifeMaterialRevisionKind | None = None

    def __post_init__(self) -> None:
        if (
            _REF.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.basis_ordinals) is not tuple
            or not self.basis_ordinals
            or len(self.basis_ordinals) > 8
            or any(
                type(value) is not int or not 1 <= value <= 999
                for value in self.basis_ordinals
            )
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or not _uuid7(self.material_id)
            or not _uuid7(self.owner_party_id)
            or type(self.material_kind) is not LifeMaterialKind
            or type(self.expected_head_version) is not int
            or self.expected_head_version < 0
            or (self.current_revision_id is None) != (self.expected_head_version == 0)
            or (
                self.current_revision_id is not None
                and not _uuid7(self.current_revision_id)
            )
            or type(self.title) is not str
            or not 1 <= len(self.title) <= 256
            or not self.title.strip()
            or "\x00" in self.title
            or (
                self.body_bytes is not None
                and (
                    type(self.body_bytes) is not bytes
                    or not 1 <= len(self.body_bytes) <= 65_536
                    or b"\x00" in self.body_bytes
                )
            )
            or not valid_metadata(self.metadata)
            or type(self.material_status) is not LifeMaterialStatus
            or self.privacy_status
            not in {
                LifeMaterialPrivacyStatus.CREATOR_VISIBLE.value,
                LifeMaterialPrivacyStatus.PRIVATE.value,
                LifeMaterialPrivacyStatus.RESTRICTED.value,
            }
            or self.source_kind != "subject_cognition"
            or (
                self.change_kind is not None
                and type(self.change_kind) is not LifeMaterialRevisionKind
            )
        ):
            raise MaterialViolation("MATERIAL-CANDIDATE")
        try:
            body = (
                None
                if self.body_bytes is None
                else self.body_bytes.decode("utf-8", errors="strict")
            )
            self.title.encode("utf-8", errors="strict")
            for key, value in self.metadata:
                key.encode("ascii", errors="strict")
                value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise MaterialViolation("MATERIAL-CANDIDATE") from None
        if body is not None and not body.strip():
            raise MaterialViolation("MATERIAL-CANDIDATE")
        revision_kind = self.revision_kind
        if (
            (revision_kind is LifeMaterialRevisionKind.CREATED)
            != (self.current_revision_id is None)
            or (
                revision_kind
                in {LifeMaterialRevisionKind.CREATED, LifeMaterialRevisionKind.UPDATED}
            )
            != (self.body_bytes is not None)
            or (
                revision_kind is LifeMaterialRevisionKind.CREATED
                and self.privacy_status != "creator_visible"
            )
            or (
                revision_kind
                in {
                    LifeMaterialRevisionKind.UPDATED,
                    LifeMaterialRevisionKind.PRIVACY_CHANGED,
                }
                and self.privacy_status not in {"creator_visible", "private"}
            )
            or (
                revision_kind is LifeMaterialRevisionKind.DELETED
                and self.privacy_status != "restricted"
            )
        ):
            raise MaterialViolation("MATERIAL-CANDIDATE-SHAPE")

    @property
    def revision_kind(self) -> LifeMaterialRevisionKind:
        return self.change_kind or (
            LifeMaterialRevisionKind.CREATED
            if self.current_revision_id is None
            else LifeMaterialRevisionKind.UPDATED
        )


@dataclass(frozen=True, slots=True)
class MaterialCandidateSource:
    material_id: UUID
    current_revision_id: UUID
    head_version: int
    owner_party_id: UUID
    material_kind: LifeMaterialKind
    title: str
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus
    artifact: ArtifactRef


@dataclass(frozen=True, slots=True)
class MaterialContextItem:
    material_id: UUID
    current_revision_id: UUID
    head_version: int
    owner_party_id: UUID
    material_kind: LifeMaterialKind
    title: str
    body_bytes: bytes
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.material_id)
            or not _uuid7(self.current_revision_id)
            or not _uuid7(self.owner_party_id)
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.material_kind) is not LifeMaterialKind
            or type(self.title) is not str
            or not 1 <= len(self.title) <= 256
            or not self.title.strip()
            or type(self.body_bytes) is not bytes
            or not 1 <= len(self.body_bytes) <= 65_536
            or not valid_metadata(self.metadata)
            or type(self.material_status) is not LifeMaterialStatus
            or self.privacy_status
            not in {
                LifeMaterialPrivacyStatus.CREATOR_VISIBLE,
                LifeMaterialPrivacyStatus.PRIVATE,
            }
        ):
            raise MaterialViolation("MATERIAL-CONTEXT")


@dataclass(frozen=True, slots=True)
class CreatorLifeMaterialItem:
    material_id: UUID
    current_revision_id: UUID
    material_kind: LifeMaterialKind
    revision_no: int
    head_version: int
    title: str
    body: str
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus
    created_at: Instant
    updated_at: Instant

    def __post_init__(self) -> None:
        try:
            encoded_body = self.body.encode("utf-8", errors="strict")
            self.title.encode("utf-8", errors="strict")
            for key, value in self.metadata:
                key.encode("ascii", errors="strict")
                value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("creator life material is invalid") from None
        if (
            not _uuid7(self.material_id)
            or not _uuid7(self.current_revision_id)
            or type(self.material_kind) is not LifeMaterialKind
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.head_version) is not int
            or self.head_version < 1
            or type(self.title) is not str
            or not 1 <= len(self.title) <= 256
            or not self.title.strip()
            or "\x00" in self.title
            or type(self.body) is not str
            or not 1 <= len(encoded_body) <= 65_536
            or not self.body.strip()
            or "\x00" in self.body
            or not valid_metadata(self.metadata)
            or type(self.material_status) is not LifeMaterialStatus
            or self.privacy_status is not LifeMaterialPrivacyStatus.CREATOR_VISIBLE
            or type(self.created_at) is not Instant
            or type(self.updated_at) is not Instant
            or self.updated_at.value < self.created_at.value
        ):
            raise ValueError("creator life material is invalid")


@dataclass(frozen=True, slots=True)
class MaterialAdminItem:
    material_id: UUID
    current_revision_id: UUID
    material_kind: LifeMaterialKind
    head_version: int
    revision_no: int
    title: str
    body: str
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus
    artifact_id: UUID
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MaterialAdminSnapshot:
    items: tuple[MaterialAdminItem, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class MaterialLifeRecordItem:
    material_id: UUID
    title: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MaterialOpportunitySource:
    material_id: UUID
    revision_id: UUID
    head_version: int


@dataclass(frozen=True, slots=True)
class MaterialProjectionSource:
    subject_id: UUID
    generation_id: UUID
    material_id: UUID
    current_revision_id: UUID
    head_version: int
    owner_party_id: UUID
    material_kind: LifeMaterialKind
    title: str
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: LifeMaterialPrivacyStatus
    artifact: ArtifactRef


@dataclass(frozen=True, slots=True)
class RecalledMaterials:
    items: tuple[tuple[UUID, int, str, float], ...]
    missing_projection: bool


@runtime_checkable
class MaterialReadPort(Protocol):
    async def candidate_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        episode_id: UUID,
    ) -> tuple[MaterialCandidateSource, ...]: ...

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_visible_only: bool,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[MaterialLifeRecordItem, ...]: ...

    async def next_opportunity_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
    ) -> MaterialOpportunitySource | None: ...

    async def get_creator_visible(
        self, material_id: UUID
    ) -> CreatorLifeMaterialItem | None: ...


@runtime_checkable
class MaterialAdminReadPort(Protocol):
    def private_snapshot(self, subject_id: UUID) -> MaterialAdminSnapshot: ...


@runtime_checkable
class MaterialCognitionPort(Protocol):
    def bind(self, value: CandidateLifeMaterialDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateLifeMaterialDraft: ...
    def bind_wire(self, value: object) -> CandidateOwnerDraft: ...


@runtime_checkable
class MaterialCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        validation_id: UUID,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        artifacts: dict[str, ArtifactRef],
    ) -> tuple[UUID, ...]: ...

    async def affected_material_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class MaterialProjectionPort(Protocol):
    async def next_missing_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        model_binding: str,
        work_kind: str,
    ) -> MaterialProjectionSource | None: ...

    async def load_source(
        self, transaction: PostgreSQLTransaction, material_id: UUID
    ) -> MaterialProjectionSource | None: ...

    async def recall(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        model_binding: str,
        query_vector: tuple[float, ...],
        minimum_similarity: float,
        limit: int,
    ) -> RecalledMaterials: ...


__all__ = (
    "CREATOR_LIFE_MATERIAL_PROJECTION_VERSION",
    "MATERIAL_CANDIDATE_VERSION",
    "CandidateLifeMaterialDraft",
    "CreatorLifeMaterialItem",
    "LifeMaterialKind",
    "LifeMaterialPrivacyStatus",
    "LifeMaterialRevisionKind",
    "LifeMaterialStatus",
    "MaterialAdminItem",
    "MaterialAdminReadPort",
    "MaterialAdminSnapshot",
    "MaterialCandidateSource",
    "MaterialCognitionPort",
    "MaterialCommitPort",
    "MaterialContextItem",
    "MaterialLifeRecordItem",
    "MaterialOpportunitySource",
    "MaterialProjectionPort",
    "MaterialProjectionSource",
    "MaterialReadPort",
    "MaterialViolation",
    "RecalledMaterials",
)
