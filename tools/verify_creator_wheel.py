"""Verify the frozen Creator and Runtime-composition wheel resources."""

from __future__ import annotations

import argparse
import importlib
import importlib.resources
import sys
from pathlib import Path
from zipfile import ZipFile

PACKAGE_PREFIX = "armi_runtime/interfaces/creator_web_resources/"
RUNTIME_PREFIX = "armi_runtime/composition/runtime_resources/"
REQUIRED = {
    f"{PACKAGE_PREFIX}openapi.json",
    f"{PACKAGE_PREFIX}manifest.json",
    f"{PACKAGE_PREFIX}static/index.html",
    f"{PACKAGE_PREFIX}static/.vite/manifest.json",
    f"{RUNTIME_PREFIX}runtime.defaults.toml",
    f"{RUNTIME_PREFIX}runtime-composition.manifest.json",
}
FORBIDDEN_PARTS = (
    "node_modules",
    "armi-creator-web/src",
    ".map",
    "/tests/",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--creator-resources", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    wheel = args.wheel
    if wheel is None:
        candidates = sorted(
            (root / ".tmp/quality/python-dist").glob("armi_runtime*.whl")
        )
        if len(candidates) != 1:
            print("WEB-WHEEL-MISSING: expected one Runtime wheel", file=sys.stderr)
            return 1
        wheel = candidates[0]
    wheel = wheel.resolve()
    if not wheel.is_file():
        print("WEB-WHEEL-MISSING: Runtime wheel is absent", file=sys.stderr)
        return 1

    source_root = (
        root / "apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources"
    )
    built_root = (
        args.creator_resources.resolve()
        if args.creator_resources is not None
        else root / "apps/armi-runtime/build/creator-web-resources"
    )
    if not (built_root / "manifest.json").is_file():
        print("WEB-WHEEL-MISSING: built Creator resources are absent", file=sys.stderr)
        return 1
    creator_files = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(source_root).parts
        and path.suffix != ".pyc"
    }
    creator_files.update(
        {
            path.relative_to(built_root).as_posix(): path.read_bytes()
            for path in built_root.rglob("*")
            if path.is_file()
        }
    )
    runtime_root = (
        root / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources"
    )
    runtime_files = {
        path.relative_to(runtime_root).as_posix(): path.read_bytes()
        for path in runtime_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(runtime_root).parts
        and path.suffix != ".pyc"
    }
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED - names)
        forbidden = sorted(
            name for name in names if any(part in name for part in FORBIDDEN_PARTS)
        )
        drift = sorted(
            relative
            for relative, expected in creator_files.items()
            if f"{PACKAGE_PREFIX}{relative}" not in names
            or archive.read(f"{PACKAGE_PREFIX}{relative}") != expected
        )
        runtime_drift = sorted(
            relative
            for relative, expected in runtime_files.items()
            if f"{RUNTIME_PREFIX}{relative}" not in names
            or archive.read(f"{RUNTIME_PREFIX}{relative}") != expected
        )
        entry_points = [
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        ]
        entry_point_valid = len(entry_points) == 1 and archive.read(
            entry_points[0]
        ) == (
            b"[console_scripts]\n"
            b"armi = armi_runtime.cli:main\n"
            b"armi-codex-runner = armi_runtime.codex_runner_cli:main\n"
        )
    if missing:
        print(f"WEB-WHEEL-MISSING: {', '.join(missing)}", file=sys.stderr)
        return 1
    if forbidden:
        print(f"WEB-WHEEL-FORBIDDEN: {', '.join(forbidden)}", file=sys.stderr)
        return 1
    if drift:
        print(f"WEB-WHEEL-DIGEST: {', '.join(drift)}", file=sys.stderr)
        return 1
    if runtime_drift:
        print(
            f"CMP-WHEEL-DIGEST: {', '.join(runtime_drift)}",
            file=sys.stderr,
        )
        return 1
    if not entry_point_valid:
        print("LIFE-WHEEL-ENTRY: Runtime console entries have drifted", file=sys.stderr)
        return 1

    sys.path.insert(0, str(wheel))
    try:
        module = importlib.import_module(
            "armi_runtime.interfaces.creator_web_resources"
        )
        manifest = importlib.resources.files(module).joinpath("manifest.json")
        if manifest.read_bytes() != creator_files["manifest.json"]:
            print("WEB-WHEEL-READ: resource API returned drift", file=sys.stderr)
            return 1
    finally:
        sys.path.pop(0)
        for name in tuple(sys.modules):
            if name == "armi_runtime" or name.startswith("armi_runtime."):
                del sys.modules[name]

    print(
        "creator-wheel: pass "
        f"({len(creator_files)} Creator resources, "
        f"{len(runtime_files)} composition resources, console entry, "
        "Node-independent read)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
