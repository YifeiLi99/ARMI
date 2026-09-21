"""Runtime assembly of the Creator-visible subject summary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from armi_cognition.api import CognitionOperationReadPort
from armi_mind.api import MindReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_subject_state.api import SubjectStateReadPort, SubjectStateViolation


class SubjectComponentKind(StrEnum):
    SELF = "self"
    MIND = "mind"
    LIFE_MODE = "life_mode"


@dataclass(frozen=True, slots=True)
class SubjectComponentSummary:
    kind: SubjectComponentKind
    version: int
    schema_version: str
    content_visibility: str = "private"

    def __post_init__(self) -> None:
        expected = {
            SubjectComponentKind.SELF: "armi.self.v1",
            SubjectComponentKind.MIND: "armi.mind.v4",
            SubjectComponentKind.LIFE_MODE: "armi.life-mode.v1",
        }
        if (
            type(self.kind) is not SubjectComponentKind
            or type(self.version) is not int
            or self.version <= 0
            or self.schema_version != expected[self.kind]
            or self.content_visibility != "private"
        ):
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    subject_version: int
    components: tuple[SubjectComponentSummary, ...]
    latest_commit_ref: UUID | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.subject_version) is not int
            or self.subject_version < 0
            or tuple(item.kind for item in self.components)
            != (
                SubjectComponentKind.SELF,
                SubjectComponentKind.MIND,
                SubjectComponentKind.LIFE_MODE,
            )
            or (
                self.latest_commit_ref is not None
                and (
                    type(self.latest_commit_ref) is not UUID
                    or self.latest_commit_ref.version != 7
                )
            )
            or type(self.observed_at) is not datetime
            or self.observed_at.tzinfo is None
        ):
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")


class RuntimeSubjectSummaryAssembler:
    __slots__ = ("_cognition", "_factory", "_mind", "_subject_id", "_subject_state")

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        subject_id: UUID,
        subject_state: SubjectStateReadPort,
        mind: MindReadPort,
        cognition: CognitionOperationReadPort,
    ) -> None:
        self._factory = factory
        self._subject_id = subject_id
        self._subject_state = subject_state
        self._mind = mind
        self._cognition = cognition

    async def __call__(self) -> SubjectSummary:
        async with self._factory.unit_of_work(read_only=True) as unit_of_work:
            transaction = unit_of_work.transaction
            row = await (
                await transaction.execute(
                    """
                    SELECT subject_version, statement_timestamp()
                    FROM armi.subjects WHERE subject_id = %s AND status = 'active'
                    """,
                    (self._subject_id,),
                )
            ).fetchone()
            if row is None:
                raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")
            commit_id = await self._cognition.commit_at_version(
                transaction, subject_id=self._subject_id, subject_version=int(row[0])
            )
            heads = await self._subject_state.current_heads(
                transaction, subject_id=self._subject_id
            )
            mind = await self._mind.current_head(
                transaction, subject_id=self._subject_id
            )
        if len(heads) != 2:
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")
        components = [
            SubjectComponentSummary(
                SubjectComponentKind(item.kind.value),
                item.version,
                "armi.self.v1" if item.kind.value == "self" else "armi.life-mode.v1",
            )
            for item in heads
        ]
        components.insert(
            1,
            SubjectComponentSummary(
                SubjectComponentKind.MIND, mind.version, "armi.mind.v4"
            ),
        )
        return SubjectSummary(int(row[0]), tuple(components), commit_id, row[1])


__all__ = (
    "RuntimeSubjectSummaryAssembler",
    "SubjectComponentKind",
    "SubjectComponentSummary",
    "SubjectSummary",
)
