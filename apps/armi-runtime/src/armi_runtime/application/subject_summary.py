"""Runtime assembly of the Creator-visible subject summary."""

from __future__ import annotations

from uuid import UUID

from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_subject_state.api import (
    SubjectComponentSummary,
    SubjectStateKind,
    SubjectStateReadPort,
    SubjectStateViolation,
    SubjectSummary,
)


class RuntimeSubjectSummaryAssembler:
    __slots__ = ("_factory", "_subject_id", "_subject_state")

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        subject_id: UUID,
        subject_state: SubjectStateReadPort,
    ) -> None:
        self._factory = factory
        self._subject_id = subject_id
        self._subject_state = subject_state

    async def __call__(self) -> SubjectSummary:
        async with self._factory.unit_of_work(read_only=True) as unit_of_work:
            transaction = unit_of_work.transaction
            row = await (
                await transaction.execute(
                    """
                    SELECT subject_version,
                           (SELECT subject_commit_id FROM armi.subject_commits
                            WHERE subject_id = subjects.subject_id
                            ORDER BY new_subject_version DESC LIMIT 1),
                           statement_timestamp()
                    FROM armi.subjects WHERE subject_id = %s AND status = 'active'
                    """,
                    (self._subject_id,),
                )
            ).fetchone()
            heads = await self._subject_state.current_heads(
                transaction, subject_id=self._subject_id
            )
        if row is None or len(heads) != 3:
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")
        schema = {
            SubjectStateKind.SELF: "armi.self.v1",
            SubjectStateKind.MIND: "armi.mind.v2",
            SubjectStateKind.LIFE_MODE: "armi.life-mode.v1",
        }
        ordered = sorted(
            heads, key=lambda item: tuple(SubjectStateKind).index(item.kind)
        )
        return SubjectSummary(
            int(row[0]),
            tuple(
                SubjectComponentSummary(item.kind, item.version, schema[item.kind])
                for item in ordered
            ),
            row[1],
            row[2],
        )


__all__ = ("RuntimeSubjectSummaryAssembler",)
