"""Content-addressed source extraction and independent tree accounting."""

from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import rfc8785
from armi_kernel.application import CodexRunnerViolation, CodexTaskManifest
from armi_kernel.contracts import Digest

_REPARSE = 0x400
_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    digest: Digest
    files: tuple[tuple[str, str, int], ...]
    byte_size: int


def extract_source_bundle(
    bundle: Path,
    workspace: Path,
    task: CodexTaskManifest,
) -> TreeSnapshot:
    _safe_regular(bundle, "CODEX-SOURCE-BUNDLE")
    if Digest.from_bytes(bundle.read_bytes()) != task.source_bundle_digest:
        raise CodexRunnerViolation("CODEX-SOURCE-DIGEST")
    workspace.mkdir(parents=True, exist_ok=False)
    names: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                relative = _archive_path(entry.filename)
                folded = relative.casefold()
                if folded in names or _zip_link(entry):
                    raise CodexRunnerViolation("CODEX-SOURCE-PATH")
                names.add(folded)
                total += entry.file_size
                if total > task.workspace_limit_bytes:
                    raise CodexRunnerViolation("CODEX-WORKSPACE-LIMIT")
                target = workspace.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry, "r") as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                _safe_regular(target, "CODEX-SOURCE-PATH")
    except zipfile.BadZipFile, OSError:
        raise CodexRunnerViolation("CODEX-SOURCE-BUNDLE") from None
    snapshot = snapshot_tree(workspace, byte_limit=task.workspace_limit_bytes)
    if snapshot.digest != task.source_tree_digest:
        raise CodexRunnerViolation("CODEX-SOURCE-TREE")
    return snapshot


def snapshot_tree(root: Path, *, byte_limit: int) -> TreeSnapshot:
    _safe_directory(root)
    records: list[tuple[str, str, int]] = []
    total = 0
    folded: set[str] = set()
    try:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_dir():
                _safe_directory(path)
                continue
            _safe_regular(path, "CODEX-WORKSPACE-PATH")
            relative = path.relative_to(root).as_posix()
            _archive_path(relative)
            if relative.casefold() in folded:
                raise CodexRunnerViolation("CODEX-WORKSPACE-PATH")
            folded.add(relative.casefold())
            size = path.stat().st_size
            total += size
            if total > byte_limit:
                raise CodexRunnerViolation("CODEX-WORKSPACE-LIMIT")
            records.append((relative, _sha256_file(path), size))
    except OSError:
        raise CodexRunnerViolation("CODEX-WORKSPACE-PATH") from None
    canonical = rfc8785.dumps(
        cast(
            Any,
            [
                {"path": path, "sha256": digest, "bytes": size}
                for path, digest, size in records
            ],
        )
    )
    return TreeSnapshot(Digest.from_bytes(canonical), tuple(records), total)


def changed_paths(
    before: TreeSnapshot,
    after: TreeSnapshot,
    task: CodexTaskManifest,
) -> tuple[str, ...]:
    old = {path: (digest, size) for path, digest, size in before.files}
    new = {path: (digest, size) for path, digest, size in after.files}
    changed = tuple(
        sorted(
            path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
        )
    )
    if not changed or len(changed) > task.modified_file_limit:
        raise CodexRunnerViolation("CODEX-VALIDATION")
    for path in changed:
        # An empty legacy allow-list means the whole disposable workspace is writable.
        # The forbidden paths remain authoritative and the workspace boundary itself is
        # enforced by archive extraction and the Codex sandbox.
        if task.allowed_paths and not any(
            _matches(path, allowed) for allowed in task.allowed_paths
        ):
            raise CodexRunnerViolation("CODEX-SCOPE")
        if any(_matches(path, denied) for denied in task.forbidden_paths):
            raise CodexRunnerViolation("CODEX-SCOPE")
    patch_bytes = sum(
        (old.get(path, ("", 0))[1] + new.get(path, ("", 0))[1]) for path in changed
    )
    if patch_bytes > task.diff_limit_bytes:
        raise CodexRunnerViolation("CODEX-DIFF-LIMIT")
    return changed


def patch_digest(
    before: TreeSnapshot,
    after: TreeSnapshot,
    paths: tuple[str, ...],
) -> Digest:
    old = {path: digest for path, digest, _ in before.files}
    new = {path: digest for path, digest, _ in after.files}
    value = [
        {"path": path, "before": old.get(path), "after": new.get(path)}
        for path in paths
    ]
    return Digest.from_bytes(rfc8785.dumps(cast(Any, value)))


def _archive_path(value: str) -> str:
    if not value or "\\" in value or ":" in value:
        raise CodexRunnerViolation("CODEX-SOURCE-PATH")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CodexRunnerViolation("CODEX-SOURCE-PATH")
    for part in path.parts:
        stem = part.rstrip(" .").split(".", 1)[0].casefold()
        if (
            part.rstrip(" .") != part
            or stem in _RESERVED
            or part.casefold() == ".codex"
        ):
            raise CodexRunnerViolation("CODEX-SOURCE-PATH")
    return path.as_posix()


def _matches(path: str, scope: str) -> bool:
    return path == scope or path.startswith(scope.rstrip("/") + "/")


def _zip_link(entry: zipfile.ZipInfo) -> bool:
    mode = entry.external_attr >> 16
    return stat.S_ISLNK(mode) or (mode != 0 and not stat.S_ISREG(mode))


def _safe_regular(path: Path, code: str) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise CodexRunnerViolation(code) from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_nlink != 1
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE
    ):
        raise CodexRunnerViolation(code)


def _safe_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise CodexRunnerViolation("CODEX-WORKSPACE-PATH") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE
    ):
        raise CodexRunnerViolation("CODEX-WORKSPACE-PATH")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = (
    "TreeSnapshot",
    "changed_paths",
    "extract_source_bundle",
    "patch_digest",
    "snapshot_tree",
)
