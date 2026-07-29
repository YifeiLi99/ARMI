"""Verify that the Runtime wheel carries only the frozen Creator resources."""

from __future__ import annotations

import argparse
import importlib
import importlib.resources
import sys
from pathlib import Path
from zipfile import ZipFile

PACKAGE_PREFIX = "armi_runtime/interfaces/creator_web_resources/"
REQUIRED = {
    f"{PACKAGE_PREFIX}openapi.json",
    f"{PACKAGE_PREFIX}manifest.json",
    f"{PACKAGE_PREFIX}static/index.html",
    f"{PACKAGE_PREFIX}static/.vite/manifest.json",
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
    expected_files = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED - names)
        forbidden = sorted(
            name for name in names if any(part in name for part in FORBIDDEN_PARTS)
        )
        drift = sorted(
            relative
            for relative, expected in expected_files.items()
            if f"{PACKAGE_PREFIX}{relative}" not in names
            or archive.read(f"{PACKAGE_PREFIX}{relative}") != expected
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

    sys.path.insert(0, str(wheel))
    try:
        module = importlib.import_module(
            "armi_runtime.interfaces.creator_web_resources"
        )
        manifest = importlib.resources.files(module).joinpath("manifest.json")
        if manifest.read_bytes() != expected_files["manifest.json"]:
            print("WEB-WHEEL-READ: resource API returned drift", file=sys.stderr)
            return 1
    finally:
        sys.path.pop(0)
        for name in tuple(sys.modules):
            if name == "armi_runtime" or name.startswith("armi_runtime."):
                del sys.modules[name]

    print(
        "creator-wheel: pass "
        f"({len(expected_files)} exact resources, Node-independent read)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
