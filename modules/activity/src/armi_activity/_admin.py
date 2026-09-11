"""Administrative content/status changes without synthetic Activity decisions."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from .api import ActivityViolation


class PostgreSQLActivityAdmin:
    def apply(
        self,
        tx: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, Any]:
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT h.current_revision_id,h.head_version,r.status,r.goal,r.progress_summary "
                "FROM armi.activities h LEFT JOIN armi.activity_revisions r "
                "ON r.activity_revision_id=h.current_revision_id WHERE h.activity_id=%s "
                "AND h.subject_id=%s FOR UPDATE OF h",
                (command.object_id, context.subject_id),
            ).fetchone(),
        )
        if command.action == "create":
            if row is not None or command.expected_version != 0:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif row is None or row[1] != command.expected_version:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif row[2] in {"completed", "abandoned", "failed"}:
            raise ActivityViolation("ACTIVITY-ADMIN-TERMINAL")
        values = cast(dict[str, Any], command.values)
        deleted = command.action == "delete"
        if deleted:
            if values or row is None:
                raise ActivityViolation("ACTIVITY-ADMIN-PAYLOAD")
            goal, progress, step = row[3], row[4], None
        else:
            if set(values) != {"goal", "progress_summary", "next_safe_step", "status"}:
                raise ActivityViolation("ACTIVITY-ADMIN-PAYLOAD")
            if values["status"] not in {"ready", "paused"} or (
                command.action == "create" and values["status"] != "ready"
            ):
                raise ActivityViolation("ACTIVITY-ADMIN-STATE")
            goal, progress, step = (
                values["goal"],
                values["progress_summary"],
                values["next_safe_step"],
            )
            if (
                type(goal) is not str
                or not 1 <= len(goal.encode("utf-8")) <= 8192
                or type(step) is not str
                or not 1 <= len(step.encode("utf-8")) <= 4096
                or (
                    progress is not None
                    and (type(progress) is not str or not 1 <= len(progress) <= 4096)
                )
                or any(
                    "\x00" in v for v in (goal, progress, step) if isinstance(v, str)
                )
            ):
                raise ActivityViolation("ACTIVITY-ADMIN-PAYLOAD")
        revision = uuid7()
        version = command.expected_version + 1
        if row is None:
            tx.execute(
                "INSERT INTO armi.activities (activity_id,subject_id,activity_kind,"
                "privacy_scope,admin_change_id) VALUES (%s,%s,'self_directed','private',%s)",
                (command.object_id, context.subject_id, context.change_id),
            )
        tx.execute(
            "INSERT INTO armi.activity_revisions (activity_revision_id,activity_id,revision_no,"
            "previous_revision_id,admin_change_id,goal,progress_summary,next_safe_step,status,terminal_reason,transition_kind) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                revision,
                command.object_id,
                version,
                None if row is None else row[0],
                context.change_id,
                goal,
                progress,
                step,
                "abandoned" if deleted else values["status"],
                "administrator_deleted" if deleted else None,
                "admin_delete"
                if deleted
                else "created"
                if row is None
                else "admin_update",
            ),
        )
        result = tx.execute(
            "UPDATE armi.activities SET current_revision_id=%s,head_version=%s "
            "WHERE activity_id=%s AND current_revision_id IS NOT DISTINCT FROM %s AND head_version=%s",
            (
                revision,
                version,
                command.object_id,
                None if row is None else row[0],
                command.expected_version,
            ),
        )
        if result.rowcount != 1:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "state": "abandoned" if deleted else values["status"],
            "history_retained": True,
            "physical_rows_deleted": 0,
        }


__all__ = ("PostgreSQLActivityAdmin",)
