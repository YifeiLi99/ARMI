"""Path containment and Windows reparse-point checks."""

from __future__ import annotations

import stat
from pathlib import Path

from .errors import ConfigurationViolation

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def canonical_absolute(path: Path, *, code: str) -> Path:
    if not path.is_absolute():
        raise ConfigurationViolation(code, "an absolute path is required")
    try:
        return path.resolve(strict=False)
    except OSError:
        raise ConfigurationViolation(code, "path normalization failed") from None


def require_within_roots(
    path: Path, roots: tuple[Path, ...], *, code: str
) -> tuple[Path, Path]:
    candidate = canonical_absolute(path, code=code)
    for configured_root in roots:
        root = canonical_absolute(configured_root, code=code)
        if candidate == root or candidate.is_relative_to(root):
            return candidate, root
    raise ConfigurationViolation(code, "path is outside the trusted roots")


def has_reparse_point(path: Path, *, root: Path) -> bool:
    relative = path.relative_to(root)
    candidates = [root]
    current = root
    for part in relative.parts:
        current = current / part
        candidates.append(current)
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            attributes = candidate.stat(follow_symlinks=False).st_file_attributes
        except AttributeError, OSError:
            attributes = 0
        if candidate.is_symlink() or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            return True
        try:
            if stat.S_ISLNK(candidate.lstat().st_mode):
                return True
        except OSError:
            return True
    return False


__all__ = ("canonical_absolute", "has_reparse_point", "require_within_roots")
