"""Material-owned online administrator revisions and soft deletion."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid7

from armi_artifact_store.life_material_codec import build_life_material_artifact
from armi_kernel.application import ArtifactRef
from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._domain import valid_metadata
from .api import LifeMaterialKind, MaterialViolation


class PostgreSQLMaterialAdminContent:
    def prepare_content(
        self, command: AdminContentCommand
    ) -> tuple[bytes, str, str] | None:
        values = cast(dict[str, Any], command.values)
        if command.action == "delete":
            if values:
                raise MaterialViolation("MATERIAL-ADMIN-PAYLOAD")
            return None
        fields = {"title", "body", "metadata", "privacy_status", "material_status"}
        if command.action == "create":
            fields.add("material_kind")
        if set(values) != fields:
            raise MaterialViolation("MATERIAL-ADMIN-PAYLOAD")
        if command.action == "create":
            LifeMaterialKind(values["material_kind"])
        if (
            type(values["title"]) is not str
            or not 1 <= len(values["title"]) <= 256
            or type(values["metadata"]) is not dict
            or not valid_metadata(
                tuple(sorted(cast(dict[str, str], values["metadata"]).items()))
            )
            or values["privacy_status"] not in {"creator_visible", "private"}
            or (
                command.action == "create"
                and values["privacy_status"] != "creator_visible"
            )
            or values["material_status"] not in {"active", "archived"}
            or type(values["body"]) is not str
            or not values["body"].strip()
            or len(values["body"].encode("utf-8")) > 65536
            or "\x00" in values["body"]
            or "\x00" in values["title"]
        ):
            raise MaterialViolation("MATERIAL-ADMIN-PAYLOAD")
        return (
            build_life_material_artifact(values["body"].encode("utf-8")),
            "life.material.content",
            "application/json",
        )

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
                "SELECT h.current_revision_id,h.head_version,h.deleted_at,r.artifact_id,r.title,r.metadata,r.material_status FROM armi.life_materials h JOIN armi.life_material_revisions r ON r.life_material_revision_id=h.current_revision_id WHERE h.life_material_id=%s AND h.subject_id=%s FOR UPDATE OF h",
                (command.object_id, context.subject_id),
            ).fetchone(),
        )
        if command.action == "create":
            if row is not None or command.expected_version != 0:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif row is None or row[1] != command.expected_version or row[2] is not None:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        deleted = command.action == "delete"
        if deleted:
            if row is None or values:
                raise MaterialViolation("MATERIAL-ADMIN-PAYLOAD")
            artifact, title, metadata, status = row[3:7]
        else:
            publication = values["_prepared_artifact"]
            if (
                not isinstance(publication, ArtifactRef)
                or publication.logical_kind != "life.material.content"
            ):
                raise MaterialViolation("MATERIAL-ARTIFACT")
            artifact, title, metadata, status = (
                publication.artifact_id.value,
                values["title"],
                values["metadata"],
                values["material_status"],
            )
        revision = uuid7()
        version = command.expected_version + 1
        if row is None:
            tx.execute(
                "INSERT INTO armi.life_materials (life_material_id,subject_id,material_kind,owner_party_id,current_revision_id,head_version) VALUES (%s,%s,%s,%s,%s,1)",
                (
                    command.object_id,
                    context.subject_id,
                    values["material_kind"],
                    context.subject_party_id,
                    revision,
                ),
            )
        tx.execute(
            "INSERT INTO armi.life_material_revisions (life_material_revision_id,life_material_id,revision_no,previous_revision_id,admin_change_id,artifact_id,title,metadata,revision_kind,privacy_status,material_status,source_kind) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,'administrator')",
            (
                revision,
                command.object_id,
                version,
                None if row is None else row[0],
                context.change_id,
                artifact,
                title,
                json.dumps(metadata),
                "deleted" if deleted else "created" if row is None else "updated",
                "restricted" if deleted else values["privacy_status"],
                status,
            ),
        )
        if row is not None:
            changed = tx.execute(
                "UPDATE armi.life_materials SET current_revision_id=%s,head_version=%s,updated_at=statement_timestamp(),"
                "deleted_at=CASE WHEN %s THEN statement_timestamp() ELSE deleted_at END "
                "WHERE life_material_id=%s AND current_revision_id=%s AND head_version=%s",
                (
                    revision,
                    version,
                    deleted,
                    command.object_id,
                    row[0],
                    command.expected_version,
                ),
            )
            if changed.rowcount != 1:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "history_retained": True,
            "physical_rows_deleted": 0,
            "artifacts_retained": True,
            "state": "deleted" if deleted else status,
        }


__all__ = ("PostgreSQLMaterialAdminContent",)
