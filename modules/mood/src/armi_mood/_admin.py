"""Synchronous Admin adapters owned by the mood module."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ._domain import validate_state
from .api import MoodAdminComponent, MoodCorrectionHead, MoodViolation

_SEARCH_PATH = "pg_catalog, armi"


class PostgreSQLMoodAdmin:
    __slots__ = ("_conninfo", "_expected_role")

    def __init__(
        self, conninfo: str | None = None, *, expected_role: str | None = None
    ) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role

    def current_component(self, *, private: bool) -> MoodAdminComponent | None:
        if self._conninfo is None or self._expected_role is None:
            raise RuntimeError("mood Admin read is not configured")
        pool = ConnectionPool(
            self._conninfo,
            min_size=0,
            max_size=1,
            open=False,
            configure=self._configure,
            reset=self._reset,
        )
        try:
            pool.open(wait=True, timeout=5.0)
            with pool.connection() as connection:
                row = connection.execute(
                    "SELECT session_user,current_user,current_setting('search_path')"
                ).fetchone()
                if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                    raise RuntimeError("mood Admin role mismatch")
                connection.execute("SET TRANSACTION READ ONLY")
                row = connection.execute(
                    "SELECT head.mood_version,revision.privacy_scope"
                    + (",revision.semantic_payload" if private else "")
                    + " FROM armi.mood_heads AS head JOIN armi.mood_revisions AS revision ON revision.mood_revision_id=head.current_revision_id"
                ).fetchone()
                if row is None:
                    return None
                return MoodAdminComponent(
                    "mood", int(row[0]), str(row[1]), row[2] if private else None
                )
        finally:
            pool.close()

    def _configure(self, connection: psycopg.Connection[Any]) -> None:
        connection.autocommit = True
        connection.execute("SET search_path TO pg_catalog, armi")

    def _reset(self, connection: psycopg.Connection[Any]) -> None:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            connection.rollback()
        connection.execute("RESET ROLE")
        connection.execute("RESET ALL")
        connection.execute("SET search_path TO pg_catalog, armi")

    def current_head(
        self,
        transaction: Any,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> MoodCorrectionHead | None:
        self._require_kind(kind)
        suffix = " FOR UPDATE OF head" if for_update else ""
        row = transaction.execute(
            "SELECT head.current_revision_id,head.mood_version,revision.semantic_payload,(SELECT max(candidate.mood_version) FROM armi.mood_revisions AS candidate WHERE candidate.subject_id=head.subject_id) FROM armi.mood_heads AS head JOIN armi.mood_revisions AS revision ON revision.mood_revision_id=head.current_revision_id WHERE head.subject_id=%s"
            + suffix,
            (subject_id,),
        ).fetchone()
        return (
            None
            if row is None
            else MoodCorrectionHead(row[0], int(row[1]), row[2], int(row[3]))
        )

    def revision(
        self,
        transaction: Any,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
    ) -> tuple[UUID, int] | None:
        self._require_kind(kind)
        row = transaction.execute(
            "SELECT mood_revision_id,mood_version FROM armi.mood_revisions WHERE mood_revision_id=%s AND subject_id=%s",
            (revision_id, subject_id),
        ).fetchone()
        return None if row is None else (row[0], int(row[1]))

    def replace(
        self,
        transaction: Any,
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
            "INSERT INTO armi.mood_revisions (mood_revision_id,subject_id,mood_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload,privacy_scope) VALUES (%s,%s,%s,%s,'admin_correction',%s,NULL,NULL,%s,'private')",
            (
                revision_id,
                subject_id,
                version,
                previous_revision_id,
                revision_id,
                Jsonb(replacement),
            ),
        )
        return (
            transaction.execute(
                "UPDATE armi.mood_heads SET current_revision_id=%s,mood_version=%s WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s",
                (
                    revision_id,
                    version,
                    subject_id,
                    previous_revision_id,
                    version - 1,
                ),
            ).rowcount
            == 1
        )

    def repair_head(
        self,
        transaction: Any,
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
                "UPDATE armi.mood_heads SET current_revision_id=%s,mood_version=%s WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s",
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

    def find_current(self, transaction: Any, *, kind: str) -> tuple[UUID, int] | None:
        self._require_kind(kind)
        row = transaction.execute(
            "SELECT current_revision_id,mood_version FROM armi.mood_heads"
        ).fetchone()
        return None if row is None else (row[0], int(row[1]))

    @staticmethod
    def _require_kind(kind: str) -> None:
        if kind != "mood":
            raise MoodViolation("MOOD-KIND")


__all__ = ("PostgreSQLMoodAdmin",)
