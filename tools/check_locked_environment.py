"""Validate the supported platform and toolchain metadata."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TARGET_PYTHON = "3.14.6"
TARGET_NODE = "24.18.0"
TARGET_NPM = "11.16.0"
TARGET_UV = "0.11.33"
TARGET_POSTGRESQL = "18.4"


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
        violations.append(
            Violation("S003-METADATA", path.as_posix(), "root must be an object")
        )
        return None
    return data


def _expect(
    violations: list[Violation],
    *,
    actual: object,
    expected: object,
    path: Path,
    field: str,
) -> None:
    if actual != expected:
        violations.append(
            Violation(
                "S003-VERSION",
                path.as_posix(),
                f"{field} expected {expected!r}, got {actual!r}",
            )
        )


def check_repository(
    root: Path,
    *,
    system_name: str | None = None,
    machine: str | None = None,
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
            "hatchling": "1.31.0",
            "node": TARGET_NODE,
            "npm": TARGET_NPM,
            "codex-cli": "0.144.4",
            "pyright": "1.1.411",
            "postgresql": TARGET_POSTGRESQL,
        }.items():
            _expect(
                violations,
                actual=versions.get(tool_id),
                expected=version,
                path=manifest_path,
                field=f"tools.{tool_id}.version",
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--system")
    parser.add_argument("--machine")
    args = parser.parse_args(argv)
    violations = check_repository(
        args.root,
        system_name=args.system,
        machine=args.machine,
    )
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1
    print("locked-environment: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
