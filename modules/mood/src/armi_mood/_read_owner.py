"""Birth and read access to the current independent Mood state."""

from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._evaluation_contract import MoodView
from ._psychology import (
    Appraisal,
    DynamicsParameters,
    MoodDynamics,
    current_affect,
    derive_response,
    initial_dynamics,
)
from .api import MoodBirthContinuity, MoodHead, MoodViolation


class MoodReadOwner:
    def __init__(self, parameters: DynamicsParameters) -> None:
        self._parameters = parameters

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def current(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodHead:
        row = await (
            await transaction.execute(
                """SELECT mood_revision_id,mood_version,semantic_payload
               FROM armi.mood_revisions WHERE subject_id=%s AND is_current""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise MoodViolation("MOOD-MISSING")
        state = MoodDynamics.model_validate(row[2])
        return MoodHead(
            row[0], int(row[1]), rfc8785.dumps(state.model_dump(mode="json"))
        )

    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodView:
        head = await self.current(transaction, subject_id=subject_id)
        clock = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if clock is None:
            raise MoodViolation("MOOD-CLOCK")
        state = MoodDynamics.model_validate_json(head.canonical_state)
        assessment = await (
            await transaction.execute(
                """SELECT status,mood_assessment_id,error_code,appraisal FROM armi.mood_assessments
               WHERE subject_id=%s ORDER BY created_at DESC,mood_assessment_id DESC LIMIT 1""",
                (subject_id,),
            )
        ).fetchone()
        return MoodView(
            head.current_revision_id,
            head.version,
            clock[0],
            current_affect(state, clock[0]),
            state,
            "not_evaluated" if assessment is None else assessment[0],
            None if assessment is None else assessment[1],
            None if assessment is None else assessment[2],
            ()
            if assessment is None or assessment[3] is None
            else derive_response(Appraisal.model_validate(assessment[3])).unknown,
        )

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.mood_revisions WHERE subject_id=%s AND is_current",
                (subject_id,),
            )
        ).fetchone()
        assert row is not None
        return int(row[0])

    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> MoodBirthContinuity:
        row = transaction.execute(
            """SELECT count(*) FILTER (WHERE is_current), count(*) FROM armi.mood_revisions
               WHERE (%s::uuid IS NULL OR subject_id=%s)""",
            (subject_id, subject_id),
        ).fetchone()
        assert row is not None
        return MoodBirthContinuity(cast(int, row[0]), cast(int, row[1]))

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        clock = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if clock is None:
            raise MoodViolation("MOOD-CLOCK")
        state = initial_dynamics(clock[0], self._parameters)
        await transaction.execute(
            """INSERT INTO armi.mood_revisions
               (mood_revision_id,subject_id,mood_version,origin_kind,origin_ref,semantic_payload,is_current)
               VALUES (%s,%s,1,'bootstrap',%s,%s::jsonb,true)""",
            (uuid7(), subject_id, subject_id, state.model_dump_json()),
        )
