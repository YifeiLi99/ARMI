"""Synchronous Admin adapters owned by subject-state."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID, uuid7

from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._domain import validate_state
from .api import (
    SubjectStateAdminComponent,
    SubjectStateCorrectionHead,
    SubjectStateKind,
    SubjectStateViolation,
)


class PostgreSQLSubjectStateAdmin:
    __slots__ = ()

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
            "UPDATE armi.subject_component_revisions SET admin_change_id=%s WHERE component_revision_id=%s",
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
        try:
            parsed_kind = SubjectStateKind(kind)
            if type(replacement) is not dict:
                raise ValueError
            value = cast(dict[str, object], replacement)
            validate_state(parsed_kind, value)
            return cast(dict[str, object], json.loads(json.dumps(value)))
        except TypeError, ValueError:
            raise SubjectStateViolation("SUBJECT-STATE-CORRECTION") from None

    def current_components(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]:
        statement = (
            """SELECT head.component_kind,head.component_version,head.privacy_scope,head.semantic_payload FROM armi.subject_component_revisions AS head WHERE head.is_current  ORDER BY head.component_kind"""
            if private
            else """SELECT head.component_kind,head.component_version,head.privacy_scope FROM armi.subject_component_revisions AS head WHERE head.is_current  ORDER BY head.component_kind"""
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
            """SELECT head.component_revision_id,head.component_version,head.semantic_payload,(SELECT max(candidate.component_version) FROM armi.subject_component_revisions AS candidate WHERE candidate.subject_id=head.subject_id AND candidate.component_kind=head.component_kind) FROM armi.subject_component_revisions AS head WHERE head.is_current AND head.subject_id=%s AND head.component_kind=%s"""
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
        replacement = self.canonicalize_replacement(kind=kind, replacement=replacement)
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
                """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::text AS component_kind, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.component_revision_id
                    FROM armi.subject_component_revisions AS candidate, input
                    WHERE candidate.component_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.component_version=input.new_version AND NOT candidate.is_current AND candidate.component_kind=input.component_kind
                ), retired AS (
                    UPDATE armi.subject_component_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.component_revision_id=input.old_id
                      AND previous.component_version=input.old_version AND previous.is_current AND previous.component_kind=input.component_kind
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.subject_component_revisions AS current SET is_current=true
                FROM target, retired WHERE current.component_revision_id=target.component_revision_id""",
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
        if current_revision_id == target_revision_id:
            return (
                current_version == target_version
                and transaction.execute(
                    "SELECT 1 FROM armi.subject_component_revisions WHERE subject_id=%s AND component_revision_id=%s AND component_version=%s AND is_current AND component_kind=%s FOR UPDATE",
                    (subject_id, current_revision_id, current_version, kind),
                ).fetchone()
                is not None
            )
        return (
            transaction.execute(
                """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::text AS component_kind, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.component_revision_id
                    FROM armi.subject_component_revisions AS candidate, input
                    WHERE candidate.component_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.component_version=input.new_version AND NOT candidate.is_current AND candidate.component_kind=input.component_kind
                ), retired AS (
                    UPDATE armi.subject_component_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.component_revision_id=input.old_id
                      AND previous.component_version=input.old_version AND previous.is_current AND previous.component_kind=input.component_kind
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.subject_component_revisions AS current SET is_current=true
                FROM target, retired WHERE current.component_revision_id=target.component_revision_id""",
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
            """SELECT head.component_revision_id,head.component_version FROM armi.subject_component_revisions AS head WHERE head.is_current AND head.component_kind=%s""",
            (kind,),
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))


__all__ = ("PostgreSQLSubjectStateAdmin",)
