"""Strict loading of the private one-time birth manifest."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import (
    BirthManifest,
    BirthViolation,
    PersonalityAnchor,
)
from armi_kernel.contracts import Digest

from .configuration.paths import has_reparse_point

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_CREATOR_PACKAGE = "armi_runtime.interfaces.creator_web_resources"
_MAXIMUM_BYTES = 64 * 1024
_ROOT_FIELDS = {
    "schema_version",
    "environment_id",
    "birth_request_id",
    "creator_party_id",
    "idempotency_key",
    "personality_anchor",
    "personality_anchor_digest",
    "expected_package",
}
_ANCHOR_FIELDS = {"schema_version", "voice_style", "traits"}
_PACKAGE_FIELDS = {
    "composition_digest",
    "birth_contract_digest",
    "schema_manifest_digest",
    "creator_asset_manifest_digest",
}
_FORBIDDEN_FIELDS = {
    "experiences",
    "goals",
    "interests",
    "name",
    "preferences",
    "relationships",
    "self_description",
    "values",
}


def _digest(value: bytes) -> Digest:
    return Digest.from_bytes(value)


def _canonical(value: object) -> bytes:
    try:
        return rfc8785.dumps(cast(Any, value))
    except (TypeError, ValueError) as error:
        raise BirthViolation("BIRTH-MANIFEST") from error


def packaged_birth_digests() -> dict[str, Digest]:
    resources = files(_RESOURCE_PACKAGE)
    creator = files(_CREATOR_PACKAGE)
    try:
        return {
            "composition_digest": _digest(
                resources.joinpath("runtime-composition.manifest.json").read_bytes()
            ),
            "birth_contract_digest": _digest(
                resources.joinpath("birth-contract.manifest.json").read_bytes()
            ),
            "schema_manifest_digest": _digest(
                resources.joinpath("schema/manifests/schema-manifest.json").read_bytes()
            ),
            "creator_asset_manifest_digest": _digest(
                creator.joinpath("manifest.json").read_bytes()
            ),
        }
    except OSError:
        raise BirthViolation("BIRTH-PACKAGE-DRIFT") from None


def load_birth_manifest(
    environment_root: Path,
    *,
    expected_environment_id: UUID,
) -> BirthManifest:
    path = environment_root / "bootstrap" / "birth-manifest.json"
    try:
        resolved = path.resolve(strict=True)
        bootstrap_root = (environment_root / "bootstrap").resolve(strict=True)
    except OSError:
        raise BirthViolation("BIRTH-MANIFEST-MISSING") from None
    if (
        resolved.parent != bootstrap_root
        or not resolved.is_file()
        or has_reparse_point(resolved, root=environment_root)
    ):
        raise BirthViolation("BIRTH-MANIFEST-PATH")
    try:
        raw = resolved.read_bytes()
    except OSError:
        raise BirthViolation("BIRTH-MANIFEST-MISSING") from None
    if not raw or len(raw) > _MAXIMUM_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise BirthViolation("BIRTH-MANIFEST-SIZE")
    try:
        loaded = cast(object, json.loads(raw))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise BirthViolation("BIRTH-MANIFEST") from None
    if type(loaded) is not dict:
        raise BirthViolation("BIRTH-MANIFEST")
    value = cast(dict[str, object], loaded)
    if _contains_forbidden_field(value):
        raise BirthViolation("BIRTH-FORBIDDEN-CONTENT")
    if set(value) != _ROOT_FIELDS:
        raise BirthViolation("BIRTH-MANIFEST")
    anchor_value = value["personality_anchor"]
    package_value = value["expected_package"]
    if type(anchor_value) is not dict or type(package_value) is not dict:
        raise BirthViolation("BIRTH-MANIFEST")
    anchor_fields = cast(dict[str, object], anchor_value)
    package_fields = cast(dict[str, object], package_value)
    if set(anchor_fields) != _ANCHOR_FIELDS or set(package_fields) != _PACKAGE_FIELDS:
        raise BirthViolation("BIRTH-MANIFEST")
    traits_value = anchor_fields["traits"]
    if type(traits_value) is not list or any(
        type(item) is not str for item in cast(list[object], traits_value)
    ):
        raise BirthViolation("BIRTH-MANIFEST")
    traits = tuple(cast(list[str], traits_value))
    try:
        anchor = PersonalityAnchor(
            schema_version=cast(str, anchor_fields["schema_version"]),
            voice_style=cast(str, anchor_fields["voice_style"]),
            traits=traits,
        )
        declared_anchor_digest = Digest(cast(str, value["personality_anchor_digest"]))
        actual_anchor_digest = _digest(_canonical(anchor_fields))
        expected_package = {
            name: Digest(cast(str, package_fields[name])) for name in _PACKAGE_FIELDS
        }
        environment_id = UUID(cast(str, value["environment_id"]))
        manifest = BirthManifest(
            schema_version=cast(str, value["schema_version"]),
            environment_id=environment_id,
            birth_request_id=UUID(cast(str, value["birth_request_id"])),
            creator_party_id=UUID(cast(str, value["creator_party_id"])),
            idempotency_key=cast(str, value["idempotency_key"]),
            personality_anchor=anchor,
            personality_anchor_digest=declared_anchor_digest,
            request_digest=_digest(_canonical(value)),
            **expected_package,
        )
    except BirthViolation:
        raise
    except TypeError, ValueError:
        raise BirthViolation("BIRTH-MANIFEST") from None
    if environment_id != expected_environment_id:
        raise BirthViolation("BIRTH-ENVIRONMENT")
    if declared_anchor_digest != actual_anchor_digest:
        raise BirthViolation("BIRTH-ANCHOR-DIGEST")
    if expected_package != packaged_birth_digests():
        raise BirthViolation("BIRTH-PACKAGE-DRIFT")
    return manifest


def _contains_forbidden_field(value: object) -> bool:
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        for key, nested in mapping.items():
            if key in _FORBIDDEN_FIELDS or _contains_forbidden_field(nested):
                return True
    elif type(value) is list:
        return any(
            _contains_forbidden_field(item) for item in cast(list[object], value)
        )
    return False


__all__ = ("load_birth_manifest", "packaged_birth_digests")
