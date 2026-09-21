"""Memory-owned administrative revisions; never fabricate accepted experiences."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from .api import MemoryAccessibility, MemoryViolation, valid_memory_text


class PostgreSQLMemoryAdmin:
    def apply(
        self,
        tx: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, Any]:
        values = cast(dict[str, Any], command.values)
        if command.action == "delete":
            if values:
                raise MemoryViolation("MEMORY-ADMIN-PAYLOAD")
        elif (
            set(values) != {"summary", "uncertainty", "accessibility"}
            or not valid_memory_text(values["summary"], 512)
            or not valid_memory_text(values["uncertainty"], 512, optional=True)
            or values["accessibility"] not in {"available", "faded"}
            or (command.action == "create" and values["accessibility"] != "available")
        ):
            raise MemoryViolation("MEMORY-ADMIN-PAYLOAD")
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT m.current_revision_id,m.head_version,r.accessibility,m.tombstoned_at FROM armi.subjective_memories m JOIN armi.subjective_memory_revisions r ON r.memory_revision_id=m.current_revision_id WHERE m.memory_id=%s AND m.subject_id=%s FOR UPDATE OF m",
                (command.object_id, context.subject_id),
            ).fetchone(),
        )
        if command.action == "create":
            if row is not None or command.expected_version != 0:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif row is None or row[1] != command.expected_version or row[3] is not None:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif MemoryAccessibility(str(row[2])) is MemoryAccessibility.FORGOTTEN:
            raise MemoryViolation("MEMORY-TRANSITION")
        revision = uuid7()
        version = command.expected_version + 1
        if command.action == "create":
            tx.execute(
                "INSERT INTO armi.subjective_memories (memory_id,subject_id,current_revision_id,head_version) VALUES (%s,%s,%s,1)",
                (
                    command.object_id,
                    context.subject_id,
                    revision,
                ),
            )
        deleted = command.action == "delete"
        tx.execute(
            "INSERT INTO armi.subjective_memory_revisions "
            "(memory_revision_id,memory_id,revision_no,previous_revision_id,admin_change_id,"
            "source_kind,source_fact_class,summary,uncertainty,revision_kind,accessibility,"
            "mechanism_identity,mechanism_config_identity,privacy_scope) "
            "VALUES (%s,%s,%s,%s,%s,'administrator','external_claim',%s,%s,%s,%s,"
            "'armi.memory.admin-v1','admin-v1','private')",
            (
                revision,
                command.object_id,
                version,
                None if row is None else row[0],
                context.change_id,
                None if deleted else values["summary"],
                None if deleted else values["uncertainty"],
                "forgotten"
                if deleted
                else "formed"
                if row is None
                else "reinterpreted",
                "forgotten" if deleted else values["accessibility"],
            ),
        )
        if row is not None:
            updated = tx.execute(
                "UPDATE armi.subjective_memories SET current_revision_id=%s,head_version=%s "
                "WHERE memory_id=%s AND current_revision_id=%s AND head_version=%s",
                (
                    revision,
                    version,
                    command.object_id,
                    row[0],
                    command.expected_version,
                ),
            )
            if updated.rowcount != 1:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "history_retained": True,
            "physical_rows_deleted": 0,
            "state": "forgotten" if deleted else values["accessibility"],
        }


__all__ = ("PostgreSQLMemoryAdmin",)
