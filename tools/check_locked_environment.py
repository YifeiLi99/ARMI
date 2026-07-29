"""Validate the M0-S003 toolchain, direct dependencies, locks, and inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TARGET_PYTHON = "3.14.6"
TARGET_NODE = "24.18.0"
TARGET_NPM = "11.16.0"
TARGET_UV = "0.11.33"

PYTHON_DIRECT = {
    "fastapi": "0.140.13",
    "hypothesis": "6.163.0",
    "mcp": "2.0.0",
    "openai": "2.49.0",
    "playwright": "1.61.0",
    "psycopg": "3.3.4",
    "psycopg-pool": "3.3.1",
    "pydantic": "2.13.4",
    "pytest": "9.1.1",
    "pytest-asyncio": "1.4.0",
    "rfc8785": "0.1.4",
    "ruff": "0.16.0",
    "uvicorn": "0.51.0",
}

CREATOR_DEPENDENCIES = {
    "@tanstack/react-query": "5.101.4",
    "react": "19.2.8",
    "react-dom": "19.2.8",
}

CREATOR_DEV_DEPENDENCIES = {
    "@testing-library/dom": "10.4.1",
    "@testing-library/jest-dom": "6.9.1",
    "@testing-library/react": "16.3.2",
    "@testing-library/user-event": "14.6.1",
    "@types/node": "24.13.3",
    "@types/react": "19.2.17",
    "@types/react-dom": "19.2.3",
    "@vitejs/plugin-react": "6.0.4",
    "jsdom": "30.0.0",
    "openapi-typescript": "7.13.0",
    "oxlint": "1.76.0",
    "prettier": "3.9.6",
    "typescript": "5.9.3",
    "vite": "8.1.5",
    "vitest": "4.1.10",
}

TOOL_DEPENDENCIES = {
    "@openai/codex": "0.144.4",
    "pyright": "1.1.411",
}

FLOATING_PREFIX = re.compile(r"^(?:\^|~|>|<|=|latest\b|\*|workspace:)", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str

    def render(self) -> str:
        return f"{self.code} {self.path}: {self.message}"


def _read_text(path: Path, violations: list[Violation]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        violations.append(Violation("S003-MISSING", path.as_posix(), str(error)))
        return None


def _load_json(path: Path, violations: list[Violation]) -> dict[str, Any] | None:
    text = _read_text(path, violations)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        violations.append(Violation("S003-METADATA", path.as_posix(), str(error)))
        return None
    if not isinstance(data, dict):
        violations.append(Violation("S003-METADATA", path.as_posix(), "root must be an object"))
        return None
    return data


def _load_toml(path: Path, violations: list[Violation]) -> dict[str, Any] | None:
    text = _read_text(path, violations)
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        violations.append(Violation("S003-METADATA", path.as_posix(), str(error)))
        return None


def _expect(
    violations: list[Violation],
    *,
    actual: object,
    expected: object,
    path: Path,
    field: str,
    code: str = "S003-VERSION",
) -> None:
    if actual != expected:
        violations.append(
            Violation(code, path.as_posix(), f"{field} expected {expected!r}, got {actual!r}")
        )


def _check_exact_map(
    violations: list[Violation],
    *,
    actual: object,
    expected: dict[str, str],
    path: Path,
    field: str,
) -> None:
    if not isinstance(actual, dict):
        violations.append(Violation("S003-METADATA", path.as_posix(), f"{field} must be an object"))
        return
    _expect(
        violations,
        actual=actual,
        expected=expected,
        path=path,
        field=field,
        code="S003-LOCK-DRIFT",
    )
    for name, version in actual.items():
        if not isinstance(version, str) or FLOATING_PREFIX.match(version):
            violations.append(
                Violation(
                    "S003-FLOATING",
                    path.as_posix(),
                    f"{field}.{name} must be an exact version, got {version!r}",
                )
            )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_package_lock(
    root: Path,
    relative: str,
    expected_dependencies: dict[str, str],
    expected_dev_dependencies: dict[str, str],
    violations: list[Violation],
) -> None:
    path = root / relative
    data = _load_json(path, violations)
    if data is None:
        return
    _expect(
        violations,
        actual=data.get("lockfileVersion"),
        expected=3,
        path=path,
        field="lockfileVersion",
        code="S003-LOCK-DRIFT",
    )
    packages = data.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        violations.append(
            Violation("S003-LOCK-DRIFT", path.as_posix(), "lock root package is missing")
        )
        return
    lock_root = packages[""]
    _check_exact_map(
        violations,
        actual=lock_root.get("dependencies", {}),
        expected=expected_dependencies,
        path=path,
        field="packages[''].dependencies",
    )
    _check_exact_map(
        violations,
        actual=lock_root.get("devDependencies", {}),
        expected=expected_dev_dependencies,
        path=path,
        field="packages[''].devDependencies",
    )
    for dependency, version in {**expected_dependencies, **expected_dev_dependencies}.items():
        package_key = f"node_modules/{dependency}"
        entry = packages.get(package_key)
        if not isinstance(entry, dict) or entry.get("version") != version:
            violations.append(
                Violation(
                    "S003-LOCK-DRIFT",
                    path.as_posix(),
                    f"{package_key} exact version {version} is not locked",
                )
            )


def check_repository(
    root: Path,
    *,
    system_name: str | None = None,
    machine: str | None = None,
    require_generated: bool = True,
) -> list[Violation]:
    """Return all deterministic M0-S003 violations."""

    root = root.resolve()
    violations: list[Violation] = []
    actual_system = (system_name or platform.system()).lower()
    actual_machine = (machine or platform.machine()).lower()
    if actual_system != "windows" or actual_machine not in {"amd64", "x86_64"}:
        violations.append(
            Violation(
                "S003-PLATFORM",
                "<platform>",
                f"supported target is Windows x86_64, got {actual_system}/{actual_machine}",
            )
        )

    for relative, expected in (
        (".python-version", TARGET_PYTHON),
        (".node-version", TARGET_NODE),
    ):
        path = root / relative
        text = _read_text(path, violations)
        if text is not None:
            _expect(
                violations,
                actual=text.strip(),
                expected=expected,
                path=path,
                field=relative,
            )

    creator_path = root / "apps/armi-creator-web/package.json"
    creator = _load_json(creator_path, violations)
    if creator is not None:
        _expect(
            violations,
            actual=creator.get("engines"),
            expected={"node": TARGET_NODE},
            path=creator_path,
            field="engines",
        )
        _expect(
            violations,
            actual=creator.get("packageManager"),
            expected=f"npm@{TARGET_NPM}",
            path=creator_path,
            field="packageManager",
        )
        _check_exact_map(
            violations,
            actual=creator.get("dependencies"),
            expected=CREATOR_DEPENDENCIES,
            path=creator_path,
            field="dependencies",
        )
        _check_exact_map(
            violations,
            actual=creator.get("devDependencies"),
            expected=CREATOR_DEV_DEPENDENCIES,
            path=creator_path,
            field="devDependencies",
        )

    tool_path = root / "tools/toolchain-node/package.json"
    tool = _load_json(tool_path, violations)
    if tool is not None:
        _expect(
            violations,
            actual=tool.get("engines"),
            expected={"node": TARGET_NODE},
            path=tool_path,
            field="engines",
        )
        _expect(
            violations,
            actual=tool.get("packageManager"),
            expected=f"npm@{TARGET_NPM}",
            path=tool_path,
            field="packageManager",
        )
        _check_exact_map(
            violations,
            actual=tool.get("devDependencies"),
            expected=TOOL_DEPENDENCIES,
            path=tool_path,
            field="devDependencies",
        )

    uv_lock_path = root / "uv.lock"
    uv_lock = _load_toml(uv_lock_path, violations)
    if uv_lock is not None:
        locked = {
            str(entry.get("name", "")).lower(): str(entry.get("version", ""))
            for entry in uv_lock.get("package", [])
            if isinstance(entry, dict)
        }
        for name, version in PYTHON_DIRECT.items():
            if locked.get(name) != version:
                violations.append(
                    Violation(
                        "S003-LOCK-DRIFT",
                        uv_lock_path.as_posix(),
                        f"{name} exact version {version} is not locked",
                    )
                )

    _check_package_lock(
        root,
        "apps/armi-creator-web/package-lock.json",
        CREATOR_DEPENDENCIES,
        CREATOR_DEV_DEPENDENCIES,
        violations,
    )
    _check_package_lock(
        root,
        "tools/toolchain-node/package-lock.json",
        {},
        TOOL_DEPENDENCIES,
        violations,
    )

    manifest_path = root / "tools/toolchain-manifest.json"
    manifest = _load_json(manifest_path, violations)
    if manifest is not None:
        versions = {
            str(item.get("id")): item.get("version")
            for item in manifest.get("tools", [])
            if isinstance(item, dict)
        }
        for tool_id, version in {
            "cpython": TARGET_PYTHON,
            "uv": TARGET_UV,
            "uv-build": TARGET_UV,
            "node": TARGET_NODE,
            "npm": TARGET_NPM,
            "codex-cli": "0.144.4",
            "pyright": "1.1.411",
        }.items():
            _expect(
                violations,
                actual=versions.get(tool_id),
                expected=version,
                path=manifest_path,
                field=f"tools.{tool_id}.version",
            )
        for lock in manifest.get("lockfiles", []):
            if not isinstance(lock, dict):
                continue
            relative = lock.get("path")
            if not isinstance(relative, str):
                continue
            lock_path = root / relative
            if lock_path.exists():
                _expect(
                    violations,
                    actual=lock.get("sha256"),
                    expected=_sha256(lock_path),
                    path=manifest_path,
                    field=f"lockfiles.{relative}.sha256",
                    code="S003-LOCK-DRIFT",
                )

    if require_generated:
        inventory_path = root / "tools/dependency-inventory.json"
        inventory = _load_json(inventory_path, violations)
        if inventory is not None:
            _expect(
                violations,
                actual=inventory.get("status"),
                expected="pass",
                path=inventory_path,
                field="status",
                code="S003-INVENTORY",
            )
            unresolved = inventory.get("unresolved_licenses")
            _expect(
                violations,
                actual=unresolved,
                expected=[],
                path=inventory_path,
                field="unresolved_licenses",
                code="S003-INVENTORY",
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--system")
    parser.add_argument("--machine")
    parser.add_argument("--allow-pending-generated", action="store_true")
    args = parser.parse_args(argv)
    violations = check_repository(
        args.root,
        system_name=args.system,
        machine=args.machine,
        require_generated=not args.allow_pending_generated,
    )
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1
    print("locked-environment: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
