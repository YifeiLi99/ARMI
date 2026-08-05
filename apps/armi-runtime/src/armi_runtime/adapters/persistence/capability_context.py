"""Read-only capability inventory projection for one ARMI subject."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import ContextViolation
from armi_kernel.contracts import Digest

type CapabilityStatePayload = tuple[UUID, int, bytes, Digest, str]
_MAX_JSON_SAFE_INTEGER = (1 << 53) - 1


async def load_capability_state_payloads(
    connection: Any,
    *,
    subject_id: UUID,
) -> tuple[CapabilityStatePayload, ...]:
    rows = await (
        await connection.execute(
            """
            SELECT capability.capability_id,
                   capability.capability_kind,
                   capability.operation_class,
                   capability.availability_status,
                   capability.configuration_version,
                   request.capability_request_id,
                   request.request_version,
                   CASE
                     WHEN request.current_status IN ('granted', 'limited')
                      AND permission.valid_until <= statement_timestamp()
                     THEN 'expired'
                     ELSE request.current_status
                   END AS effective_request_status,
                   request.resolution_reason_class,
                   request.audience_scope,
                   request.data_scope,
                   request.purpose,
                   request.workspace_scope,
                   request.artifact_scope,
                   request.network_access,
                   request.requested_valid_for_seconds,
                   request.requested_max_uses,
                   request.requested_max_payload_bytes,
                   permission.grant_id,
                   CASE
                     WHEN permission.status = 'active'
                      AND permission.valid_until <= statement_timestamp()
                     THEN 'expired'
                     ELSE permission.status
                   END AS effective_grant_status,
                   permission.valid_from,
                   permission.valid_until,
                   permission.max_uses,
                   permission.consumed_uses,
                   permission.max_payload_bytes,
                   permission.workspace_scope,
                   permission.artifact_scope,
                   permission.network_access,
                   request.created_at
            FROM armi.capabilities AS capability
            LEFT JOIN LATERAL (
                SELECT item.*
                FROM armi.capability_requests AS item
                WHERE item.subject_id = %s
                  AND item.capability_id = capability.capability_id
                ORDER BY item.created_at DESC,
                         item.capability_request_id DESC
                LIMIT 1
            ) AS request ON true
            LEFT JOIN armi.permission_grants AS permission
              ON permission.capability_request_id = request.capability_request_id
            ORDER BY capability.capability_kind
            """,
            (subject_id,),
        )
    ).fetchall()
    return tuple(_capability_state_payload(row) for row in rows)


def _capability_state_payload(row: tuple[object, ...]) -> CapabilityStatePayload:
    request_id = cast(UUID | None, row[5])
    request_status = None if row[7] is None else str(row[7])
    current_request = None
    if request_id is not None:
        requested_scope = (
            {
                "scope_kind": "creator_scene_reply",
                "audience_scope": str(row[9]),
                "data_scope": str(row[10]),
                "purpose": str(row[11]),
                "valid_for_seconds": int(cast(int, row[15])),
                "max_uses": int(cast(int, row[16])),
                "max_payload_bytes": int(cast(int, row[17])),
            }
            if str(row[1]) == "creator.scene.reply"
            else {
                "scope_kind": "codex_delegated_work",
                "workspace_scope": str(row[12]),
                "artifact_scope": str(row[13]),
                "network_access": bool(row[14]),
                "purpose": str(row[11]),
                "valid_for_seconds": int(cast(int, row[15])),
                "max_uses": int(cast(int, row[16])),
            }
        )
        current_request = {
            "request_ref": str(request_id),
            "request_version": int(cast(int, row[6])),
            "status": request_status,
            "requested_scope": requested_scope,
            "resolution_reason_class": None if row[8] is None else str(row[8]),
            "created_at": cast(datetime, row[28]).isoformat(),
        }
    effective_grant = None
    if row[18] is not None:
        effective_grant = {
            "grant_ref": str(row[18]),
            "status": str(row[19]),
            "valid_from": cast(datetime, row[20]).isoformat(),
            "valid_until": cast(datetime, row[21]).isoformat(),
            "max_uses": int(cast(int, row[22])),
            "consumed_uses": int(cast(int, row[23])),
            "remaining_uses": int(cast(int, row[22])) - int(cast(int, row[23])),
            "max_payload_bytes": (None if row[24] is None else int(cast(int, row[24]))),
            "workspace_scope": None if row[25] is None else str(row[25]),
            "artifact_scope": None if row[26] is None else str(row[26]),
            "network_access": None if row[27] is None else bool(row[27]),
        }
    value = {
        "schema_version": "armi.capability-state.v1",
        "capability_ref": str(row[0]),
        "capability_kind": str(row[1]),
        "operation": str(row[2]),
        "availability_status": str(row[3]),
        "authorization_status": request_status or "unauthorized",
        "current_request": current_request,
        "effective_grant": effective_grant,
    }
    payload = rfc8785.dumps(cast(Any, value))
    source_version = int(cast(int, row[4]))
    if request_id is not None:
        created_at = cast(datetime, row[28])
        epoch = datetime(1970, 1, 1, tzinfo=created_at.tzinfo)
        elapsed = created_at - epoch
        created_microseconds = (
            elapsed.days * 86_400 + elapsed.seconds
        ) * 1_000_000 + elapsed.microseconds
        source_version = created_microseconds + int(cast(int, row[6]))
        if source_version > _MAX_JSON_SAFE_INTEGER:
            raise ContextViolation("CTX-SOURCE-INVALID")
    return (
        cast(UUID, row[0]),
        source_version,
        payload,
        Digest.from_bytes(payload),
        request_status or "unauthorized",
    )


__all__ = ("CapabilityStatePayload", "load_capability_state_payloads")
