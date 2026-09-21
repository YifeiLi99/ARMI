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
        # Lock the permanent first revision before reading a replaceable current row.
        tx.execute(
            "SELECT activity_revision_id FROM armi.activity_revisions "
            "WHERE activity_id=%s AND revision_no=1 FOR UPDATE",
            (command.object_id,),
        )
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT r.activity_revision_id,r.revision_no,r.status,r.goal,r.progress_summary,"
                "r.activity_kind,r.origin_opportunity_id,r.origin_admin_change_id,"
                "r.activity_created_at,r.privacy_scope "
                "FROM armi.activity_revisions r WHERE r.activity_id=%s "
                "AND r.subject_id=%s AND r.is_current",
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
        if row is not None:
            tx.execute(
                "UPDATE armi.activity_revisions SET is_current=false "
                "WHERE activity_revision_id=%s",
                (row[0],),
            )
        tx.execute(
            "INSERT INTO armi.activity_revisions (activity_revision_id,activity_id,revision_no,"
            "previous_revision_id,admin_change_id,goal,progress_summary,next_safe_step,status,terminal_reason,transition_kind,"
            "subject_id,activity_kind,origin_opportunity_id,origin_admin_change_id,activity_created_at,privacy_scope) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,statement_timestamp()),%s)",
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
                context.subject_id,
                "self_directed" if row is None else row[5],
                None if row is None else row[6],
                context.change_id if row is None else row[7],
                None if row is None else row[8],
                "private" if row is None else row[9],
            ),
        )
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "state": "abandoned" if deleted else values["status"],
            "history_retained": True,
            "physical_rows_deleted": 0,
        }


__all__ = ("PostgreSQLActivityAdmin",)
