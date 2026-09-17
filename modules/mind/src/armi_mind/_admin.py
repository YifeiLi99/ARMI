"""Authorized administration of Mind; no Subject State intermediary."""

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
from .api import MindAdminState, MindCorrectionHead, MindViolation


def _kind(kind: str) -> None:
    if kind != "mind":
        raise MindViolation("MIND-KIND")


class PostgreSQLMindAdmin:
    def apply(
        self,
        transaction: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, object]:
        if command.action != "update" or set(command.values) != {"replacement"}:
            raise AdminContentViolation("ADMIN-CONTENT-COMPONENT-OPERATION")
        if command.object_id != context.subject_id:
            raise AdminContentViolation("ADMIN-CONTENT-SUBJECT-CONFLICT")
        head = self.current_head(
            transaction,
            subject_id=str(context.subject_id),
            kind="mind",
            for_update=True,
        )
        if (
            head is None
            or head.current_version != command.expected_version
            or head.maximum_version != head.current_version
        ):
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        revision_id = uuid7()
        if not self.replace(
            transaction,
            revision_id=str(revision_id),
            subject_id=str(context.subject_id),
            kind="mind",
            version=head.current_version + 1,
            previous_revision_id=str(head.current_revision_id),
            replacement=command.values["replacement"],
        ):
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        transaction.execute(
            "UPDATE armi.mind_revisions SET admin_change_id=%s WHERE mind_revision_id=%s",
            (context.change_id, revision_id),
        )
        return {
            "object_id": str(context.subject_id),
            "component_kind": "mind",
            "revision_id": str(revision_id),
            "new_version": head.current_version + 1,
            "history_retained": True,
            "physical_rows_deleted": 0,
        }

    def canonicalize_replacement(
        self, *, kind: str, replacement: object
    ) -> dict[str, object]:
        _kind(kind)
        try:
            if type(replacement) is not dict:
                raise ValueError
            value = cast(dict[str, object], replacement)
            validate_state(value)
            return cast(dict[str, object], json.loads(json.dumps(value)))
        except TypeError, ValueError:
            raise MindViolation("MIND-CORRECTION") from None

    def current(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MindAdminState:
        row = transaction.execute(
            "SELECT h.mind_version,r.privacy_scope,r.semantic_payload FROM armi.mind_heads h JOIN armi.mind_revisions r ON r.mind_revision_id=h.current_revision_id"
            if private
            else "SELECT h.mind_version,r.privacy_scope FROM armi.mind_heads h JOIN armi.mind_revisions r ON r.mind_revision_id=h.current_revision_id"
        ).fetchone()
        if row is None:
            raise MindViolation("MIND-MISSING")
        return MindAdminState(
            int(cast(int, row[0])), str(row[1]), row[2] if private else None
        )

    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> MindCorrectionHead | None:
        _kind(kind)
        row = transaction.execute(
            "SELECT h.current_revision_id,h.mind_version,r.semantic_payload,"
            "(SELECT max(mind_version) FROM armi.mind_revisions WHERE subject_id=h.subject_id) "
            "FROM armi.mind_heads h JOIN armi.mind_revisions r ON r.mind_revision_id=h.current_revision_id WHERE h.subject_id=%s"
            + (" FOR UPDATE OF h" if for_update else ""),
            (subject_id,),
        ).fetchone()
        return (
            None
            if row is None
            else MindCorrectionHead(
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
        _kind(kind)
        row = transaction.execute(
            "SELECT mind_revision_id,mind_version FROM armi.mind_revisions WHERE mind_revision_id=%s AND subject_id=%s",
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
        value = self.canonicalize_replacement(kind=kind, replacement=replacement)
        previous = transaction.execute(
            "SELECT semantic_payload FROM armi.mind_revisions WHERE mind_revision_id=%s AND subject_id=%s",
            (previous_revision_id, subject_id),
        ).fetchone()
        if previous is None:
            raise MindViolation("MIND-MISSING")
        concerns = cast(dict[str, object], previous[0])["concerns"]
        if "concerns" in value and value["concerns"] != concerns:
            raise MindViolation("MIND-CONCERN-REPLACEMENT")
        value = {**value, "concerns": concerns}
        transaction.execute(
            "INSERT INTO armi.mind_revisions (mind_revision_id,subject_id,mind_version,previous_revision_id,origin_kind,origin_ref,semantic_payload,privacy_scope) "
            "VALUES (%s,%s,%s,%s,'admin_correction',%s,%s::jsonb,'private')",
            (
                revision_id,
                subject_id,
                version,
                previous_revision_id,
                revision_id,
                json.dumps(value, ensure_ascii=False),
            ),
        )
        return (
            transaction.execute(
                "UPDATE armi.mind_heads SET current_revision_id=%s,mind_version=%s WHERE subject_id=%s AND current_revision_id=%s AND mind_version=%s",
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
        _kind(kind)
        rows = transaction.execute(
            "SELECT mind_revision_id,semantic_payload FROM armi.mind_revisions WHERE subject_id=%s AND mind_revision_id IN (%s,%s)",
            (subject_id, current_revision_id, target_revision_id),
        ).fetchall()
        payloads = {str(row[0]): cast(dict[str, object], row[1]) for row in rows}
        current, target = (
            payloads.get(current_revision_id),
            payloads.get(target_revision_id),
        )
        if (
            current is None
            or target is None
            or target.get("schema_version") != "armi.mind.v3"
            or current.get("concerns") != target.get("concerns")
        ):
            raise MindViolation("MIND-CONCERN-REPLACEMENT")
        return (
            transaction.execute(
                "UPDATE armi.mind_heads SET current_revision_id=%s,mind_version=%s WHERE subject_id=%s AND current_revision_id=%s AND mind_version=%s",
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
        _kind(kind)
        row = transaction.execute(
            "SELECT current_revision_id,mind_version FROM armi.mind_heads"
        ).fetchone()
        return None if row is None else (cast(UUID, row[0]), int(cast(int, row[1])))


__all__ = ("PostgreSQLMindAdmin",)
