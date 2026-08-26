"""Reproducible identity for the Admin process and its dependency closure."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import stat
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from packaging.requirements import Requirement

_OWNED_MODULES = (
    "armi_admin",
    "armi_artifact_store",
    "armi_cognition",
    "armi_effect",
    "armi_expression",
    "armi_interaction",
    "armi_kernel",
    "armi_material",
    "armi_mood",
    "armi_postgresql_contract",
    "armi_runtime_foundation",
    "armi_subject_state",
)
_RESOURCE_SUFFIXES = frozenset({".json", ".mako", ".py", ".sql", ".toml", ".yaml"})


class AdminPackageIdentityError(RuntimeError):
    """The running package set is not a sealed production identity."""


def _feed(hasher: object, label: str, value: bytes) -> None:
    digest = hasher
    assert hasattr(digest, "update")
    encoded = label.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))  # type: ignore[attr-defined]
    digest.update(encoded)  # type: ignore[attr-defined]
    digest.update(len(value).to_bytes(8, "big"))  # type: ignore[attr-defined]
    digest.update(value)  # type: ignore[attr-defined]


def _regular_bytes(path: Path) -> bytes:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        raise AdminPackageIdentityError("ADMIN-PACKAGE-UNSEALED-FILE")
    value = path.read_bytes()
    after = path.lstat()
    if (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise AdminPackageIdentityError("ADMIN-PACKAGE-FILE-RACE")
    return value


def _module_roots() -> tuple[tuple[str, Path], ...]:
    roots: list[tuple[str, Path]] = []
    for module_name in _OWNED_MODULES:
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            raise AdminPackageIdentityError("ADMIN-PACKAGE-MISSING")
        origin = Path(spec.origin).resolve(strict=True)
        roots.append(
            (module_name, origin.parent if origin.name == "__init__.py" else origin)
        )
    return tuple(roots)


def _editable(distribution: importlib.metadata.Distribution) -> bool:
    try:
        direct_url = distribution.read_text("direct_url.json")
        if direct_url is None:
            return False
        value = json.loads(direct_url)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise AdminPackageIdentityError("ADMIN-PACKAGE-METADATA") from None
    if not isinstance(value, Mapping):
        return False
    metadata = cast(Mapping[str, object], value)
    directory = metadata.get("dir_info")
    return (
        isinstance(directory, Mapping)
        and cast(Mapping[str, object], directory).get("editable") is True
    )


def _distribution_closure() -> tuple[importlib.metadata.Distribution, ...]:
    pending: deque[str] = deque(("armi-admin",))
    result: dict[str, importlib.metadata.Distribution] = {}
    while pending:
        name = pending.popleft()
        normalized = name.lower().replace("_", "-")
        if normalized in result:
            continue
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise AdminPackageIdentityError("ADMIN-PACKAGE-MISSING") from exc
        result[normalized] = distribution
        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker is None or requirement.marker.evaluate():
                pending.append(requirement.name)
    return tuple(result[name] for name in sorted(result))


def admin_package_set_digest(*, allow_editable: bool = False) -> str:
    """Hash owned resources plus every installed dependency selected by metadata."""

    hasher = hashlib.sha256()
    distributions = _distribution_closure()
    if not allow_editable and any(_editable(item) for item in distributions):
        raise AdminPackageIdentityError("ADMIN-PACKAGE-EDITABLE")
    for module_name, root in _module_roots():
        if root.is_file():
            _feed(hasher, f"module:{module_name}", _regular_bytes(root))
            continue
        for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
            if not path.is_file() or path.suffix not in _RESOURCE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            _feed(hasher, f"module:{module_name}:{relative}", _regular_bytes(path))
    for distribution in distributions:
        name = str(distribution.metadata["Name"]).lower().replace("_", "-")
        _feed(
            hasher,
            f"distribution:{name}",
            str(distribution.version).encode("utf-8"),
        )
        if name.startswith("armi-"):
            continue
        for relative in sorted(distribution.files or (), key=os.fspath):
            path = Path(str(distribution.locate_file(relative)))
            if path.is_file():
                _feed(
                    hasher,
                    f"distribution:{name}:{str(relative).replace('\\\\', '/')}",
                    _regular_bytes(path),
                )
    return f"sha256:{hasher.hexdigest()}"


def verify_admin_package_set(expected: str) -> None:
    if admin_package_set_digest() != expected:
        raise AdminPackageIdentityError("ADMIN-PACKAGE-DIGEST")


__all__ = (
    "AdminPackageIdentityError",
    "admin_package_set_digest",
    "verify_admin_package_set",
)
