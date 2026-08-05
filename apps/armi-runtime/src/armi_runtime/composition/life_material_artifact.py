"""Canonical text envelope for immutable life-material body artifacts."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.contracts import Digest

LIFE_MATERIAL_CONTENT_VERSION = "armi.life-material-content.v1"


def build_life_material_artifact(body_bytes: bytes) -> bytes:
    if type(body_bytes) is not bytes or not body_bytes or b"\x00" in body_bytes:
        raise ValueError("life material body is invalid")
    body = body_bytes.decode("utf-8", errors="strict")
    if not body.strip():
        raise ValueError("life material body is invalid")
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": LIFE_MATERIAL_CONTENT_VERSION,
                "body": body,
            },
        )
    )


def parse_life_material_artifact(
    artifact_bytes: bytes,
    *,
    expected_body_digest: Digest,
) -> bytes:
    try:
        raw: object = json.loads(artifact_bytes)
        if type(raw) is not dict:
            raise ValueError
        value = cast(dict[str, object], raw)
        body_value = value.get("body")
        if (
            set(value) != {"schema_version", "body"}
            or value.get("schema_version") != LIFE_MATERIAL_CONTENT_VERSION
            or type(body_value) is not str
            or rfc8785.dumps(cast(Any, value)) != artifact_bytes
        ):
            raise ValueError
        body = body_value.encode("utf-8", errors="strict")
        if not body or b"\x00" in body or not body_value.strip():
            raise ValueError
        if Digest.from_bytes(body) != expected_body_digest:
            raise ValueError
        return body
    except TypeError, ValueError, UnicodeError, json.JSONDecodeError:
        raise ValueError("life material artifact is invalid") from None


__all__ = (
    "LIFE_MATERIAL_CONTENT_VERSION",
    "build_life_material_artifact",
    "parse_life_material_artifact",
)
