"""Frozen, explicitly wired S008 Runtime composition manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, cast

import rfc8785

from .runtime_errors import RuntimeViolation

COMPOSITION_SCHEMA_VERSION: Final = "armi.runtime-composition.v1"
_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_CREATOR_PACKAGE = "armi_runtime.interfaces.creator_web_resources"
_SEAMS: Final = (
    ("M0-SEAM-CONTEXT", ("M0-S023",)),
    ("M0-SEAM-MODEL", ("M0-S024",)),
    ("M0-SEAM-COGNITIVE-CANDIDATE", ("M0-S025", "M0-S026")),
    ("M0-SEAM-WORK-SELECTION", ("M0-S014", "M0-S023")),
    ("M0-SEAM-POLICY", ("M0-S027—M0-S029",)),
    ("M0-SEAM-WEB", ("M0-S032—M0-S034",)),
    ("M0-SEAM-CODEX", ("M0-S038", "M0-S039")),
    ("M0-SEAM-CREATOR-PROJECTION", ("M0-S019", "M0-S031")),
    (
        "M0-SEAM-CREATOR-UI",
        ("M0-S007", "M0-S022", "M0-S031", "M0-S043"),
    ),
)
_BLOCKERS: Final = (
    ("CREATOR_SESSION_NOT_IMPLEMENTED", "M0-S018"),
    ("RUNTIME_AUDIT_NOT_IMPLEMENTED", "M0-S013"),
    ("RUNTIME_AUTHORITY_NOT_IMPLEMENTED", "M0-S016"),
    ("RUNTIME_RECOVERY_NOT_IMPLEMENTED", "M0-S017"),
)
_CONFIG_FILES: Final = (
    "runtime.defaults.toml",
    "runtime.schema.json",
    "runtime-config-manifest.json",
)
_SCHEMA_FILES: Final = (
    "checks/invariants.sql",
    "manifests/schema-manifest.json",
    "migrations/0001_m0_baseline.sql",
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def build_composition_manifest(
    *,
    config_resources: dict[str, bytes],
    creator_manifest: bytes,
    creator_openapi: bytes,
    schema_resources: dict[str, bytes],
) -> dict[str, object]:
    """Return the only allowed S008 composition declaration."""

    if set(config_resources) != set(_CONFIG_FILES):
        raise RuntimeViolation(
            "CMP-RESOURCE-SET",
            "the packaged configuration resource set is incomplete",
        )
    if set(schema_resources) != set(_SCHEMA_FILES):
        raise RuntimeViolation(
            "CMP-RESOURCE-SET",
            "the packaged schema resource set is incomplete",
        )
    seams: list[dict[str, object]] = []
    for seam_id, activation_steps in _SEAMS:
        active = "armi.creator-static.v1" if seam_id == "M0-SEAM-CREATOR-UI" else None
        seams.append(
            {
                "seam_id": seam_id,
                "active_binding": active,
                "activation_steps": list(activation_steps),
                "runtime_discovery": False,
            }
        )
    return {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "entry_point": "armi",
        "runtime_discovery": False,
        "seams": seams,
        "readiness_blockers": [
            {"reason_code": code, "activation_step": step} for code, step in _BLOCKERS
        ],
        "resources": {
            **{
                f"config/{name}": _sha256(value)
                for name, value in sorted(config_resources.items())
            },
            "creator/manifest.json": _sha256(creator_manifest),
            "creator/openapi.json": _sha256(creator_openapi),
            **{
                f"schema/{name}": _sha256(value)
                for name, value in sorted(schema_resources.items())
            },
        },
        "runtime_business_contract": False,
    }


def canonical_manifest_bytes(value: dict[str, object]) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


@dataclass(frozen=True, slots=True)
class VerifiedComposition:
    schema_version: str
    active_bindings: tuple[tuple[str, str | None], ...]
    readiness_blockers: tuple[str, ...]
    digest: str


def verify_packaged_composition() -> VerifiedComposition:
    """Verify the package copies and the explicit seam set before listening."""

    resources = files(_RESOURCE_PACKAGE)
    schema = resources.joinpath("schema")
    creator = files(_CREATOR_PACKAGE)
    try:
        config_resources = {
            name: resources.joinpath(name).read_bytes() for name in _CONFIG_FILES
        }
        creator_manifest = creator.joinpath("manifest.json").read_bytes()
        creator_openapi = creator.joinpath("openapi.json").read_bytes()
        committed = resources.joinpath("runtime-composition.manifest.json").read_bytes()
        schema_resources = {
            name: schema.joinpath(name).read_bytes() for name in _SCHEMA_FILES
        }
    except OSError:
        raise RuntimeViolation(
            "CMP-RESOURCE-MISSING",
            "a required packaged Runtime resource is unavailable",
        ) from None
    expected = build_composition_manifest(
        config_resources=config_resources,
        creator_manifest=creator_manifest,
        creator_openapi=creator_openapi,
        schema_resources=schema_resources,
    )
    expected_bytes = canonical_manifest_bytes(expected)
    if committed != expected_bytes:
        raise RuntimeViolation(
            "CMP-MANIFEST-DRIFT",
            "the packaged Runtime composition manifest has drifted",
        )
    try:
        parsed = json.loads(committed)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise RuntimeViolation(
            "CMP-MANIFEST-FORMAT",
            "the packaged Runtime composition manifest is malformed",
        ) from None
    seams = parsed["seams"]
    blockers = parsed["readiness_blockers"]
    return VerifiedComposition(
        schema_version=COMPOSITION_SCHEMA_VERSION,
        active_bindings=tuple(
            (entry["seam_id"], entry["active_binding"]) for entry in seams
        ),
        readiness_blockers=tuple(entry["reason_code"] for entry in blockers),
        digest=_sha256(committed),
    )


__all__ = (
    "COMPOSITION_SCHEMA_VERSION",
    "VerifiedComposition",
    "build_composition_manifest",
    "canonical_manifest_bytes",
    "verify_packaged_composition",
)
