"""Prompt-owned administrative versions, retaining immutable personality anchors."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

from armi_kernel.application import ArtifactRef
from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._domain import canonical_subject_content
from .api import MAX_CREATOR_PROMPT_BYTES, PromptViolation


class PostgreSQLPromptAdminContent:
    def prepare_content(
        self, command: AdminContentCommand
    ) -> tuple[bytes, str, str] | None:
        values = cast(dict[str, Any], command.values)
        if command.action == "delete":
            if values:
                raise PromptViolation("PROMPT-ADMIN-PAYLOAD")
            return None
        if values.get("prompt_kind") not in {"creator_guidance", "subject_guidance"}:
            raise PromptViolation("PROMPT-ADMIN-AUTHORITY")
        if set(values) != {"prompt_kind", "content"}:
            raise PromptViolation("PROMPT-ADMIN-PAYLOAD")
        if values["prompt_kind"] == "subject_guidance":
            return (
                canonical_subject_content(values["content"]),
                "subject.prompt.content",
                "application/json",
            )
        body = values["content"]
        if type(body) is not str or not body.strip() or "\x00" in body:
            raise PromptViolation("PROMPT-ADMIN-PAYLOAD")
        encoded = body.encode("utf-8")
        if not 1 <= len(encoded) <= MAX_CREATOR_PROMPT_BYTES:
            raise PromptViolation("PROMPT-ADMIN-PAYLOAD")
        return encoded, "creator.prompt.text", "text/plain"

    def apply(
        self,
        tx: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, Any]:
        values = cast(dict[str, Any], command.values)
        # Share the owner lock with Creator writes and cognition, including first creation.
        for kind_to_lock in ("creator_guidance", "subject_guidance"):
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"prompt:{context.subject_id}:{kind_to_lock}",),
            )
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT r.prompt_revision_id,r.revision_no,r.content_artifact_id,r.content_digest,r.prompt_kind "
                "FROM armi.prompt_revisions r "
                "WHERE r.prompt_document_id=%s AND r.subject_id=%s AND r.is_current FOR UPDATE",
                (command.object_id, context.subject_id),
            ).fetchone(),
        )
        kind = (
            row[4]
            if command.action == "delete" and row is not None
            else values.get("prompt_kind")
        )
        if kind not in {"creator_guidance", "subject_guidance"} or (
            row is not None and row[4] != kind
        ):
            raise PromptViolation("PROMPT-ADMIN-AUTHORITY")
        version = 0 if row is None else int(row[1])
        if version != command.expected_version or (command.action == "create") != (
            version == 0
        ):
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        deleted = command.action == "delete"
        if deleted:
            if row is None or row[0] is None:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
            artifact, digest = row[2], row[3]
        else:
            prepared = values["_prepared_artifact"]
            if not isinstance(prepared, ArtifactRef):
                raise PromptViolation("PROMPT-ARTIFACT")
            artifact, digest = prepared.artifact_id.value, prepared.content_digest.value
        if row is None:
            existing = tx.execute(
                "SELECT 1 FROM armi.prompt_revisions WHERE subject_id=%s AND prompt_kind=%s AND is_current",
                (context.subject_id, kind),
            ).fetchone()
            if existing is not None:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        else:
            tx.execute(
                "UPDATE armi.prompt_revisions SET is_current=false WHERE prompt_revision_id=%s",
                (row[0],),
            )
        revision = uuid7()
        tx.execute(
            "INSERT INTO armi.prompt_revisions (prompt_revision_id,prompt_document_id,revision_no,previous_revision_id,"
            "content_artifact_id,content_digest,admin_change_id,change_reason,subject_id,prompt_kind,status,is_current) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",
            (
                revision,
                command.object_id,
                version + 1,
                None if row is None else row[0],
                artifact,
                digest,
                context.change_id,
                "deactivated" if deleted else "created" if version == 0 else "revised",
                context.subject_id,
                kind,
                "inactive" if deleted else "active",
            ),
        )
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version + 1,
            "history_retained": True,
            "physical_rows_deleted": 0,
            "artifacts_retained": True,
            "state": "inactive" if deleted else "active",
        }


__all__ = ("PostgreSQLPromptAdminContent",)
