"""Signed, query-bound cursor contract for Creator projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.contracts import OpaqueCursor

_CONTRACT = "armi.projection-cursor.v1"
_FIELDS = frozenset(
    {
        "contract",
        "environment_id",
        "creator_party_id",
        "projection_version",
        "resource_kind",
        "resource_ref",
        "page_limit",
        "query",
        "snapshot_ceiling",
        "boundary",
    }
)


class ProjectionCursorInvalid(ValueError):
    """The cursor is not a canonical, authentic v1 cursor."""


class ProjectionCursorStale(ValueError):
    """The cursor is authentic but belongs to another query scope."""


@dataclass(frozen=True, slots=True)
class ProjectionCursorPage:
    snapshot_ceiling: dict[str, object]
    boundary: dict[str, object]


class ProjectionCursorCodec:
    __slots__ = ("_creator_party_id", "_environment_id", "_key")

    def __init__(
        self, key: bytes, environment_id: UUID, creator_party_id: UUID
    ) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("projection cursor key must contain at least 32 bytes")
        self._key = key
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id

    def encode(
        self,
        *,
        projection_version: str,
        resource_kind: str,
        resource_ref: str | None,
        page_limit: int,
        query: dict[str, object],
        snapshot_ceiling: dict[str, object],
        boundary: dict[str, object],
    ) -> OpaqueCursor:
        payload = self._scope(
            projection_version=projection_version,
            resource_kind=resource_kind,
            resource_ref=resource_ref,
            page_limit=page_limit,
            query=query,
        )
        payload["snapshot_ceiling"] = snapshot_ceiling
        payload["boundary"] = boundary
        raw = rfc8785.dumps(cast(Any, payload))
        encoded = _b64encode(raw)
        signature = _b64encode(
            hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return OpaqueCursor(f"v1.{encoded}.{signature}")

    def decode(
        self,
        cursor: OpaqueCursor,
        *,
        projection_version: str,
        resource_kind: str,
        resource_ref: str | None,
        page_limit: int,
        query: dict[str, object],
    ) -> ProjectionCursorPage:
        try:
            prefix, encoded, signature = cursor.value.split(".", 2)
            if prefix != "v1" or not hmac.compare_digest(
                _b64decode(signature),
                hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest(),
            ):
                raise ProjectionCursorInvalid
            raw = _b64decode(encoded)
            decoded = json.loads(raw)
            if type(decoded) is not dict:
                raise ProjectionCursorInvalid
            value = cast(dict[str, object], decoded)
            if (
                frozenset(value) != _FIELDS
                or rfc8785.dumps(cast(Any, value)) != raw
                or type(value.get("snapshot_ceiling")) is not dict
                or type(value.get("boundary")) is not dict
            ):
                raise ProjectionCursorInvalid
        except ProjectionCursorInvalid:
            raise
        except UnicodeError, ValueError, TypeError, json.JSONDecodeError:
            raise ProjectionCursorInvalid from None
        expected = self._scope(
            projection_version=projection_version,
            resource_kind=resource_kind,
            resource_ref=resource_ref,
            page_limit=page_limit,
            query=query,
        )
        if any(
            value.get(name) != expected_value
            for name, expected_value in expected.items()
        ):
            raise ProjectionCursorStale
        return ProjectionCursorPage(
            cast(dict[str, object], value["snapshot_ceiling"]),
            cast(dict[str, object], value["boundary"]),
        )

    def _scope(
        self,
        *,
        projection_version: str,
        resource_kind: str,
        resource_ref: str | None,
        page_limit: int,
        query: dict[str, object],
    ) -> dict[str, object]:
        return {
            "contract": _CONTRACT,
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            "projection_version": projection_version,
            "resource_kind": resource_kind,
            "resource_ref": resource_ref,
            "page_limit": page_limit,
            "query": query,
        }


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    result = base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )
    if _b64encode(result) != value:
        raise ProjectionCursorInvalid
    return result


__all__ = (
    "ProjectionCursorCodec",
    "ProjectionCursorInvalid",
    "ProjectionCursorPage",
    "ProjectionCursorStale",
)
