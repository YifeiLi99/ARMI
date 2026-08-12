"""Canonical candidate payload codec owned by the material module."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785

from .api import (
    MATERIAL_CANDIDATE_VERSION,
    CandidateLifeMaterialDraft,
    LifeMaterialKind,
    LifeMaterialRevisionKind,
    LifeMaterialStatus,
    MaterialViolation,
)


def encode(value: CandidateLifeMaterialDraft) -> bytes:
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": MATERIAL_CANDIDATE_VERSION,
                "proposal_ref": value.proposal_ref,
                "atomic_group_ref": value.atomic_group_ref,
                "basis_ordinals": list(value.basis_ordinals),
                "material_id": str(value.material_id),
                "owner_party_id": str(value.owner_party_id),
                "material_kind": value.material_kind.value,
                "current_revision_id": None
                if value.current_revision_id is None
                else str(value.current_revision_id),
                "expected_head_version": value.expected_head_version,
                "title": value.title,
                "body": None
                if value.body_bytes is None
                else value.body_bytes.decode("utf-8", errors="strict"),
                "metadata": dict(value.metadata),
                "material_status": value.material_status.value,
                "privacy_status": value.privacy_status,
                "revision_kind": value.revision_kind.value,
                "source_kind": value.source_kind,
            },
        )
    )


def decode(payload: bytes) -> CandidateLifeMaterialDraft:
    try:
        raw = json.loads(payload)
        if type(raw) is not dict or rfc8785.dumps(cast(Any, raw)) != payload:
            raise ValueError
        item = cast(dict[str, object], raw)
        if (
            set(item)
            != {
                "schema_version",
                "proposal_ref",
                "atomic_group_ref",
                "basis_ordinals",
                "material_id",
                "owner_party_id",
                "material_kind",
                "current_revision_id",
                "expected_head_version",
                "title",
                "body",
                "metadata",
                "material_status",
                "privacy_status",
                "revision_kind",
                "source_kind",
            }
            or item["schema_version"] != MATERIAL_CANDIDATE_VERSION
        ):
            raise ValueError
        ordinals = item["basis_ordinals"]
        metadata = item["metadata"]
        if type(ordinals) is not list or type(metadata) is not dict:
            raise ValueError
        current = item["current_revision_id"]
        body = item["body"]
        revision = LifeMaterialRevisionKind(str(item["revision_kind"]))
        return CandidateLifeMaterialDraft(
            str(item["proposal_ref"]),
            str(item["atomic_group_ref"]),
            tuple(cast(list[int], ordinals)),
            UUID(str(item["material_id"])),
            UUID(str(item["owner_party_id"])),
            LifeMaterialKind(str(item["material_kind"])),
            None if current is None else UUID(str(current)),
            int(cast(int, item["expected_head_version"])),
            str(item["title"]),
            None if body is None else str(body).encode("utf-8"),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in cast(dict[object, object], metadata).items()
                )
            ),
            LifeMaterialStatus(str(item["material_status"])),
            str(item["privacy_status"]),
            str(item["source_kind"]),
            None
            if revision
            in {LifeMaterialRevisionKind.CREATED, LifeMaterialRevisionKind.UPDATED}
            else revision,
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        MaterialViolation,
    ):
        raise MaterialViolation("MATERIAL-CODEC") from None


__all__ = ()
