"""Run fast development checks, or the full offline release gate on request."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

GATE_ORDER = (
    "QLT-LOCKED",
    "PY-FORMAT",
    "PY-LINT",
    "PY-TYPE",
    "PY-TEST",
    "ARC-SURFACE",
    "SEC-REPOSITORY",
    "WEB-FORMAT",
    "WEB-LINT",
    "WEB-TYPE",
    "WEB-TEST",
    "BUILD-WEB",
    "BUILD-PY",
)
FAST_GATE_ORDER = (
    "PY-FORMAT",
    "PY-LINT",
    "PY-TYPE",
    "PY-TEST",
    "WEB-FORMAT",
    "WEB-LINT",
    "WEB-TYPE",
    "WEB-TEST",
)


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    exit_code: int
    output: str


@dataclass(frozen=True)
class Gate:
    gate_id: str
    command: tuple[str, ...]
    cwd: Path
    required_paths: tuple[Path, ...] = ()
    prepare: Callable[[], None] | None = None
    validate: Callable[[], tuple[bool, str]] | None = None


def aggregate_exit_code(results: Iterable[GateResult]) -> int:
    statuses = {result.status for result in results}
    if "fail" in statuses:
        return 1
    if "blocked" in statuses:
        return 2
    return 0


def safe_remove_output(path: Path, quality_root: Path) -> None:
    resolved = path.resolve()
    allowed = quality_root.resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise RuntimeError(f"unsafe quality output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def run_gate(gate: Gate, environment: dict[str, str]) -> GateResult:
    missing = [path for path in gate.required_paths if not path.is_file()]
    if missing:
        names = ", ".join(path.name for path in missing)
        return GateResult(gate.gate_id, "blocked", 2, f"missing required tool: {names}")
    try:
        if gate.prepare:
            gate.prepare()
        completed = subprocess.run(
            gate.command,
            cwd=gate.cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return GateResult(gate.gate_id, "blocked", 2, str(error))
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    if completed.returncode != 0:
        return GateResult(gate.gate_id, "fail", completed.returncode, output)
    if gate.validate:
        valid, validation_output = gate.validate()
        if validation_output:
            output = "\n".join(item for item in (output, validation_output) if item)
        if not valid:
            return GateResult(gate.gate_id, "fail", 1, output)
    return GateResult(gate.gate_id, "pass", 0, output)


def commands(root: Path, tool_root: Path) -> dict[str, Gate]:
    venv_python = root / ".venv/Scripts/python.exe"
    managed_python = (
        tool_root / "installs/python/cpython-3.14.6-windows-x86_64-none/python.exe"
    )
    node = tool_root / "installs/node/node-v24.18.0-win-x64/node.exe"
    uv = tool_root / "installs/uv/0.11.33/uv.exe"
    creator = root / "apps/armi-creator-web"
    node_modules = creator / "node_modules"
    pyright = root / "tools/toolchain-node/node_modules/pyright/index.js"
    quality_root = root / ".tmp/quality"
    python_dist = quality_root / "python-dist"

    def validate_python_build() -> tuple[bool, str]:
        artifacts = sorted(
            path.name for path in python_dist.glob("*") if path.is_file()
        )
        expected = (
            "armi_activity",
            "armi_adapter_qq",
            "armi_admin",
            "armi_artifact_store",
            "armi_channel_napcat",
            "armi_kernel",
            "armi_memory",
            "armi_material",
            "armi_postgresql_contract",
            "armi_relationship",
            "armi_runtime",
            "armi_runtime_foundation",
            "armi_sleep",
            "armi_subject_state",
            "armi_mood",
            "armi_prompt",
        )
        wheels = [name for name in artifacts if name.endswith(".whl")]
        source_distributions = [name for name in artifacts if name.endswith(".tar.gz")]
        valid = (
            len(artifacts) == 32
            and len(wheels) == 16
            and len(source_distributions) == 16
            and all(
                any(name.startswith(prefix) for name in wheels) for prefix in expected
            )
            and all(
                any(name.startswith(prefix) for name in source_distributions)
                for prefix in expected
            )
        )
        summary = f"python build artifacts: {', '.join(artifacts)}"
        if not valid:
            return False, summary
        runtime_wheels = sorted(
            path for path in python_dist.glob("armi_runtime*.whl") if path.is_file()
        )
        if len(runtime_wheels) != 1:
            return False, f"{summary}\nexpected one Runtime wheel"
        completed = subprocess.run(
            (
                str(managed_python),
                "-B",
                str(root / "tools/verify_creator_wheel.py"),
                "--root",
                str(root),
                "--wheel",
                str(runtime_wheels[0]),
            ),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        verification = "\n".join(
            item.strip()
            for item in (completed.stdout, completed.stderr)
            if item.strip()
        )
        return completed.returncode == 0, f"{summary}\n{verification}"

    def validate_creator_build() -> tuple[bool, str]:
        resources = root / "apps/armi-runtime/build/creator-web-resources"
        required = (
            resources / "manifest.json",
            resources / "static/index.html",
            resources / "static/.vite/manifest.json",
        )
        missing = tuple(
            path.relative_to(resources).as_posix()
            for path in required
            if not path.is_file()
        )
        assets = tuple((resources / "static/assets").glob("*"))
        valid = not missing and any(path.suffix == ".js" for path in assets)
        details = (
            f"missing: {', '.join(missing)}" if missing else f"assets: {len(assets)}"
        )
        return valid, details

    def py(*arguments: str) -> tuple[str, ...]:
        return (str(venv_python), *arguments)

    def node_command(relative: str, *arguments: str) -> tuple[str, ...]:
        return (str(node), str(node_modules / relative), *arguments)

    common_python = (venv_python,)
    common_node = (node,)
    return {
        "QLT-LOCKED": Gate(
            "QLT-LOCKED",
            py("-B", "tools/check_locked_environment.py"),
            root,
            common_python,
        ),
        "PY-FORMAT": Gate(
            "PY-FORMAT",
            py("-B", "-m", "ruff", "format", "--check", "."),
            root,
            common_python,
        ),
        "PY-LINT": Gate(
            "PY-LINT",
            py("-B", "-m", "ruff", "check", "."),
            root,
            common_python,
        ),
        "PY-TYPE": Gate(
            "PY-TYPE",
            (str(node), str(pyright), "--project", str(root / "pyrightconfig.json")),
            root,
            (node, pyright),
        ),
        "PY-TEST": Gate(
            "PY-TEST",
            py("-B", "-m", "pytest"),
            root,
            common_python,
        ),
        "ARC-SURFACE": Gate(
            "ARC-SURFACE",
            py("-B", "tools/check_workspace_boundaries.py"),
            root,
            common_python,
        ),
        "SEC-REPOSITORY": Gate(
            "SEC-REPOSITORY",
            py("-B", "tools/check_repository_hygiene.py"),
            root,
            common_python,
        ),
        "WEB-FORMAT": Gate(
            "WEB-FORMAT",
            node_command(
                "prettier/bin/prettier.cjs",
                "--check",
                "package.json",
                "index.html",
                "tsconfig.json",
                "vite.config.ts",
                "vitest.config.ts",
                "src",
            ),
            creator,
            common_node,
        ),
        "WEB-LINT": Gate(
            "WEB-LINT",
            node_command("oxlint/bin/oxlint", "--deny-warnings", "src"),
            creator,
            common_node,
        ),
        "WEB-TYPE": Gate(
            "WEB-TYPE",
            node_command(
                "typescript/bin/tsc",
                "--project",
                "tsconfig.json",
                "--noEmit",
            ),
            creator,
            common_node,
        ),
        "WEB-TEST": Gate(
            "WEB-TEST",
            node_command(
                "vitest/vitest.mjs",
                "run",
                "--config",
                "vitest.config.ts",
            ),
            creator,
            common_node,
        ),
        "BUILD-PY": Gate(
            "BUILD-PY",
            (
                str(uv),
                "build",
                "--all-packages",
                "--offline",
                "--no-create-gitignore",
                "--out-dir",
                str(python_dist),
            ),
            root,
            (uv,),
            prepare=lambda: safe_remove_output(python_dist, quality_root),
            validate=validate_python_build,
        ),
        "BUILD-WEB": Gate(
            "BUILD-WEB",
            py(
                "-B",
                "tools/build_creator_web.py",
                "--tool-root",
                str(tool_root),
            ),
            root,
            (node, managed_python, venv_python),
            validate=validate_creator_build,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path)
    parser.add_argument("--gate", action="append", choices=GATE_ORDER)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    tool_root = args.tool_root.resolve() if args.tool_root else root / ".armi-tools"
    selected = tuple(args.gate or (GATE_ORDER if args.release else FAST_GATE_ORDER))
    available = commands(root, tool_root)
    environment = os.environ.copy()
    environment.update(
        {
            "ARMI_TOOL_ROOT": str(tool_root),
            "UV_OFFLINE": "1",
            "NPM_CONFIG_OFFLINE": "true",
            "PLAYWRIGHT_BROWSERS_PATH": str(tool_root / "installs/playwright"),
        }
    )
    results: list[GateResult] = []
    for gate_id in selected:
        result = run_gate(available[gate_id], environment)
        results.append(result)
        print(f"{result.gate_id}\t{result.status}\texit={result.exit_code}")
        if result.output:
            for line in result.output.splitlines():
                print(f"  {line}")
    exit_code = aggregate_exit_code(results)
    print(f"QUALITY\t{'pass' if exit_code == 0 else 'fail'}\texit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
