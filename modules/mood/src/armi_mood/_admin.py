"""Synchronous Admin adapters owned by the mood module."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from ._domain import validate_state
from .api import MoodAdminComponent, MoodCorrectionHead, MoodViolation


class PostgreSQLMoodAdmin:
    __slots__ = ()

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
        self._require_kind(kind)
        if type(replacement) is not dict:
            raise MoodViolation("MOOD-STATE")
        validate_state(cast(dict[str, object], replacement))
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
