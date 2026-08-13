"""Synchronous Admin adapters owned by subject-state."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import (
    SubjectStateAdminComponent,
    SubjectStateCorrectionHead,
    SubjectStateKind,
)


class PostgreSQLSubjectStateAdmin:
    __slots__ = ()

    def current_components(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]:
        statement = (
            "SELECT head.component_kind,head.component_version,revision.privacy_scope,"
            "revision.semantic_payload FROM armi.subject_component_heads AS head JOIN "
            "armi.subject_component_revisions AS revision ON revision.component_revision_id="
            "head.current_revision_id ORDER BY head.component_kind"
            if private
            else "SELECT head.component_kind,head.component_version,revision.privacy_scope "
            "FROM armi.subject_component_heads AS head JOIN armi.subject_component_revisions "
            "AS revision ON revision.component_revision_id=head.current_revision_id "
            "ORDER BY head.component_kind"
        )
        rows = transaction.execute(statement).fetchall()
        return tuple(
            SubjectStateAdminComponent(
                SubjectStateKind(str(row[0])),
                int(cast(int, row[1])),
                str(row[2]),
                row[3] if private else None,
            )
            for row in rows
        )

    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> SubjectStateCorrectionHead | None:
        suffix = " FOR UPDATE OF head" if for_update else ""
        row = transaction.execute(
            "SELECT head.current_revision_id,head.component_version,revision.semantic_payload,"
            "(SELECT max(candidate.component_version) FROM armi.subject_component_revisions "
            "AS candidate WHERE candidate.subject_id=head.subject_id AND candidate.component_kind="
            "head.component_kind) FROM armi.subject_component_heads AS head JOIN "
            "armi.subject_component_revisions AS revision ON revision.component_revision_id="
            "head.current_revision_id WHERE head.subject_id=%s AND head.component_kind=%s"
            + suffix,
            (subject_id, kind),
        ).fetchone()
        return (
            None
            if row is None
            else SubjectStateCorrectionHead(
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
        row = transaction.execute(
            "SELECT component_revision_id,component_version FROM "
            "armi.subject_component_revisions WHERE component_revision_id=%s "
            "AND subject_id=%s AND component_kind=%s",
            (revision_id, subject_id, kind),
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
        transaction.execute(
            "INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,"
            "component_kind,component_version,previous_revision_id,origin_kind,origin_ref,"
            "subject_commit_id,proposal_ref,semantic_payload,privacy_scope) VALUES "
            "(%s,%s,%s,%s,%s,'admin_correction',%s,NULL,NULL,%s::jsonb,'private')",
            (
                revision_id,
                subject_id,
                kind,
                version,
                previous_revision_id,
                revision_id,
                json.dumps(replacement, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return (
            transaction.execute(
                "UPDATE armi.subject_component_heads SET current_revision_id=%s,"
                "component_version=%s WHERE subject_id=%s AND component_kind=%s "
                "AND current_revision_id=%s AND component_version=%s",
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
        transaction: PostgreSQLAdminTransaction,
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
                "UPDATE armi.subject_component_heads SET current_revision_id=%s,"
                "component_version=%s WHERE subject_id=%s AND component_kind=%s "
                "AND current_revision_id=%s AND component_version=%s",
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

    def find_current(
        self, transaction: PostgreSQLAdminTransaction, *, kind: str
    ) -> tuple[UUID, int] | None:
        row = transaction.execute(
            "SELECT head.current_revision_id,head.component_version FROM "
            "armi.subject_component_heads AS head JOIN armi.subject_component_revisions "
            "AS revision ON revision.component_revision_id=head.current_revision_id "
            "WHERE head.component_kind=%s",
            (kind,),
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))


__all__ = ("PostgreSQLSubjectStateAdmin",)
