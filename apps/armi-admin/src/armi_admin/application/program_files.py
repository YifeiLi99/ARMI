"""Copy and remove only files owned by a verified program distribution."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from armi_local_control.configuration.paths import has_reparse_point

from .distribution import ProgramBundle


def copy_program(source: Path, target: Path, bundle: ProgramBundle) -> None:
    target.mkdir()
    for relative in (*bundle.files, "bundle.json"):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)


def remove_program(
    program: Path, bundle: ProgramBundle, *, partial: bool = False
) -> bool:
    """Keep unknown/modified files; a partial unpublished copy can be discarded."""
    if not program.exists():
        return True
    if has_reparse_point(program, root=Path(program.anchor)):
        raise ValueError("INSTALLER-CLEANUP-BOUNDARY")
    owned = set(bundle.files) | {"bundle.json", ".update.lock"}
    paths = list(program.rglob("*"))
    removable: list[Path] = []
    for path in paths:
        if has_reparse_point(path, root=program):
            raise ValueError("INSTALLER-CLEANUP-BOUNDARY")
        if not path.is_file():
            continue
        relative = path.relative_to(program).as_posix()
        generated = False
        if path.parent.name == "__pycache__" and path.suffix == ".pyc":
            source = path.parent.parent / (path.name.split(".cpython-")[0] + ".py")
            generated = source.relative_to(program).as_posix() in bundle.files
        if relative not in owned and not generated:
            continue
        if not partial and relative in bundle.files:
            with path.open("rb") as stream:
                if (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    != bundle.files[relative]
                ):
                    continue
        removable.append(path)
    # Preserve the manifest when anything unknown remains, for later inspection.
    unknown = {p for p in paths if p.is_file()} - set(removable)
    for path in removable:
        if path == program / "bundle.json":
            continue
        path.unlink()
    for path in sorted(
        (p for p in paths if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        if not any(path.iterdir()):
            path.rmdir()
    if not unknown:
        (program / "bundle.json").unlink(missing_ok=True)
    if not any(program.iterdir()):
        program.rmdir()
        return True
    return False
