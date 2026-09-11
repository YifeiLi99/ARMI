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
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT h.current_revision_id,COALESCE(r.revision_no,0),r.content_artifact_id,r.content_digest,h.prompt_kind "
                "FROM armi.prompt_documents h LEFT JOIN armi.prompt_revisions r ON r.prompt_revision_id=h.current_revision_id "
                "WHERE h.prompt_document_id=%s AND h.subject_id=%s FOR UPDATE OF h",
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
            tx.execute(
                "INSERT INTO armi.prompt_documents (prompt_document_id,subject_id,prompt_kind,write_authority) VALUES (%s,%s,%s,%s)",
                (
                    command.object_id,
                    context.subject_id,
                    kind,
                    "creator" if kind == "creator_guidance" else "subject",
                ),
            )
        revision = uuid7()
        tx.execute(
            "INSERT INTO armi.prompt_revisions (prompt_revision_id,prompt_document_id,revision_no,previous_revision_id,"
            "content_artifact_id,content_digest,admin_change_id,change_reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                revision,
                command.object_id,
                version + 1,
                None if row is None else row[0],
                artifact,
                digest,
                context.change_id,
                "deactivated" if deleted else "created" if version == 0 else "revised",
            ),
        )
        result = tx.execute(
            "UPDATE armi.prompt_documents SET current_revision_id=%s,status=%s WHERE prompt_document_id=%s "
            "AND current_revision_id IS NOT DISTINCT FROM %s",
            (
                revision,
                "inactive" if deleted else "active",
                command.object_id,
                None if row is None else row[0],
            ),
        )
        if result.rowcount != 1:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
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
