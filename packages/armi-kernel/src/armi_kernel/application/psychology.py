"""Read-only psychology integration values; no emotion or motivation policy."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PsychologicalContextItem:
    item_kind: str
    source_kind: str
    source_ref: UUID
    source_version: int
    content: str
    required: bool
    relevance: int


@dataclass(frozen=True, slots=True)
class ConsiderationSignal:
    owner: Literal["mind", "mood"]
    object_ref: UUID
    condition_version: str
    reason: Literal[
        "review_time_reached", "creator_input", "activity_result", "affective_change"
    ]
    eligible_at: datetime
    source_commit_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            self.owner not in {"mind", "mood"}
            or type(self.object_ref) is not UUID
            or self.object_ref.version != 7
            or type(self.condition_version) is not str
            or not 1 <= len(self.condition_version) <= 160
            or self.reason
            not in {
                "review_time_reached",
                "creator_input",
                "activity_result",
                "affective_change",
            }
            or type(self.eligible_at) is not datetime
            or self.eligible_at.tzinfo is None
            or (
                self.source_commit_id is not None
                and (
                    type(self.source_commit_id) is not UUID
                    or self.source_commit_id.version != 7
                )
            )
        ):
            raise ValueError("invalid consideration signal")

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.owner, str(self.object_ref), self.condition_version


__all__ = ("ConsiderationSignal", "PsychologicalContextItem")
