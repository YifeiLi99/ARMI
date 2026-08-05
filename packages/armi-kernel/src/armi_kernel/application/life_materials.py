"""Technology-neutral contracts for ARMI-owned mutable life materials."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from armi_kernel.contracts import Digest

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


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
    body_bytes: bytes
    body_digest: Digest
    metadata: tuple[tuple[str, str], ...]
    material_status: LifeMaterialStatus
    privacy_status: str = "creator_visible"
    source_kind: str = "subject_cognition"

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
            or type(self.body_bytes) is not bytes
            or not 1 <= len(self.body_bytes) <= 65_536
            or b"\x00" in self.body_bytes
            or type(self.body_digest) is not Digest
            or Digest.from_bytes(self.body_bytes) != self.body_digest
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
            or self.privacy_status != "creator_visible"
            or self.source_kind != "subject_cognition"
        ):
            raise ValueError("life material draft is invalid")
        try:
            body = self.body_bytes.decode("utf-8", errors="strict")
            self.title.encode("utf-8", errors="strict")
            for key, value in self.metadata:
                key.encode("ascii", errors="strict")
                value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("life material draft is invalid") from None
        if not body.strip():
            raise ValueError("life material draft is invalid")

    @property
    def revision_kind(self) -> LifeMaterialRevisionKind:
        return (
            LifeMaterialRevisionKind.CREATED
            if self.current_revision_id is None
            else LifeMaterialRevisionKind.UPDATED
        )


__all__ = (
    "CandidateLifeMaterialDraft",
    "LifeMaterialKind",
    "LifeMaterialRevisionKind",
    "LifeMaterialStatus",
)
