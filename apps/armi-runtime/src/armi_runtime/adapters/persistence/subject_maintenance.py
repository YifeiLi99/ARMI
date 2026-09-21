"""Runtime-owned maintenance progress on the subject record (DESIGN.md)."""

from uuid import UUID

from armi_kernel.application import SubjectCommitViolation
from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLSubjectMaintenance:
    async def pending_window(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[int, int] | None:
        row = await (
            await transaction.execute(
                """SELECT maintenance_latest_accepted_ordinal,maintenance_processed_through_ordinal
                   FROM armi.subjects WHERE subject_id=%s
                     AND maintenance_latest_accepted_ordinal > maintenance_processed_through_ordinal
                   FOR UPDATE""",
                (subject_id,),
            )
        ).fetchone()
        return None if row is None else (int(row[0]), int(row[1]))

    async def note_accepted_experience(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        acceptance_ordinal: int,
    ) -> None:
        row = await (
            await transaction.execute(
                """UPDATE armi.subjects
                   SET maintenance_latest_accepted_ordinal=GREATEST(maintenance_latest_accepted_ordinal,%s)
                   WHERE subject_id=%s RETURNING subject_id""",
                (acceptance_ordinal, subject_id),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-IDENTITY")

    async def complete_window(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after_ordinal: int,
        through_ordinal: int,
    ) -> None:
        row = await (
            await transaction.execute(
                """UPDATE armi.subjects
                   SET maintenance_processed_through_ordinal=%s
                   WHERE subject_id=%s AND maintenance_processed_through_ordinal=%s
                     AND maintenance_latest_accepted_ordinal >= %s
                   RETURNING subject_id""",
                (through_ordinal, subject_id, after_ordinal, through_ordinal),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
