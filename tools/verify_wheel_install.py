"""Install every workspace wheel into a clean offline environment and smoke it."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


def _run(
    command: Sequence[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


@dataclass(frozen=True, slots=True)
class WorkspaceDistribution:
    name: str
    module: str
    requirements: tuple[str, ...]


def _workspace_distributions(root: Path) -> tuple[WorkspaceDistribution, ...]:
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    members = cast(list[str], workspace["tool"]["uv"]["workspace"]["members"])
    distributions: list[WorkspaceDistribution] = []
    for member in members:
        metadata = tomllib.loads(
            (root / member / "pyproject.toml").read_text(encoding="utf-8")
        )
        project = cast(dict[str, Any], metadata["project"])
        name = cast(str, project["name"])
        distributions.append(
            WorkspaceDistribution(
                name=name,
                module=re.sub(r"[-_.]+", "_", name),
                requirements=tuple(cast(list[str], project.get("dependencies", []))),
            )
        )
    return tuple(sorted(distributions, key=lambda item: item.name))


def _link_or_copy(source: str, target: str) -> str:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return target


def _safe_dependency_path_hook(path: Path) -> bool:
    if path.name.casefold() != "pywin32.pth":
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("import "):
            if line != "import pywin32_bootstrap":
                return False
            continue
        candidate = Path(line)
        if candidate.is_absolute() or ".." in candidate.parts:
            return False
    return True


def snapshot_locked_dependencies(
    dependency_site: Path,
    wheel_site: Path,
    workspace_modules: frozenset[str],
) -> None:
    """Create a local dependency snapshot without executing editable path hooks."""

    for source in dependency_site.iterdir():
        folded = source.name.casefold()
        normalized = re.sub(r"[-_.]+", "_", folded)
        if (
            (
                source.suffix.casefold() == ".pth"
                and not _safe_dependency_path_hook(source)
            )
            or source.suffix.casefold() == ".egg-link"
            or folded.startswith("__editable__")
            or folded.startswith("_editable_impl_armi_")
            or normalized in workspace_modules
            or (
                folded.startswith("armi_")
                and folded.endswith((".dist-info", ".egg-info"))
            )
        ):
            continue
        if source.is_symlink():
            raise OSError(
                f"dependency snapshot contains a symbolic link: {source.name}"
            )
        target = wheel_site / source.name
        if source.is_dir():
            linked = next(
                (item for item in source.rglob("*") if item.is_symlink()), None
            )
            if linked is not None:
                raise OSError(
                    "dependency snapshot contains a symbolic link: "
                    f"{linked.relative_to(dependency_site)}"
                )
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                copy_function=_link_or_copy,
            )
        elif source.is_file():
            _link_or_copy(str(source), str(target))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--dependency-environment", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    tool_root = args.tool_root.resolve()
    dist = args.dist.resolve()
    venv = args.venv.resolve()
    dependency_environment = args.dependency_environment.resolve()
    managed_python = (
        tool_root / "installs/python/cpython-3.14.6-windows-x86_64-none/python.exe"
    )
    uv = tool_root / "installs/uv/0.11.33/uv.exe"
    if not managed_python.is_file() or not uv.is_file():
        print(
            "WHEEL-INSTALL-TOOL: managed Python or uv is unavailable", file=sys.stderr
        )
        return 2
    wheels = tuple(sorted(dist.glob("*.whl")))
    distributions = _workspace_distributions(root)
    modules = tuple(item.module for item in distributions)
    if len(wheels) != len(distributions):
        print(
            "WHEEL-INSTALL-INVENTORY: "
            f"expected {len(distributions)} wheels, found {len(wheels)}",
            file=sys.stderr,
        )
        return 1
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
    }
    environment.update(
        {
            "UV_OFFLINE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    created = _run(
        (str(managed_python), "-m", "venv", str(venv)),
        cwd=root,
        environment=environment,
    )
    if created.returncode != 0:
        print(created.stderr or created.stdout, file=sys.stderr)
        return 1
    python = venv / "Scripts/python.exe"
    dependency_site = dependency_environment / "Lib/site-packages"
    if not dependency_site.is_dir():
        print(
            "WHEEL-INSTALL-DEPS: locked dependency environment is absent",
            file=sys.stderr,
        )
        return 2
    wheel_site = venv / "Lib/site-packages"
    try:
        snapshot_locked_dependencies(
            dependency_site,
            wheel_site,
            frozenset(modules),
        )
    except OSError as error:
        print(f"WHEEL-INSTALL-DEPS: {error}", file=sys.stderr)
        return 2
    installed = _run(
        (
            str(uv),
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(python),
            *(str(wheel) for wheel in wheels),
        ),
        cwd=venv,
        environment=environment,
    )
    if installed.returncode != 0:
        print(installed.stderr or installed.stdout, file=sys.stderr)
        return 1
    contract_path = venv / "wheel-contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "distributions": [
                    {
                        "name": item.name,
                        "module": item.module,
                        "requirements": item.requirements,
                    }
                    for item in distributions
                ],
                "forbidden_paths": [
                    str(dependency_environment),
                    *(
                        str((root / member).resolve())
                        for member in ("apps", "modules", "packages")
                    ),
                ],
                "wheel_site": str(wheel_site.resolve()),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    imports = _run(
        (
            str(python),
            "-B",
            str(root / "tools/validate_wheel_environment.py"),
            "--contract",
            str(contract_path),
        ),
        cwd=venv,
        environment=environment,
    )
    if imports.returncode != 0:
        print(imports.stderr or imports.stdout, file=sys.stderr)
        return 1
    for entrypoint in ("armi", "armi-codex-runner", "armi-admin-mcp"):
        executable = venv / "Scripts" / f"{entrypoint}.exe"
        if not executable.is_file():
            print(f"WHEEL-INSTALL-ENTRYPOINT: missing {entrypoint}", file=sys.stderr)
            return 1
        help_result = _run(
            (str(executable), "--help"), cwd=venv, environment=environment
        )
        if help_result.returncode != 0 or "usage:" not in help_result.stdout.lower():
            print(
                f"WHEEL-INSTALL-HELP: {entrypoint}\n"
                f"{help_result.stdout}\n{help_result.stderr}",
                file=sys.stderr,
            )
            return 1
    print(f"wheel-install: pass ({len(modules)} imports, 3 entry points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
