"""Evidence-module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass

from ._postgresql import PostgreSQLEvidenceWriter
from .api import EvidenceReadPort, EvidenceWritePort


@dataclass(frozen=True, slots=True)
class EvidenceModule:
    read: EvidenceReadPort
    write: EvidenceWritePort

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


def bootstrap_evidence() -> EvidenceModule:
    owner = PostgreSQLEvidenceWriter()
    return EvidenceModule(read=owner, write=owner)


__all__ = ("EvidenceModule", "bootstrap_evidence")
