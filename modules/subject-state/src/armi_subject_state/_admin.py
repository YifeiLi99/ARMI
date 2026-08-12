"""Synchronous Admin adapters for subject-state observation and correction."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .api import (
    SubjectStateAdminComponent,
    SubjectStateCorrectionHead,
    SubjectStateKind,
)

_SEARCH_PATH = "pg_catalog, armi"


class PostgreSQLSubjectStateAdmin:
    __slots__ = ("_conninfo", "_expected_role")

    def __init__(
        self, conninfo: str | None = None, *, expected_role: str | None = None
    ) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role

    def current_components(
        self, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]:
        if self._conninfo is None or self._expected_role is None:
            raise RuntimeError("subject-state Admin read is not configured")
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
                    raise RuntimeError("subject-state Admin role mismatch")
                connection.execute("SET TRANSACTION READ ONLY")
                return self.current_components_on(connection, private=private)
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

    def current_components_on(
        self, connection: Any, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]:
        rows = connection.execute(
            "SELECT head.component_kind, head.component_version, revision.privacy_scope"
            + (", revision.semantic_payload" if private else "")
            + " FROM armi.subject_component_heads AS head JOIN armi.subject_component_revisions AS revision ON revision.component_revision_id=head.current_revision_id ORDER BY head.component_kind"
        ).fetchall()
        return tuple(
            SubjectStateAdminComponent(
                SubjectStateKind(str(row[0])),
                int(row[1]),
                str(row[2]),
                row[3] if private else None,
            )
            for row in rows
        )

    def current_head(
        self, transaction: Any, *, subject_id: str, kind: str, for_update: bool
    ) -> SubjectStateCorrectionHead | None:
        suffix = " FOR UPDATE OF head" if for_update else ""
        row = transaction.execute(
            "SELECT head.current_revision_id,head.component_version,revision.semantic_payload,(SELECT max(candidate.component_version) FROM armi.subject_component_revisions AS candidate WHERE candidate.subject_id=head.subject_id AND candidate.component_kind=head.component_kind) FROM armi.subject_component_heads AS head JOIN armi.subject_component_revisions AS revision ON revision.component_revision_id=head.current_revision_id WHERE head.subject_id=%s AND head.component_kind=%s"
            + suffix,
            (subject_id, kind),
        ).fetchone()
        return (
            None
            if row is None
            else SubjectStateCorrectionHead(row[0], int(row[1]), row[2], int(row[3]))
        )

    def revision(
        self, transaction: Any, *, revision_id: str, subject_id: str, kind: str
    ) -> tuple[UUID, int] | None:
        row = transaction.execute(
            "SELECT component_revision_id,component_version FROM armi.subject_component_revisions WHERE component_revision_id=%s AND subject_id=%s AND component_kind=%s",
            (revision_id, subject_id, kind),
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
        transaction.execute(
            "INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,component_kind,component_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload,privacy_scope) VALUES (%s,%s,%s,%s,%s,'admin_correction',%s,NULL,NULL,%s,'private')",
            (
                revision_id,
                subject_id,
                kind,
                version,
                previous_revision_id,
                revision_id,
                Jsonb(replacement),
            ),
        )
        return (
            transaction.execute(
                "UPDATE armi.subject_component_heads SET current_revision_id=%s,component_version=%s WHERE subject_id=%s AND component_kind=%s AND current_revision_id=%s AND component_version=%s",
                (
                    revision_id,
                    version,
                    subject_id,
                    kind,
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
        return (
            transaction.execute(
                "UPDATE armi.subject_component_heads SET current_revision_id=%s,component_version=%s WHERE subject_id=%s AND component_kind=%s AND current_revision_id=%s AND component_version=%s",
                (
                    target_revision_id,
                    target_version,
                    subject_id,
                    kind,
                    current_revision_id,
                    current_version,
                ),
            ).rowcount
            == 1
        )

    def find_current(self, transaction: Any, *, kind: str) -> tuple[UUID, int] | None:
        row = transaction.execute(
            "SELECT head.current_revision_id,head.component_version FROM armi.subject_component_heads AS head JOIN armi.subject_component_revisions AS revision ON revision.component_revision_id=head.current_revision_id WHERE head.component_kind=%s",
            (kind,),
        ).fetchone()
        return None if row is None else (row[0], int(row[1]))


__all__ = ("PostgreSQLSubjectStateAdmin",)
