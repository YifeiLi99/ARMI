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
        tx.execute(
            "SELECT memory_revision_id FROM armi.subjective_memory_revisions "
            "WHERE memory_id=%s AND revision_no=1 FOR UPDATE",
            (command.object_id,),
        )
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT memory_revision_id,revision_no,accessibility,tombstoned_at,memory_created_at FROM armi.subjective_memory_revisions WHERE memory_id=%s AND subject_id=%s AND is_current",
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
        if row is not None:
            tx.execute(
                "UPDATE armi.subjective_memory_revisions SET is_current=false "
                "WHERE memory_revision_id=%s",
                (row[0],),
            )
        deleted = command.action == "delete"
        tx.execute(
            "INSERT INTO armi.subjective_memory_revisions "
            "(memory_revision_id,memory_id,subject_id,memory_created_at,revision_no,previous_revision_id,admin_change_id,"
            "source_kind,source_fact_class,summary,uncertainty,revision_kind,accessibility,"
            "mechanism_identity,mechanism_config_identity) "
            "VALUES (%s,%s,%s,COALESCE(%s,statement_timestamp()),%s,%s,%s,'administrator','external_claim',%s,%s,%s,%s,"
            "'armi.memory.admin','admin')",
            (
                revision,
                command.object_id,
                context.subject_id,
                None if row is None else row[4],
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
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "history_retained": True,
            "physical_rows_deleted": 0,
            "state": "forgotten" if deleted else values["accessibility"],
        }


__all__ = ("PostgreSQLMemoryAdmin",)
