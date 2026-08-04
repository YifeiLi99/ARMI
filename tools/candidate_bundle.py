"""Build and verify the immutable M0 candidate bundle identity."""

from __future__ import annotations

import configparser
import hashlib
import io
import json
import re
import stat
from collections.abc import Sequence
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, cast
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import rfc8785

try:
    from tools.check_repository_hygiene import PATTERNS, TEXT_SUFFIXES
except ModuleNotFoundError:  # Direct execution from the tools directory.
    from check_repository_hygiene import PATTERNS, TEXT_SUFFIXES

IDENTITY_SCHEMA = "armi.bundle-identity.v1"
IDENTITY_PATH = "bundle-identity.json"
CREATOR_MANIFEST = "armi_runtime/interfaces/creator_web_resources/manifest.json"
CREATOR_PREFIX = "armi_runtime/interfaces/creator_web_resources/"
SCHEMA_MANIFEST = (
    "armi_runtime/composition/runtime_resources/schema/manifests/schema-manifest.json"
)
SCHEMA_PREFIX = "armi_runtime/composition/runtime_resources/"
COMPOSITION_MANIFEST = (
    "armi_runtime/composition/runtime_resources/runtime-composition.manifest.json"
)
EXPECTED_DISTRIBUTIONS = ("armi-admin", "armi-kernel", "armi-runtime")
EXPECTED_LOCK_ROLES = (
    "creator-package-lock",
    "runtime-requirements",
    "toolchain-package-lock",
    "uv-lock",
)
EXPECTED_ENTRY_POINTS = {
    "armi-admin": {"armi-admin-mcp": "armi_admin.mcp.entrypoint:main"},
    "armi-kernel": {},
    "armi-runtime": {
        "armi": "armi_runtime.cli:main",
        "armi-codex-runner": "armi_runtime.codex_runner_cli:main",
    },
}
FORBIDDEN_WHEEL_PARTS = (
    "/tests/",
    ".map",
    "node_modules",
    "armi-creator-web/src",
)
FORBIDDEN_ARCHIVE_SUFFIXES = (".bat", ".cmd", ".com", ".dll", ".exe", ".msi")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")


class CandidateError(ValueError):
    """A stable candidate build or verification failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_bytes(value: object) -> bytes:
    return rfc8785.dumps(cast(Any, value))


def _json_object(raw: bytes, code: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateError(code, "invalid UTF-8 JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandidateError(code, "expected a JSON object")
    return cast(dict[str, object], value)


def _require_exact_keys(
    value: dict[str, object], expected: set[str], code: str
) -> None:
    if set(value) != expected:
        raise CandidateError(code, "object fields do not match the contract")


def _require_string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateError(code, "expected a non-empty string")
    return value


def _require_integer(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CandidateError(code, "expected a non-negative integer")
    return value


def _require_digest(value: object, code: str) -> str:
    digest = _require_string(value, code)
    if _SHA256.fullmatch(digest) is None:
        raise CandidateError(code, "expected a sha256 digest")
    return digest


def _safe_member(info: ZipInfo, code: str) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CandidateError(code, f"unsafe archive member: {name!r}")
    mode = info.external_attr >> 16
    if name.endswith("/"):
        if info.file_size or stat.S_IFMT(mode) not in {0, stat.S_IFDIR}:
            raise CandidateError(code, f"invalid directory member: {name}")
        return
    if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
        raise CandidateError(code, f"non-regular archive member: {name}")


def _validated_infos(archive: ZipFile, code: str) -> dict[str, ZipInfo]:
    infos: dict[str, ZipInfo] = {}
    for info in archive.infolist():
        _safe_member(info, code)
        if info.filename in infos:
            raise CandidateError(code, f"duplicate archive member: {info.filename}")
        infos[info.filename] = info
    return infos


def _artifact(path: str, data: bytes, **extra: object) -> dict[str, object]:
    return {
        **extra,
        "path": path,
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def _wheel_metadata(archive: ZipFile) -> tuple[str, str]:
    metadata_names = [
        name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
    ]
    if len(metadata_names) != 1:
        raise CandidateError("BND-WHEEL-METADATA", "wheel METADATA is ambiguous")
    metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        raise CandidateError("BND-WHEEL-METADATA", "wheel identity is incomplete")
    return name.lower().replace("_", "-"), version


def _entry_points(archive: ZipFile) -> dict[str, str]:
    names = [
        name
        for name in archive.namelist()
        if name.endswith(".dist-info/entry_points.txt")
    ]
    if not names:
        return {}
    if len(names) != 1:
        raise CandidateError("BND-WHEEL-ENTRY", "entry point file is ambiguous")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(archive.read(names[0]).decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise CandidateError("BND-WHEEL-ENTRY", "invalid entry point file") from error
    unexpected = set(parser.sections()) - {"console_scripts"}
    if unexpected:
        raise CandidateError("BND-WHEEL-ENTRY", "unexpected entry point group")
    if not parser.has_section("console_scripts"):
        return {}
    return dict(parser.items("console_scripts"))


def _verify_creator(archive: ZipFile) -> tuple[str, dict[str, object]]:
    names = set(archive.namelist())
    if CREATOR_MANIFEST not in names:
        raise CandidateError("BND-CREATOR-MISSING", "Creator manifest is absent")
    raw = archive.read(CREATOR_MANIFEST)
    manifest = _json_object(raw, "BND-CREATOR-MANIFEST")
    if manifest.get("schema_version") != "armi.creator-static.v1":
        raise CandidateError("BND-CREATOR-MANIFEST", "Creator schema drifted")
    openapi = manifest.get("openapi")
    if not isinstance(openapi, dict):
        raise CandidateError("BND-CREATOR-MANIFEST", "OpenAPI reference is absent")
    openapi_path = CREATOR_PREFIX + _require_string(
        openapi.get("path"), "BND-CREATOR-MANIFEST"
    )
    if openapi_path not in names or sha256_bytes(archive.read(openapi_path))[7:] != (
        _require_string(openapi.get("sha256"), "BND-CREATOR-MANIFEST")
    ):
        raise CandidateError("BND-CREATOR-DIGEST", "OpenAPI digest drifted")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise CandidateError("BND-CREATOR-MANIFEST", "Creator assets are absent")
    declared: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise CandidateError("BND-CREATOR-MANIFEST", "invalid asset entry")
        asset = cast(dict[str, object], item)
        relative = _require_string(asset.get("path"), "BND-CREATOR-MANIFEST")
        path = CREATOR_PREFIX + relative
        declared.add(path)
        if path not in names:
            raise CandidateError("BND-CREATOR-MISSING", f"asset is absent: {relative}")
        data = archive.read(path)
        if len(data) != _require_integer(asset.get("size"), "BND-CREATOR-MANIFEST"):
            raise CandidateError(
                "BND-CREATOR-DIGEST", f"asset size drifted: {relative}"
            )
        expected = _require_string(asset.get("sha256"), "BND-CREATOR-MANIFEST")
        if sha256_bytes(data)[7:] != expected:
            raise CandidateError(
                "BND-CREATOR-DIGEST", f"asset digest drifted: {relative}"
            )
    packaged_static = {
        name
        for name in names
        if name.startswith(f"{CREATOR_PREFIX}static/") and not name.endswith("/")
    }
    if packaged_static != declared:
        raise CandidateError("BND-CREATOR-DIRTY", "undeclared Creator asset present")
    return sha256_bytes(raw), manifest


def verify_schema_archive(archive: ZipFile) -> tuple[str, int, str]:
    names = set(archive.namelist())
    if SCHEMA_MANIFEST not in names:
        raise CandidateError("DB-SCHEMA-MISSING", "schema manifest is absent")
    raw = archive.read(SCHEMA_MANIFEST)
    manifest = _json_object(raw, "DB-MANIFEST-DRIFT")
    if manifest.get("schema_version") != "armi.schema-manifest.v1":
        raise CandidateError("DB-MANIFEST-DRIFT", "schema contract drifted")
    migrations = manifest.get("migrations")
    target = manifest.get("target")
    if not isinstance(migrations, list) or not isinstance(target, dict):
        raise CandidateError("DB-MANIFEST-DRIFT", "schema target is incomplete")
    target_version = _require_integer(target.get("version"), "DB-MANIFEST-DRIFT")
    if target_version != len(migrations) or target_version == 0:
        raise CandidateError("DB-SCHEMA-GAP", "schema target and migrations differ")
    migration_set = bytearray()
    declared_sql: set[str] = set()
    for expected_version, item in enumerate(migrations, start=1):
        if not isinstance(item, dict):
            raise CandidateError("DB-MANIFEST-DRIFT", "invalid migration entry")
        migration = cast(dict[str, object], item)
        version = _require_integer(migration.get("version"), "DB-MANIFEST-DRIFT")
        relative = _require_string(migration.get("path"), "DB-MANIFEST-DRIFT")
        digest = _require_digest(migration.get("sha256"), "DB-MANIFEST-DRIFT")
        if version != expected_version or not relative.startswith("schema/migrations/"):
            raise CandidateError("DB-SCHEMA-GAP", "migration order drifted")
        path = SCHEMA_PREFIX + relative
        declared_sql.add(path)
        if path not in names or sha256_bytes(archive.read(path)) != digest:
            raise CandidateError("DB-MANIFEST-DRIFT", f"migration drifted: {relative}")
        migration_set.extend(f"{version}\t{relative}\t{digest}\n".encode())
    expected_set = _require_digest(
        manifest.get("migration_set_sha256"), "DB-MANIFEST-DRIFT"
    )
    if sha256_bytes(bytes(migration_set)) != expected_set:
        raise CandidateError("DB-MANIFEST-DRIFT", "migration set digest drifted")
    for reference_key in ("invariants", "database_role_manifest"):
        reference = manifest.get(reference_key)
        if not isinstance(reference, dict):
            raise CandidateError("DB-MANIFEST-DRIFT", f"{reference_key} is absent")
        relative = _require_string(reference.get("path"), "DB-MANIFEST-DRIFT")
        digest = _require_digest(reference.get("sha256"), "DB-MANIFEST-DRIFT")
        path = SCHEMA_PREFIX + relative
        if path not in names or sha256_bytes(archive.read(path)) != digest:
            raise CandidateError("DB-MANIFEST-DRIFT", f"resource drifted: {relative}")
    packaged_sql = {
        name
        for name in names
        if name.startswith(f"{SCHEMA_PREFIX}schema/migrations/")
        and name.endswith(".sql")
    }
    if packaged_sql != declared_sql:
        raise CandidateError("DB-SCHEMA-DIRTY", "undeclared migration is present")
    forbidden = [
        name
        for name in names
        if name.startswith("schema/")
        or (name.endswith(".sql") and not name.startswith(SCHEMA_PREFIX))
    ]
    if forbidden:
        raise CandidateError("DB-SCHEMA-DIRTY", "schema escaped its package root")
    return sha256_bytes(raw), target_version, expected_set


def _verify_composition(archive: ZipFile) -> tuple[str, str]:
    names = set(archive.namelist())
    if COMPOSITION_MANIFEST not in names:
        raise CandidateError("BND-BINDING-MISSING", "composition manifest is absent")
    raw = archive.read(COMPOSITION_MANIFEST)
    manifest = _json_object(raw, "BND-BINDING-MANIFEST")
    if manifest.get("schema_version") != "armi.runtime-composition.v1":
        raise CandidateError("BND-BINDING-MANIFEST", "composition schema drifted")
    seams = manifest.get("seams")
    if not isinstance(seams, list) or not seams:
        raise CandidateError("BND-BINDING-MANIFEST", "composition seams are absent")
    projection: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in seams:
        if not isinstance(item, dict):
            raise CandidateError("BND-BINDING-MANIFEST", "invalid seam")
        seam = cast(dict[str, object], item)
        seam_id = _require_string(seam.get("seam_id"), "BND-BINDING-MANIFEST")
        binding = seam.get("active_binding")
        if binding is not None and not isinstance(binding, str):
            raise CandidateError("BND-BINDING-MANIFEST", "invalid Active binding")
        if seam_id in seen:
            raise CandidateError("BND-BINDING-MANIFEST", "duplicate seam")
        seen.add(seam_id)
        projection.append({"seam_id": seam_id, "active_binding": binding})
    projection.sort(key=lambda item: cast(str, item["seam_id"]))
    web = next((item for item in projection if item["seam_id"] == "M0-SEAM-WEB"), None)
    if web is None or web["active_binding"] is not None:
        raise CandidateError("BND-BINDING-WEB", "M0-S044 Web binding must remain null")
    return sha256_bytes(raw), sha256_bytes(canonical_bytes(projection))


def verify_runtime_wheel(data: bytes) -> dict[str, object]:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            _validated_infos(archive, "BND-WHEEL-PATH")
            name, version = _wheel_metadata(archive)
            if name != "armi-runtime":
                raise CandidateError("BND-WHEEL-METADATA", "expected Runtime wheel")
            if _entry_points(archive) != EXPECTED_ENTRY_POINTS[name]:
                raise CandidateError(
                    "BND-WHEEL-ENTRY", "Runtime console scripts drifted"
                )
            forbidden = sorted(
                member
                for member in archive.namelist()
                if any(part in member for part in FORBIDDEN_WHEEL_PARTS)
            )
            if forbidden:
                raise CandidateError("BND-WHEEL-FORBIDDEN", forbidden[0])
            creator_digest, _ = _verify_creator(archive)
            schema_digest, target_version, migration_set = verify_schema_archive(
                archive
            )
            composition_digest, projection_digest = _verify_composition(archive)
    except BadZipFile as error:
        raise CandidateError("BND-WHEEL-ZIP", "Runtime wheel is invalid") from error
    return {
        "distribution": name,
        "version": version,
        "creator_manifest_sha256": creator_digest,
        "schema_manifest_sha256": schema_digest,
        "target_schema_version": target_version,
        "migration_set_sha256": migration_set,
        "composition_manifest_sha256": composition_digest,
        "active_binding_sha256": projection_digest,
    }


def inspect_wheel(data: bytes) -> tuple[str, str]:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            _validated_infos(archive, "BND-WHEEL-PATH")
            name, version = _wheel_metadata(archive)
            if name not in EXPECTED_ENTRY_POINTS:
                raise CandidateError("BND-WHEEL-SET", f"unexpected wheel: {name}")
            if _entry_points(archive) != EXPECTED_ENTRY_POINTS[name]:
                raise CandidateError("BND-WHEEL-ENTRY", f"entry points drifted: {name}")
            forbidden = sorted(
                member
                for member in archive.namelist()
                if any(part in member for part in FORBIDDEN_WHEEL_PARTS)
            )
            if forbidden:
                raise CandidateError("BND-WHEEL-FORBIDDEN", forbidden[0])
    except BadZipFile as error:
        raise CandidateError("BND-WHEEL-ZIP", "wheel is invalid") from error
    return name, version


def _scan_unsafe_text(path: str, data: bytes) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in TEXT_SUFFIXES and PurePosixPath(path).name not in {
        "METADATA",
        "WHEEL",
        "entry_points.txt",
    }:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    for code, pattern, _ in PATTERNS:
        if pattern.search(text):
            raise CandidateError(code, f"unsafe text in {path}")


def _scan_candidate_payload(path: str, data: bytes) -> None:
    _scan_unsafe_text(path, data)
    if path.lower().endswith(FORBIDDEN_ARCHIVE_SUFFIXES):
        raise CandidateError("BND-EXECUTABLE", f"executable is forbidden: {path}")
    if path.endswith(".whl"):
        with ZipFile(io.BytesIO(data)) as wheel:
            for info in wheel.infolist():
                _scan_unsafe_text(f"{path}!/{info.filename}", wheel.read(info))


def build_identity(
    source_revision: str,
    wheel_files: Sequence[tuple[str, bytes]],
    lock_files: Sequence[tuple[str, str, bytes, str | None]],
) -> dict[str, object]:
    if _REVISION.fullmatch(source_revision) is None:
        raise CandidateError("BND-SOURCE-REVISION", "invalid source revision")
    wheels: list[dict[str, object]] = []
    runtime: dict[str, object] | None = None
    versions: set[str] = set()
    seen: set[str] = set()
    for path, data in sorted(wheel_files):
        name, version = inspect_wheel(data)
        if name in seen:
            raise CandidateError("BND-WHEEL-SET", f"duplicate wheel: {name}")
        seen.add(name)
        versions.add(version)
        wheels.append(_artifact(path, data, distribution=name, version=version))
        if name == "armi-runtime":
            runtime = verify_runtime_wheel(data)
    if tuple(sorted(seen)) != EXPECTED_DISTRIBUTIONS or len(versions) != 1:
        raise CandidateError("BND-WHEEL-SET", "expected three version-aligned wheels")
    if runtime is None:
        raise CandidateError("BND-WHEEL-SET", "Runtime wheel is absent")
    locks = [
        _artifact(path, data, role=role, derived_from=derived_from)
        for role, path, data, derived_from in sorted(lock_files)
    ]
    if tuple(sorted(cast(str, item["role"]) for item in locks)) != (
        EXPECTED_LOCK_ROLES
    ):
        raise CandidateError("BND-LOCK-SET", "lock set is incomplete")
    runtime_wheel = next(
        cast(str, item["path"])
        for item in wheels
        if item["distribution"] == "armi-runtime"
    )
    body: dict[str, object] = {
        "schema_version": IDENTITY_SCHEMA,
        "application_version": versions.pop(),
        "source_revision": source_revision,
        "wheels": wheels,
        "locks": locks,
        "creator_static": {
            "wheel": runtime_wheel,
            "manifest_path": CREATOR_MANIFEST,
            "manifest_sha256": runtime["creator_manifest_sha256"],
        },
        "database_schema": {
            "wheel": runtime_wheel,
            "manifest_path": SCHEMA_MANIFEST,
            "manifest_sha256": runtime["schema_manifest_sha256"],
            "target_version": runtime["target_schema_version"],
            "migration_set_sha256": runtime["migration_set_sha256"],
        },
        "active_bindings": {
            "wheel": runtime_wheel,
            "manifest_path": COMPOSITION_MANIFEST,
            "manifest_sha256": runtime["composition_manifest_sha256"],
            "projection_sha256": runtime["active_binding_sha256"],
        },
    }
    return {**body, "bundle_id": sha256_bytes(canonical_bytes(body))}


def write_deterministic_bundle(
    output: Path, identity: dict[str, object], payloads: dict[str, bytes]
) -> None:
    members = {IDENTITY_PATH: canonical_bytes(identity), **payloads}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        for name in sorted(members):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])


def _validate_identity(identity: dict[str, object]) -> None:
    _require_exact_keys(
        identity,
        {
            "schema_version",
            "bundle_id",
            "application_version",
            "source_revision",
            "wheels",
            "locks",
            "creator_static",
            "database_schema",
            "active_bindings",
        },
        "BND-IDENTITY-FIELDS",
    )
    if identity.get("schema_version") != IDENTITY_SCHEMA:
        raise CandidateError("BND-IDENTITY-SCHEMA", "identity schema drifted")
    revision = _require_string(identity.get("source_revision"), "BND-IDENTITY-SOURCE")
    if _REVISION.fullmatch(revision) is None:
        raise CandidateError("BND-IDENTITY-SOURCE", "invalid source revision")
    bundle_id = _require_digest(identity.get("bundle_id"), "BND-IDENTITY-ID")
    body = dict(identity)
    del body["bundle_id"]
    if sha256_bytes(canonical_bytes(body)) != bundle_id:
        raise CandidateError("BND-IDENTITY-ID", "bundle identity digest drifted")


def verify_bundle(path: Path) -> dict[str, object]:
    try:
        with ZipFile(path) as archive:
            infos = _validated_infos(archive, "BND-ARCHIVE-PATH")
            if IDENTITY_PATH not in infos:
                raise CandidateError("BND-IDENTITY-MISSING", "identity is absent")
            raw_identity = archive.read(IDENTITY_PATH)
            identity = _json_object(raw_identity, "BND-IDENTITY-JSON")
            if canonical_bytes(identity) != raw_identity:
                raise CandidateError(
                    "BND-IDENTITY-CANONICAL", "identity is not canonical"
                )
            _validate_identity(identity)
            wheels_value = identity.get("wheels")
            locks_value = identity.get("locks")
            if not isinstance(wheels_value, list) or not isinstance(locks_value, list):
                raise CandidateError(
                    "BND-IDENTITY-FIELDS", "artifact lists are invalid"
                )
            references: dict[str, dict[str, object]] = {}
            for item in [*wheels_value, *locks_value]:
                if not isinstance(item, dict):
                    raise CandidateError(
                        "BND-IDENTITY-FIELDS", "invalid artifact entry"
                    )
                artifact = cast(dict[str, object], item)
                path_value = _require_string(artifact.get("path"), "BND-ARTIFACT-PATH")
                if path_value in references:
                    raise CandidateError("BND-ARTIFACT-PATH", "duplicate artifact path")
                references[path_value] = artifact
            if set(infos) != {IDENTITY_PATH, *references}:
                raise CandidateError("BND-ARCHIVE-SET", "archive member set drifted")
            payloads: dict[str, bytes] = {}
            for member, artifact in references.items():
                data = archive.read(member)
                if len(data) != _require_integer(
                    artifact.get("size"), "BND-ARTIFACT-SIZE"
                ):
                    raise CandidateError("BND-ARTIFACT-SIZE", f"size drifted: {member}")
                if sha256_bytes(data) != _require_digest(
                    artifact.get("sha256"), "BND-ARTIFACT-DIGEST"
                ):
                    raise CandidateError(
                        "BND-ARTIFACT-DIGEST", f"digest drifted: {member}"
                    )
                _scan_candidate_payload(member, data)
                payloads[member] = data
            rebuilt = build_identity(
                _require_string(identity["source_revision"], "BND-IDENTITY-SOURCE"),
                [
                    (
                        _require_string(item["path"], "BND-WHEEL-SET"),
                        payloads[cast(str, item["path"])],
                    )
                    for item in cast(list[dict[str, object]], wheels_value)
                ],
                [
                    (
                        _require_string(item.get("role"), "BND-LOCK-SET"),
                        _require_string(item.get("path"), "BND-LOCK-SET"),
                        payloads[cast(str, item["path"])],
                        cast(str | None, item.get("derived_from")),
                    )
                    for item in cast(list[dict[str, object]], locks_value)
                ],
            )
            if rebuilt != identity:
                raise CandidateError("BND-IDENTITY-RECOMPUTE", "identity facts drifted")
            requirements = payloads["locks/runtime-requirements.txt"]
            lowered = requirements.decode("utf-8").lower()
            if (
                "file:" in lowered
                or "-e " in lowered
                or "armi-runtime" in lowered
                or "armi-kernel" in lowered
                or "armi-admin" in lowered
                or re.search(r"(?i)(?:[a-z]:[\\/]|/(?:home|users)/)", lowered)
            ):
                raise CandidateError(
                    "BND-LOCK-LOCAL", "requirements contain local inputs"
                )
    except (OSError, BadZipFile) as error:
        raise CandidateError(
            "BND-ARCHIVE-READ", "candidate archive is unreadable"
        ) from error
    return identity
