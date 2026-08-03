"""Frozen, explicitly wired Runtime composition manifest."""

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
_SEAMS: Final = (
    ("M0-SEAM-CONTEXT", ("M0-S023",)),
    ("M0-SEAM-MODEL", ("M0-S024",)),
    ("M0-SEAM-COGNITIVE-CANDIDATE", ("M0-S025", "M0-S026")),
    ("M0-SEAM-WORK-SELECTION", ("M0-S023",)),
    ("M0-SEAM-POLICY", ("M0-S027—M0-S029",)),
    ("M0-SEAM-EFFECT", ("M0-S030",)),
    ("M0-SEAM-WEB", ("M0-S032—M0-S034",)),
    ("M0-SEAM-CODEX", ("M0-S038", "M0-S039")),
    (
        "M0-SEAM-CREATOR-PROJECTION",
        ("M0-S019", "M0-S020", "M0-S021", "M0-S030", "M0-S031"),
    ),
    (
        "M0-SEAM-CREATOR-UI",
        ("M0-S007", "M0-S020", "M0-S022", "M0-S031", "M0-S043"),
    ),
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def build_composition_manifest() -> dict[str, object]:
    """Return the explicit Runtime binding declaration.

    Resource integrity belongs to the component that actually consumes each
    resource.  Composition records only wiring; it intentionally does not
    duplicate hashes for configuration, schema, UI, or policy artifacts.
    """
    seams: list[dict[str, object]] = []
    for seam_id, activation_steps in _SEAMS:
        active = (
            "armi.creator-workbench.v1"
            if seam_id == "M0-SEAM-CREATOR-UI"
            else "armi.creator-projection-workbench.v1"
            if seam_id == "M0-SEAM-CREATOR-PROJECTION"
            else "armi.context-compiler.deterministic-v1"
            if seam_id == "M0-SEAM-CONTEXT"
            else "armi.model-adapter.volcengine-ark-responses-v1"
            if seam_id == "M0-SEAM-MODEL"
            else "armi.candidate-validator.deterministic-v1"
            if seam_id == "M0-SEAM-COGNITIVE-CANDIDATE"
            else "armi.opportunity-selector.creator-fifo-v1"
            if seam_id == "M0-SEAM-WORK-SELECTION"
            else "armi.policy-engine.deterministic-v1"
            if seam_id == "M0-SEAM-POLICY"
            else "armi.creator-response-adapter.postgresql-inbox-v1"
            if seam_id == "M0-SEAM-EFFECT"
            else "armi.codex-runner.openai-python-sdk-v1"
            if seam_id == "M0-SEAM-CODEX"
            else None
        )
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
        "readiness_blockers": [],
        "runtime_business_contract": True,
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
    """Verify the explicit seam set before listening."""

    resources = files(_RESOURCE_PACKAGE)
    try:
        committed = resources.joinpath("runtime-composition.manifest.json").read_bytes()
    except OSError:
        raise RuntimeViolation(
            "CMP-RESOURCE-MISSING",
            "the packaged Runtime composition is unavailable",
        ) from None
    try:
        parsed = json.loads(committed)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise RuntimeViolation(
            "CMP-MANIFEST-FORMAT",
            "the packaged Runtime composition manifest is malformed",
        ) from None
    expected = build_composition_manifest()
    if parsed != expected or committed != canonical_manifest_bytes(expected):
        raise RuntimeViolation(
            "CMP-MANIFEST-DRIFT",
            "the packaged Runtime composition declaration has drifted",
        )
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
