"""Synchronous Admin adapters owned by the mood module."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._domain import consideration_signals, validate_state
from ._event_storage import EVENT_QUERY, parse_events
from .api import MoodAdminComponent, MoodCorrectionHead, MoodViolation


class PostgreSQLMoodAdmin:
    __slots__ = ()

    def consideration_signals(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        as_of: datetime,
        minimum_delay_seconds: int,
    ) -> tuple[ConsiderationSignal, ...]:
        events = parse_events(
            transaction.execute(EVENT_QUERY, (None, None, as_of, as_of, 7)).fetchall()
        )
        return consideration_signals(
            events, as_of=as_of, minimum_delay_seconds=minimum_delay_seconds
        )

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
        validate_state(value)
        return cast(dict[str, object], json.loads(json.dumps(value)))

    def current_component(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MoodAdminComponent | None:
        statement = (
            "SELECT head.mood_version,revision.privacy_scope,revision.semantic_payload "
            "FROM armi.mood_heads AS head JOIN armi.mood_revisions AS revision "
            "ON revision.mood_revision_id=head.current_revision_id"
            if private
            else "SELECT head.mood_version,revision.privacy_scope FROM armi.mood_heads AS head "
            "JOIN armi.mood_revisions AS revision ON revision.mood_revision_id=head.current_revision_id"
        )
        row = transaction.execute(statement).fetchone()
        if row is None:
            return None
        return MoodAdminComponent(
            "mood", int(cast(int, row[0])), str(row[1]), row[2] if private else None
        )

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
            "SELECT head.current_revision_id,head.mood_version,revision.semantic_payload,"
            "(SELECT max(candidate.mood_version) FROM armi.mood_revisions AS candidate "
            "WHERE candidate.subject_id=head.subject_id) FROM armi.mood_heads AS head "
            "JOIN armi.mood_revisions AS revision ON revision.mood_revision_id=head.current_revision_id "
            "WHERE head.subject_id=%s" + suffix,
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
            "previous_revision_id,origin_kind,origin_ref,subject_commit_id,proposal_ref,"
            "semantic_payload,privacy_scope) VALUES (%s,%s,%s,%s,'admin_correction',"
            "%s,NULL,NULL,%s::jsonb,'private')",
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
                "UPDATE armi.mood_heads SET current_revision_id=%s,mood_version=%s "
                "WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s",
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
        return (
            transaction.execute(
                "UPDATE armi.mood_heads SET current_revision_id=%s,mood_version=%s "
                "WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s",
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
            "SELECT current_revision_id,mood_version FROM armi.mood_heads"
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))

    @staticmethod
    def _require_kind(kind: str) -> None:
        if kind != "mood":
            raise MoodViolation("MOOD-KIND")


__all__ = ("PostgreSQLMoodAdmin",)
