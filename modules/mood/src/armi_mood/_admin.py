"""Synchronous Admin adapters owned by the mood module."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._evaluation_contract import MoodAssessmentReadPort, MoodView
from ._projection import mood_snapshot_bytes
from ._psychology import Appraisal, MoodDynamics, current_affect, derive_response
from .api import MoodAdminComponent, MoodCorrectionHead, MoodViolation


class PostgreSQLMoodAdmin:
    __slots__ = ("_assessments",)

    def __init__(self, assessments: MoodAssessmentReadPort | None = None) -> None:
        self._assessments = assessments

    def apply(
        self,
        transaction: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, object]:
        if command.action != "update" or set(command.values) != {
            "component_kind",
            "replacement",
        }:
            raise AdminContentViolation("ADMIN-CONTENT-COMPONENT-OPERATION")
        if command.object_id != context.subject_id:
            raise AdminContentViolation("ADMIN-CONTENT-SUBJECT-CONFLICT")
        kind = command.values["component_kind"]
        if not isinstance(kind, str):
            raise AdminContentViolation("ADMIN-CONTENT-COMPONENT-OPERATION")
        replacement = self.canonicalize_replacement(
            kind=kind, replacement=command.values["replacement"]
        )
        head = self.current_head(
            transaction, subject_id=str(context.subject_id), kind=kind, for_update=True
        )
        if (
            head is None
            or head.current_version != command.expected_version
            or head.maximum_version != head.current_version
        ):
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        revision = uuid7()
        version = head.current_version + 1
        if not self.replace(
            transaction,
            revision_id=str(revision),
            subject_id=str(context.subject_id),
            kind=kind,
            version=version,
            previous_revision_id=str(head.current_revision_id),
            replacement=replacement,
        ):
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        transaction.execute(
            "UPDATE armi.mood_revisions SET admin_change_id=%s WHERE mood_revision_id=%s",
            (context.change_id, revision),
        )
        return {
            "object_id": str(context.subject_id),
            "component_kind": kind,
            "revision_id": str(revision),
            "new_version": version,
            "history_retained": True,
            "physical_rows_deleted": 0,
        }

    def canonicalize_replacement(
        self, *, kind: str, replacement: object
    ) -> dict[str, object]:
        self._require_kind(kind)
        if type(replacement) is not dict:
            raise MoodViolation("MOOD-STATE")
        value = cast(dict[str, object], replacement)
        MoodDynamics.model_validate(value)
        return cast(dict[str, object], json.loads(json.dumps(value)))

    def current_component(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MoodAdminComponent | None:
        statement = (
            """SELECT head.mood_version,'private'::text AS privacy_scope,head.semantic_payload,
                 head.mood_revision_id,statement_timestamp(),head.subject_id
               FROM armi.mood_revisions AS head WHERE head.is_current"""
            if private
            else """SELECT head.mood_version,'private'::text AS privacy_scope FROM armi.mood_revisions AS head WHERE head.is_current """
        )
        row = transaction.execute(statement).fetchone()
        if row is None:
            return None
        payload = None
        if private:
            if self._assessments is None:
                raise MoodViolation("MOOD-ASSESSMENT-READ-MISSING")
            assessment = self._assessments.latest_admin(
                transaction, subject_id=cast(UUID, row[5])
            )
            row = (*row[:5], *(assessment or (None, None, None, None)))
            state = MoodDynamics.model_validate(row[2])
            payload = json.loads(
                mood_snapshot_bytes(
                    MoodView(
                        cast(UUID, row[3]),
                        cast(int, row[0]),
                        cast(datetime, row[4]),
                        current_affect(state, cast(datetime, row[4])),
                        state,
                        cast(str, row[5] or "not_evaluated"),
                        cast(UUID | None, row[6]),
                        cast(str | None, row[7]),
                        ()
                        if row[8] is None
                        else derive_response(Appraisal.model_validate(row[8])).unknown,
                    )
                )
            )
        return MoodAdminComponent("mood", int(cast(int, row[0])), str(row[1]), payload)

    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> MoodCorrectionHead | None:
        self._require_kind(kind)
        suffix = " FOR UPDATE OF head" if for_update else ""
        row = transaction.execute(
            """SELECT head.mood_revision_id,head.mood_version,head.semantic_payload,(SELECT max(candidate.mood_version) FROM armi.mood_revisions AS candidate WHERE candidate.subject_id=head.subject_id) FROM armi.mood_revisions AS head WHERE head.is_current AND head.subject_id=%s"""
            + suffix,
            (subject_id,),
        ).fetchone()
        return (
            None
            if row is None
            else MoodCorrectionHead(
                cast(UUID, row[0]),
                int(cast(int, row[1])),
                row[2],
                int(cast(int, row[3])),
            )
        )

    def revision(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
    ) -> tuple[UUID, int] | None:
        self._require_kind(kind)
        row = transaction.execute(
            "SELECT mood_revision_id,mood_version FROM armi.mood_revisions "
            "WHERE mood_revision_id=%s AND subject_id=%s",
            (revision_id, subject_id),
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))

    def replace(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
        version: int,
        previous_revision_id: str,
        replacement: object,
    ) -> bool:
        replacement = self.canonicalize_replacement(kind=kind, replacement=replacement)
        transaction.execute(
            "INSERT INTO armi.mood_revisions (mood_revision_id,subject_id,mood_version,"
            "previous_revision_id,origin_kind,origin_ref,"
            "semantic_payload) VALUES (%s,%s,%s,%s,'admin_correction',"
            "%s,%s::jsonb)",
            (
                revision_id,
                subject_id,
                version,
                previous_revision_id,
                revision_id,
                json.dumps(replacement, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return (
            transaction.execute(
                """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.mood_revision_id
                    FROM armi.mood_revisions AS candidate, input
                    WHERE candidate.mood_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.mood_version=input.new_version AND NOT candidate.is_current
                ), retired AS (
                    UPDATE armi.mood_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.mood_revision_id=input.old_id
                      AND previous.mood_version=input.old_version AND previous.is_current
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.mood_revisions AS current SET is_current=true
                FROM target, retired WHERE current.mood_revision_id=target.mood_revision_id""",
                (revision_id, version, subject_id, previous_revision_id, version - 1),
            ).rowcount
            == 1
        )

    def repair_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        current_revision_id: str,
        current_version: int,
        target_revision_id: str,
        target_version: int,
    ) -> bool:
        self._require_kind(kind)
        if current_revision_id == target_revision_id:
            return (
                current_version == target_version
                and transaction.execute(
                    "SELECT 1 FROM armi.mood_revisions WHERE subject_id=%s AND mood_revision_id=%s AND mood_version=%s AND is_current FOR UPDATE",
                    (subject_id, current_revision_id, current_version),
                ).fetchone()
                is not None
            )
        return (
            transaction.execute(
                """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.mood_revision_id
                    FROM armi.mood_revisions AS candidate, input
                    WHERE candidate.mood_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.mood_version=input.new_version AND NOT candidate.is_current
                ), retired AS (
                    UPDATE armi.mood_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.mood_revision_id=input.old_id
                      AND previous.mood_version=input.old_version AND previous.is_current
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.mood_revisions AS current SET is_current=true
                FROM target, retired WHERE current.mood_revision_id=target.mood_revision_id""",
                (
                    target_revision_id,
                    target_version,
                    subject_id,
                    current_revision_id,
                    current_version,
                ),
            ).rowcount
            == 1
        )

    def find_current(
        self, transaction: PostgreSQLAdminTransaction, *, kind: str
    ) -> tuple[UUID, int] | None:
        self._require_kind(kind)
        row = transaction.execute(
            """SELECT mood_revision_id,mood_version FROM armi.mood_revisions WHERE is_current """
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))

    @staticmethod
    def _require_kind(kind: str) -> None:
        if kind != "mood":
            raise MoodViolation("MOOD-KIND")


__all__ = ("PostgreSQLMoodAdmin",)
