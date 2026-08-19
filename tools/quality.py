"""Run fast development checks, or the full offline release gate on request."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
    "WHEEL-INSTALL",
    "PG-INTEGRATION",
    "BROWSER-CONTRACT",
    "CREATOR-SYSTEM",
)
FAST_GATE_ORDER = (
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
)
RELEASE_GATE_ORDER = (*FAST_GATE_ORDER, "BUILD-WEB", "BUILD-PY", "WHEEL-INSTALL")
SYSTEM_GATE_ORDER = (
    *RELEASE_GATE_ORDER,
    "PG-INTEGRATION",
    "BROWSER-CONTRACT",
    "CREATOR-SYSTEM",
)


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    exit_code: int
    output: str
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Gate:
    gate_id: str
    command: tuple[str, ...]
    cwd: Path
    required_paths: tuple[Path, ...] = ()
    prepare: Callable[[], None] | None = None
    validate: Callable[[], tuple[bool, str]] | None = None
    blocked_exit_codes: tuple[int, ...] = ()
    workers: int = 1


@dataclass(frozen=True)
class ScheduleOutcome:
    results: tuple[GateResult, ...]
    interrupted: bool = False


def aggregate_exit_code(results: Iterable[GateResult]) -> int:
    statuses = {result.status for result in results}
    if "fail" in statuses:
        return 1
    if "blocked" in statuses:
        return 2
    return 0


def default_jobs() -> int:
    return min(8, max(2, (os.cpu_count() or 1) // 3))


def parse_jobs(value: str) -> int:
    jobs = int(value)
    if not 1 <= jobs <= 32:
        raise argparse.ArgumentTypeError("jobs must be between 1 and 32")
    return jobs


def pytest_worker_arguments(workers: int) -> tuple[str, ...]:
    if workers == 1:
        return ()
    return (
        "-n",
        str(workers),
        "--dist",
        "worksteal",
        "--max-worker-restart=0",
    )


def safe_remove_output(path: Path, quality_root: Path) -> None:
    resolved = path.resolve()
    allowed = quality_root.resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise RuntimeError(f"unsafe quality output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def run_gate(gate: Gate, environment: dict[str, str]) -> GateResult:
    started = time.perf_counter()

    def finish(status: str, exit_code: int, output: str) -> GateResult:
        return GateResult(
            gate.gate_id,
            status,
            exit_code,
            output,
            time.perf_counter() - started,
        )

    missing = [path for path in gate.required_paths if not path.is_file()]
    if missing:
        names = ", ".join(path.name for path in missing)
        return finish("blocked", 2, f"missing required tool: {names}")
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
        return finish("blocked", 2, str(error))
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    if completed.returncode in gate.blocked_exit_codes:
        return finish("blocked", completed.returncode, output)
    if completed.returncode != 0:
        return finish("fail", completed.returncode, output)
    if gate.validate:
        valid, validation_output = gate.validate()
        if validation_output:
            output = "\n".join(item for item in (output, validation_output) if item)
        if not valid:
            return finish("fail", 1, output)
    return finish("pass", 0, output)


_GATE_DEPENDENCIES = {
    "BUILD-PY": ("BUILD-WEB",),
    "WHEEL-INSTALL": ("BUILD-PY",),
    "BROWSER-CONTRACT": ("BUILD-WEB",),
    "CREATOR-SYSTEM": ("WHEEL-INSTALL",),
}


def selected_gate_dependencies(selected: Iterable[str]) -> dict[str, tuple[str, ...]]:
    ordered = tuple(dict.fromkeys(selected))
    selected_set = frozenset(ordered)
    dependencies: dict[str, tuple[str, ...]] = {}
    for gate_id in ordered:
        declared = _GATE_DEPENDENCIES.get(gate_id, ())
        current = tuple(item for item in declared if item in selected_set)
        if gate_id != "QLT-LOCKED" and "QLT-LOCKED" in selected_set:
            current = ("QLT-LOCKED", *current)
        dependencies[gate_id] = current
    return dependencies


def schedule_gates(
    selected: Iterable[str],
    available: dict[str, Gate],
    environment: dict[str, str],
    *,
    jobs: int,
    runner: Callable[[Gate, dict[str, str]], GateResult] = run_gate,
) -> ScheduleOutcome:
    ordered = tuple(dict.fromkeys(selected))
    dependencies = selected_gate_dependencies(ordered)
    pending = set(ordered)
    results: dict[str, GateResult] = {}
    running: dict[Future[GateResult], str] = {}
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="armi-quality")
    try:
        while pending or running:
            for gate_id in ordered:
                if gate_id not in pending:
                    continue
                prerequisites = dependencies[gate_id]
                if not all(item in results for item in prerequisites):
                    continue
                unsuccessful = tuple(
                    item for item in prerequisites if results[item].status != "pass"
                )
                if unsuccessful:
                    reason = ", ".join(
                        f"{item}={results[item].status}" for item in unsuccessful
                    )
                    results[gate_id] = GateResult(
                        gate_id,
                        "skipped",
                        0,
                        f"prerequisite did not pass: {reason}",
                    )
                    pending.remove(gate_id)
                    continue
                if len(running) >= jobs:
                    break
                running[executor.submit(runner, available[gate_id], environment)] = (
                    gate_id
                )
                pending.remove(gate_id)

            if not running:
                if pending:
                    unresolved = ", ".join(sorted(pending))
                    raise RuntimeError(f"quality gate dependency cycle: {unresolved}")
                break

            try:
                completed, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
            except KeyboardInterrupt:
                interrupted = True
                break
            for future in completed:
                gate_id = running.pop(future)
                try:
                    results[gate_id] = future.result()
                except KeyboardInterrupt:
                    results[gate_id] = GateResult(
                        gate_id,
                        "fail",
                        1,
                        "quality gate was interrupted",
                    )
                    interrupted = True
                except Exception as error:
                    results[gate_id] = GateResult(
                        gate_id,
                        "fail",
                        1,
                        f"gate runner raised {type(error).__name__}: {error}",
                    )
            if interrupted:
                break

        if interrupted:
            for gate_id in ordered:
                if gate_id in pending:
                    results[gate_id] = GateResult(
                        gate_id,
                        "skipped",
                        0,
                        "quality run was interrupted before this gate started",
                    )
            pending.clear()
            wait(tuple(running))
            for future, gate_id in running.items():
                try:
                    results[gate_id] = future.result()
                except KeyboardInterrupt:
                    results[gate_id] = GateResult(
                        gate_id,
                        "fail",
                        1,
                        "gate runner was interrupted: KeyboardInterrupt",
                    )
                except Exception as error:
                    results[gate_id] = GateResult(
                        gate_id,
                        "fail",
                        1,
                        f"gate runner raised {type(error).__name__}: {error}",
                    )
    finally:
        executor.shutdown(wait=True, cancel_futures=False)
    return ScheduleOutcome(tuple(results[gate_id] for gate_id in ordered), interrupted)


def workspace_distribution_names(root: Path) -> tuple[str, ...]:
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    members = cast(list[str], workspace["tool"]["uv"]["workspace"]["members"])
    names: list[str] = []
    for member in members:
        project = cast(
            dict[str, Any],
            tomllib.loads(
                (root / member / "pyproject.toml").read_text(encoding="utf-8")
            )["project"],
        )
        names.append(re.sub(r"[-_.]+", "_", cast(str, project["name"])))
    return tuple(sorted(names))


def commands(root: Path, tool_root: Path, jobs: int) -> dict[str, Gate]:
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
    wheel_venv = quality_root / "wheel-venv"
    chromium = tool_root / "installs/playwright/chromium-1228/chrome-win64/chrome.exe"
    creator_resources = root / "apps/armi-runtime/build/creator-web-resources"

    def validate_python_build() -> tuple[bool, str]:
        artifacts = sorted(
            path.name for path in python_dist.glob("*") if path.is_file()
        )
        expected = workspace_distribution_names(root)
        wheels = [name for name in artifacts if name.endswith(".whl")]
        source_distributions = [name for name in artifacts if name.endswith(".tar.gz")]
        valid = (
            len(artifacts) == len(expected) * 2
            and len(wheels) == len(expected)
            and len(source_distributions) == len(expected)
            and all(
                any(name.startswith(f"{prefix}-") for name in wheels)
                for prefix in expected
            )
            and all(
                any(name.startswith(f"{prefix}-") for name in source_distributions)
                for prefix in expected
            )
        )
        summary = f"python build artifacts: {', '.join(artifacts)}"
        if not valid:
            return False, summary
        runtime_wheels = sorted(
            path for path in python_dist.glob("armi_runtime-*.whl") if path.is_file()
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
            py(
                "-B",
                "-m",
                "pytest",
                "-m",
                "not postgresql",
                *pytest_worker_arguments(min(8, jobs)),
            ),
            root,
            common_python,
            workers=min(8, jobs),
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
        "WHEEL-INSTALL": Gate(
            "WHEEL-INSTALL",
            (
                str(managed_python),
                "-B",
                "tools/verify_wheel_install.py",
                "--root",
                str(root),
                "--tool-root",
                str(tool_root),
                "--dist",
                str(python_dist),
                "--venv",
                str(wheel_venv),
                "--dependency-environment",
                str(root / ".venv"),
            ),
            root,
            (
                managed_python,
                uv,
                venv_python,
                root / "tools/verify_wheel_install.py",
                root / "tools/validate_wheel_environment.py",
            ),
            prepare=lambda: safe_remove_output(wheel_venv, quality_root),
            blocked_exit_codes=(2,),
        ),
        "PG-INTEGRATION": Gate(
            "PG-INTEGRATION",
            py(
                "-B",
                "tools/run_postgresql_integration.py",
                "--root",
                str(root),
                "--workers",
                str(min(4, jobs)),
            ),
            root,
            (venv_python, root / "tools/run_postgresql_integration.py"),
            blocked_exit_codes=(2,),
            workers=min(4, jobs),
        ),
        "BROWSER-CONTRACT": Gate(
            "BROWSER-CONTRACT",
            py(
                "-B",
                "tools/verify_creator_browser.py",
                "--root",
                str(root),
                "--tool-root",
                str(tool_root),
            ),
            root,
            (venv_python, chromium, root / "tools/verify_creator_browser.py"),
            blocked_exit_codes=(2,),
        ),
        "CREATOR-SYSTEM": Gate(
            "CREATOR-SYSTEM",
            py(
                "-B",
                "tools/run_postgresql_integration.py",
                "--root",
                str(root),
                "--creator-system-entry-point",
                str(wheel_venv / "Scripts/armi.exe"),
                "--creator-system-resources",
                str(creator_resources),
                "--creator-system-chromium",
                str(chromium),
            ),
            root,
            (
                venv_python,
                chromium,
                wheel_venv / "Scripts/armi.exe",
                creator_resources / "manifest.json",
                root / "tools/run_postgresql_integration.py",
            ),
            blocked_exit_codes=(2,),
        ),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        cast(Any, sys.stdout).reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path)
    parser.add_argument("--jobs", type=parse_jobs, default=default_jobs())
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--gate", action="append", choices=GATE_ORDER)
    selection.add_argument("--release", action="store_true")
    selection.add_argument("--system", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    tool_root = args.tool_root.resolve() if args.tool_root else root / ".armi-tools"
    selected = tuple(
        dict.fromkeys(
            args.gate
            or (
                SYSTEM_GATE_ORDER
                if args.system
                else RELEASE_GATE_ORDER
                if args.release
                else FAST_GATE_ORDER
            )
        )
    )
    available = commands(root, tool_root, args.jobs)
    environment = os.environ.copy()
    environment.update(
        {
            "ARMI_TOOL_ROOT": str(tool_root),
            "UV_OFFLINE": "1",
            "NPM_CONFIG_OFFLINE": "true",
            "PLAYWRIGHT_BROWSERS_PATH": str(tool_root / "installs/playwright"),
        }
    )
    started = time.perf_counter()
    outcome = schedule_gates(
        selected,
        available,
        environment,
        jobs=args.jobs,
    )
    results = outcome.results
    for result in results:
        workers = available[result.gate_id].workers
        print(
            f"{result.gate_id}\t{result.status}\texit={result.exit_code}"
            f"\tduration={result.duration_seconds:.2f}s\tworkers={workers}"
        )
        if result.output:
            for line in result.output.splitlines():
                print(f"  {line}")
    exit_code = 1 if outcome.interrupted else aggregate_exit_code(results)
    status = "pass" if exit_code == 0 else "blocked" if exit_code == 2 else "fail"
    duration = time.perf_counter() - started
    print(
        f"QUALITY\t{status}\texit={exit_code}\tduration={duration:.2f}s"
        f"\tjobs={args.jobs}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
