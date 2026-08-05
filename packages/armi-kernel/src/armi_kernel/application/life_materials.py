"""Technology-neutral contracts for ARMI-owned mutable life materials."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, Instant

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_QUERY_CODE = re.compile(r"^LIFE-MATERIAL-QUERY-[A-Z0-9-]+$", re.ASCII)

CREATOR_LIFE_MATERIAL_PROJECTION_VERSION = "creator-life-material.v1"


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


@dataclass(frozen=True, slots=True)
class CreatorLifeMaterialItem:
    """One current material that the daily Creator boundary may read."""

    material_id: UUID
    current_revision_id: UUID
    material_kind: LifeMaterialKind
    revision_no: int
    head_version: int
    title: str
    body: str
    body_digest: Digest
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
            any(
                type(value) is not UUID or value.version != 7
                for value in (self.material_id, self.current_revision_id)
            )
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
            or type(self.body_digest) is not Digest
            or Digest.from_bytes(encoded_body) != self.body_digest
            or not _valid_metadata(self.metadata)
            or type(self.material_status) is not LifeMaterialStatus
            or self.privacy_status is not LifeMaterialPrivacyStatus.CREATOR_VISIBLE
            or type(self.created_at) is not Instant
            or type(self.updated_at) is not Instant
            or self.updated_at.value < self.created_at.value
        ):
            raise ValueError("creator life material is invalid")


class CreatorLifeMaterialQueryViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _QUERY_CODE.fullmatch(code) is None:
            raise ValueError("creator life material query code is invalid")
        self.code = code
        super().__init__("creator life material query failed")


@runtime_checkable
class CreatorLifeMaterialQueryPort(Protocol):
    async def get_creator_visible(
        self,
        material_id: UUID,
    ) -> CreatorLifeMaterialItem | None: ...


@dataclass(frozen=True, slots=True)
class CandidateLifeMaterialDraft:
    """A Runtime-bound full-content revision that has not taken effect yet."""

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
    body_digest: Digest
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: str = "creator_visible"
    source_kind: str = "subject_cognition"
    change_kind: LifeMaterialRevisionKind | None = None

    def __post_init__(self) -> None:
        if (
            type(self.proposal_ref) is not str
            or _REF.fullmatch(self.proposal_ref) is None
            or type(self.atomic_group_ref) is not str
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.basis_ordinals) is not tuple
            or not self.basis_ordinals
            or len(self.basis_ordinals) > 8
            or any(
                type(value) is not int or not 1 <= value <= 999
                for value in self.basis_ordinals
            )
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or any(
                type(value) is not UUID or value.version != 7
                for value in (self.material_id, self.owner_party_id)
            )
            or type(self.material_kind) is not LifeMaterialKind
            or type(self.expected_head_version) is not int
            or self.expected_head_version < 0
            or (self.current_revision_id is None) != (self.expected_head_version == 0)
            or (
                self.current_revision_id is not None
                and (
                    type(self.current_revision_id) is not UUID
                    or self.current_revision_id.version != 7
                )
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
            or type(self.body_digest) is not Digest
            or (
                self.body_bytes is not None
                and Digest.from_bytes(self.body_bytes) != self.body_digest
            )
            or type(self.metadata) is not tuple
            or len(self.metadata) > 32
            or any(
                type(key) is not str
                or _METADATA_KEY.fullmatch(key) is None
                or type(value) is not str
                or len(value) > 512
                or "\x00" in value
                for key, value in self.metadata
            )
            or tuple(sorted(self.metadata)) != self.metadata
            or len({key for key, _ in self.metadata}) != len(self.metadata)
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
            raise ValueError("life material draft is invalid")
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
            raise ValueError("life material draft is invalid") from None
        if body is not None and not body.strip():
            raise ValueError("life material draft is invalid")
        revision_kind = self.revision_kind
        if (
            (revision_kind is LifeMaterialRevisionKind.CREATED)
            != (self.current_revision_id is None)
            or (
                revision_kind
                in {
                    LifeMaterialRevisionKind.CREATED,
                    LifeMaterialRevisionKind.UPDATED,
                }
            )
            != (self.body_bytes is not None)
            or (
                revision_kind is LifeMaterialRevisionKind.CREATED
                and self.privacy_status
                != LifeMaterialPrivacyStatus.CREATOR_VISIBLE.value
            )
            or (
                revision_kind is LifeMaterialRevisionKind.UPDATED
                and self.privacy_status
                not in {
                    LifeMaterialPrivacyStatus.CREATOR_VISIBLE.value,
                    LifeMaterialPrivacyStatus.PRIVATE.value,
                }
            )
            or (
                revision_kind is LifeMaterialRevisionKind.PRIVACY_CHANGED
                and self.privacy_status
                not in {
                    LifeMaterialPrivacyStatus.CREATOR_VISIBLE.value,
                    LifeMaterialPrivacyStatus.PRIVATE.value,
                }
            )
            or (
                revision_kind is LifeMaterialRevisionKind.DELETED
                and self.privacy_status != LifeMaterialPrivacyStatus.RESTRICTED.value
            )
        ):
            raise ValueError("life material draft is invalid")

    @property
    def revision_kind(self) -> LifeMaterialRevisionKind:
        return self.change_kind or (
            LifeMaterialRevisionKind.CREATED
            if self.current_revision_id is None
            else LifeMaterialRevisionKind.UPDATED
        )


def _valid_metadata(value: tuple[tuple[str, str], ...]) -> bool:
    return (
        type(value) is tuple
        and len(value) <= 32
        and all(
            type(key) is str
            and _METADATA_KEY.fullmatch(key) is not None
            and type(item) is str
            and len(item) <= 512
            and "\x00" not in item
            for key, item in value
        )
        and tuple(sorted(value)) == value
        and len({key for key, _ in value}) == len(value)
    )


__all__ = (
    "CREATOR_LIFE_MATERIAL_PROJECTION_VERSION",
    "CandidateLifeMaterialDraft",
    "CreatorLifeMaterialItem",
    "CreatorLifeMaterialQueryPort",
    "CreatorLifeMaterialQueryViolation",
    "LifeMaterialKind",
    "LifeMaterialPrivacyStatus",
    "LifeMaterialRevisionKind",
    "LifeMaterialStatus",
)
