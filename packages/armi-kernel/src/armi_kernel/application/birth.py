"""Technology-neutral contracts for the one-time subject birth transaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$", re.ASCII)
_VOICE_STYLE = "约 16 岁少女口吻"


class BirthViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("BIRTH-"):
            raise ValueError("birth violation code is invalid")
        self.code = code
        super().__init__("birth operation failed")

    def __str__(self) -> str:
        return f"{self.code}: birth operation failed"


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise BirthViolation("BIRTH-MANIFEST")


@dataclass(frozen=True, slots=True)
class PersonalityAnchor:
    schema_version: str
    voice_style: str
    traits: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.schema_version != "armi.personality-anchor.v1"
            or self.voice_style != _VOICE_STYLE
            or type(self.traits) is not tuple
            or not 1 <= len(self.traits) <= 8
        ):
            raise BirthViolation("BIRTH-ANCHOR")
        for trait in self.traits:
            if (
                type(trait) is not str
                or not 1 <= len(trait) <= 64
                or trait != trait.strip()
                or any(ord(character) < 0x20 for character in trait)
            ):
                raise BirthViolation("BIRTH-ANCHOR")


@dataclass(frozen=True, slots=True)
class BirthManifest:
    schema_version: str
    environment_id: UUID
    birth_request_id: UUID
    creator_party_id: UUID
    idempotency_key: str
    personality_anchor: PersonalityAnchor
    birth_contract_digest: Digest
    request_digest: Digest

    def __post_init__(self) -> None:
        if self.schema_version != "armi.birth-manifest.v1":
            raise BirthViolation("BIRTH-MANIFEST")
        for value in (
            self.environment_id,
            self.birth_request_id,
            self.creator_party_id,
        ):
            _require_uuid7(value)
        if _IDEMPOTENCY_KEY.fullmatch(self.idempotency_key) is None:
            raise BirthViolation("BIRTH-MANIFEST")
        if type(self.personality_anchor) is not PersonalityAnchor:
            raise BirthViolation("BIRTH-ANCHOR")
        for digest in (
            self.birth_contract_digest,
            self.request_digest,
        ):
            if type(digest) is not Digest:
                raise BirthViolation("BIRTH-MANIFEST")


@dataclass(frozen=True, slots=True)
class BirthResult:
    subject_id: UUID
    life_generation_id: UUID
    bundle_activation_id: UUID
    request_digest: Digest
    created: bool

    def __post_init__(self) -> None:
        for value in (
            self.subject_id,
            self.life_generation_id,
            self.bundle_activation_id,
        ):
            _require_uuid7(value)
        if type(self.request_digest) is not Digest or type(self.created) is not bool:
            raise BirthViolation("BIRTH-STATE")

    def safe_view(self) -> dict[str, object]:
        return {
            "status": "applied" if self.created else "existing",
            "subject_id": str(self.subject_id),
            "life_generation_id": str(self.life_generation_id),
            "bundle_activation_id": str(self.bundle_activation_id),
            "request_digest": self.request_digest.to_wire(),
        }


@runtime_checkable
class BirthPort(Protocol):
    async def birth(self, manifest: BirthManifest) -> BirthResult: ...


__all__ = (
    "BirthManifest",
    "BirthPort",
    "BirthResult",
    "BirthViolation",
    "PersonalityAnchor",
)
