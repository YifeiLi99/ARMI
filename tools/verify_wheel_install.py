"""Install every workspace wheel into a clean offline environment and smoke it."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
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


def _distribution_modules(root: Path) -> tuple[str, ...]:
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    members = cast(list[str], workspace["tool"]["uv"]["workspace"]["members"])
    modules: list[str] = []
    for member in members:
        metadata = tomllib.loads(
            (root / member / "pyproject.toml").read_text(encoding="utf-8")
        )
        name = cast(str, cast(dict[str, Any], metadata["project"])["name"])
        modules.append(re.sub(r"[-_.]+", "_", name))
    return tuple(sorted(modules))


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
    modules = _distribution_modules(root)
    if len(wheels) != len(modules):
        print(
            f"WHEEL-INSTALL-INVENTORY: expected {len(modules)} wheels, found {len(wheels)}",
            file=sys.stderr,
        )
        return 1
    environment = dict(os.environ)
    environment.update({"UV_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
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
    (wheel_site / "armi-locked-dependencies.pth").write_text(
        f"import site; site.addsitedir({str(dependency_site)!r})\n",
        encoding="utf-8",
        newline="\n",
    )
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
        cwd=root,
        environment=environment,
    )
    if installed.returncode != 0:
        print(installed.stderr or installed.stdout, file=sys.stderr)
        return 1
    imports = _run(
        (
            str(python),
            "-B",
            "-c",
            "import importlib, pathlib; "
            f"root = pathlib.Path({str(wheel_site)!r}).resolve(); "
            f"modules = {modules!r}; "
            "loaded = [importlib.import_module(name) for name in modules]; "
            "assert all(root in pathlib.Path(item.__file__).resolve().parents "
            "for item in loaded)",
        ),
        cwd=root,
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
            (str(executable), "--help"), cwd=root, environment=environment
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
