"""Evidence-module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass

from ._postgresql import PostgreSQLEvidenceWriter
from .api import EvidenceWritePort


@dataclass(frozen=True, slots=True)
class EvidenceModule:
    write: EvidenceWritePort

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


def bootstrap_evidence() -> EvidenceModule:
    return EvidenceModule(write=PostgreSQLEvidenceWriter())


__all__ = ("EvidenceModule", "bootstrap_evidence")
