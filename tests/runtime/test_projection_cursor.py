from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid7

import pytest
import rfc8785
from armi_kernel.contracts import OpaqueCursor
from armi_runtime_foundation import (
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorStale,
)

_KEY = b"projection-cursor-test-key-32-bytes!!"
_OTHER_RESOURCE_ID = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7"


def _encode(codec: ProjectionCursorCodec) -> OpaqueCursor:
    return codec.encode(
        projection_version="creator-memory.v2",
        resource_kind="memory-current",
        resource_ref=None,
        page_limit=50,
        query={"query_text": "\uff21"},
        snapshot_ceiling={"at": "2026-08-28T01:02:03.000000Z"},
        boundary={"before_id": str(uuid7())},
    )


def _decode(codec: ProjectionCursorCodec, cursor: OpaqueCursor) -> None:
    codec.decode(
        cursor,
        projection_version="creator-memory.v2",
        resource_kind="memory-current",
        resource_ref=None,
        page_limit=50,
        query={"query_text": "\uff21"},
    )


def _resign(
    cursor: OpaqueCursor, mutate: Callable[[dict[str, object]], object]
) -> OpaqueCursor:
    _prefix, encoded, _signature = cursor.value.split(".")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    payload = cast(dict[str, object], json.loads(raw))
    mutate(payload)
    canonical = rfc8785.dumps(cast(Any, payload))
    next_encoded = base64.urlsafe_b64encode(canonical).rstrip(b"=").decode("ascii")
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(_KEY, next_encoded.encode("ascii"), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    return OpaqueCursor(f"v1.{next_encoded}.{signature}")


def test_cursor_rejects_signature_and_authenticated_field_shape_changes() -> None:
    codec = ProjectionCursorCodec(_KEY, uuid7(), uuid7())
    cursor = _encode(codec)
    with pytest.raises(ProjectionCursorInvalid):
        _decode(codec, OpaqueCursor(cursor.value[:-1] + "A"))
    with pytest.raises(ProjectionCursorInvalid):
        _decode(codec, _resign(cursor, lambda value: value.pop("boundary")))
    with pytest.raises(ProjectionCursorInvalid):
        _decode(codec, _resign(cursor, lambda value: value.update({"extra": 1})))


@pytest.mark.parametrize(
    ("projection", "resource", "resource_ref", "limit", "query"),
    (
        ("creator-memory.v3", "memory-current", None, 50, {"query_text": "\uff21"}),
        ("creator-memory.v2", "memory-timeline", None, 50, {"query_text": "\uff21"}),
        (
            "creator-memory.v2",
            "memory-current",
            _OTHER_RESOURCE_ID,
            50,
            {"query_text": "\uff21"},
        ),
        ("creator-memory.v2", "memory-current", None, 51, {"query_text": "\uff21"}),
        ("creator-memory.v2", "memory-current", None, 50, {"query_text": "A"}),
        ("creator-memory.v2", "memory-current", None, 50, {"query_text": "\uff41"}),
        ("creator-memory.v2", "memory-current", None, 50, {"query_text": None}),
    ),
)
def test_cursor_rejects_every_scope_change_as_stale(
    projection: str,
    resource: str,
    resource_ref: str | None,
    limit: int,
    query: dict[str, object],
) -> None:
    codec = ProjectionCursorCodec(_KEY, uuid7(), uuid7())
    cursor = _encode(codec)
    with pytest.raises(ProjectionCursorStale):
        codec.decode(
            cursor,
            projection_version=projection,
            resource_kind=resource,
            resource_ref=resource_ref,
            page_limit=limit,
            query=query,
        )


def test_cursor_is_bound_to_environment_and_creator() -> None:
    environment_id = uuid7()
    creator_id = uuid7()
    cursor = _encode(ProjectionCursorCodec(_KEY, environment_id, creator_id))
    with pytest.raises(ProjectionCursorStale):
        _decode(ProjectionCursorCodec(_KEY, uuid7(), creator_id), cursor)
    with pytest.raises(ProjectionCursorStale):
        _decode(ProjectionCursorCodec(_KEY, environment_id, uuid7()), cursor)
