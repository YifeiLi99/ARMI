"""Validate the M0 workspace metadata and static import boundaries."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_VERSION = "0.0.0"
PYTHON_RANGE = ">=3.14,<3.15"
BUILD_REQUIREMENTS = ["uv_build>=0.11.33,<0.12"]
BUILD_BACKEND = "uv_build"


@dataclass(frozen=True)
class Distribution:
    name: str
    module: str
    project_dir: Path
    layers: tuple[str, ...]
    dependencies: tuple[str, ...]

    @property
    def source_dir(self) -> Path:
        return self.project_dir / "src"

    @property
    def module_dir(self) -> Path:
        return self.source_dir / self.module


DISTRIBUTIONS = (
    Distribution(
        name="armi-kernel",
        module="armi_kernel",
        project_dir=Path("packages/armi-kernel"),
        layers=("domain", "application", "contracts"),
        dependencies=(),
    ),
    Distribution(
        name="armi-runtime",
        module="armi_runtime",
        project_dir=Path("apps/armi-runtime"),
        layers=("adapters", "interfaces", "workers", "composition"),
        dependencies=(
            "armi-kernel==0.0.0",
            "fastapi==0.140.13",
            "openai==2.49.0",
            "playwright==1.61.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "pydantic==2.13.4",
            "rfc8785==0.1.4",
            "uvicorn==0.51.0",
        ),
    ),
    Distribution(
        name="armi-admin",
        module="armi_admin",
        project_dir=Path("apps/armi-admin"),
        layers=("application", "mcp", "persistence", "process_control"),
        dependencies=(
            "armi-kernel==0.0.0",
            "mcp==2.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "pydantic==2.13.4",
            "rfc8785==0.1.4",
        ),
    ),
)

EXPECTED_MEMBERS = [
    distribution.project_dir.as_posix() for distribution in DISTRIBUTIONS
]
PUBLIC_KERNEL_MODULES = frozenset(
    {"armi_kernel", "armi_kernel.application", "armi_kernel.contracts"}
)
KERNEL_FORBIDDEN_TECHNOLOGY = frozenset(
    {"fastapi", "mcp", "openai", "playwright", "psycopg", "psycopg_pool"}
)
MODULE_TO_DISTRIBUTION = {
    distribution.module: distribution.name for distribution in DISTRIBUTIONS
}


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_toml(path: Path, root: Path) -> tuple[dict[str, object], list[Violation]]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream), []
    except (OSError, tomllib.TOMLDecodeError) as error:
        return {}, [
            Violation(
                "ARC-WORKSPACE-METADATA",
                _relative(path, root),
                1,
                f"cannot read TOML metadata: {error}",
            )
        ]


def _expect(
    violations: list[Violation],
    *,
    actual: object,
    expected: object,
    path: Path,
    root: Path,
    field: str,
) -> None:
    if actual != expected:
        violations.append(
            Violation(
                "ARC-WORKSPACE-METADATA",
                _relative(path, root),
                1,
                f"{field} must be {expected!r}, found {actual!r}",
            )
        )


def validate_workspace_metadata(root: Path) -> list[Violation]:
    """Validate the virtual root, three distributions, and Creator package."""

    violations: list[Violation] = []
    root_metadata_path = root / "pyproject.toml"
    root_metadata, errors = _load_toml(root_metadata_path, root)
    violations.extend(errors)
    root_project = root_metadata.get("project", {})
    root_tool = root_metadata.get("tool", {})
    root_groups = root_metadata.get("dependency-groups", {})
    if (
        not isinstance(root_project, dict)
        or not isinstance(root_tool, dict)
        or not isinstance(root_groups, dict)
    ):
        return violations

    root_uv = root_tool.get("uv", {})
    if not isinstance(root_uv, dict):
        root_uv = {}
    workspace = root_uv.get("workspace", {})
    if not isinstance(workspace, dict):
        workspace = {}
    for field, expected in (
        ("project.name", "armi-workspace"),
        ("project.version", WORKSPACE_VERSION),
        ("project.requires-python", PYTHON_RANGE),
        ("project.dependencies", []),
        (
            "dependency-groups.dev",
            [
                "hypothesis==6.163.0",
                "pytest==9.1.1",
                "pytest-asyncio==1.4.0",
                "ruff==0.16.0",
            ],
        ),
        ("tool.uv.package", False),
        ("tool.uv.build-constraint-dependencies", ["uv_build==0.11.33"]),
        ("tool.uv.workspace.members", EXPECTED_MEMBERS),
    ):
        actual: object
        if field.startswith("project."):
            actual = root_project.get(field.removeprefix("project."))
        elif field == "dependency-groups.dev":
            actual = root_groups.get("dev")
        elif field == "tool.uv.package":
            actual = root_uv.get("package")
        elif field == "tool.uv.build-constraint-dependencies":
            actual = root_uv.get("build-constraint-dependencies")
        else:
            actual = workspace.get("members")
        _expect(
            violations,
            actual=actual,
            expected=expected,
            path=root_metadata_path,
            root=root,
            field=field,
        )

    for distribution in DISTRIBUTIONS:
        metadata_path = root / distribution.project_dir / "pyproject.toml"
        metadata, errors = _load_toml(metadata_path, root)
        violations.extend(errors)
        project = metadata.get("project", {})
        build_system = metadata.get("build-system", {})
        tool = metadata.get("tool", {})
        if not isinstance(project, dict) or not isinstance(build_system, dict):
            continue
        expected_fields = (
            ("project.name", project.get("name"), distribution.name),
            ("project.version", project.get("version"), WORKSPACE_VERSION),
            ("project.requires-python", project.get("requires-python"), PYTHON_RANGE),
            (
                "project.dependencies",
                project.get("dependencies"),
                list(distribution.dependencies),
            ),
            (
                "build-system.requires",
                build_system.get("requires"),
                BUILD_REQUIREMENTS,
            ),
            (
                "build-system.build-backend",
                build_system.get("build-backend"),
                BUILD_BACKEND,
            ),
        )
        for field, actual, expected in expected_fields:
            _expect(
                violations,
                actual=actual,
                expected=expected,
                path=metadata_path,
                root=root,
                field=field,
            )

        if distribution.dependencies:
            sources = (
                tool.get("uv", {}).get("sources", {}) if isinstance(tool, dict) else {}
            )
            kernel_source = (
                sources.get("armi-kernel", {}) if isinstance(sources, dict) else {}
            )
            _expect(
                violations,
                actual=kernel_source,
                expected={"workspace": True},
                path=metadata_path,
                root=root,
                field="tool.uv.sources.armi-kernel",
            )

        required_package_paths = (
            distribution.module_dir / "__init__.py",
            *(
                distribution.module_dir / layer / "__init__.py"
                for layer in distribution.layers
            ),
        )
        for required_path in required_package_paths:
            if not (root / required_path).is_file():
                violations.append(
                    Violation(
                        "ARC-WORKSPACE-LAYOUT",
                        required_path.as_posix(),
                        1,
                        "required explicit package entry point is missing",
                    )
                )

    creator_path = root / "apps/armi-creator-web/package.json"
    expected_creator = {
        "name": "armi-creator-web",
        "version": WORKSPACE_VERSION,
        "private": True,
        "type": "module",
        "engines": {"node": "24.18.0"},
        "packageManager": "npm@11.16.0",
        "scripts": {
            "format:check": "prettier --check package.json tests/toolchain",
            "lint": "oxlint --deny-warnings tests/toolchain",
            "typecheck": "tsc --project tests/toolchain/tsconfig.json --noEmit",
            "test": "vitest run --config tests/toolchain/vitest.config.ts",
            "build:smoke": "vite build --config tests/toolchain/vite.config.ts",
        },
        "dependencies": {
            "@tanstack/react-query": "5.101.4",
            "react": "19.2.8",
            "react-dom": "19.2.8",
        },
        "devDependencies": {
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
        },
    }
    try:
        creator = json.loads(creator_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        violations.append(
            Violation(
                "ARC-WORKSPACE-METADATA",
                _relative(creator_path, root),
                1,
                f"cannot read Creator package metadata: {error}",
            )
        )
    else:
        _expect(
            violations,
            actual=creator,
            expected=expected_creator,
            path=creator_path,
            root=root,
            field="Creator package metadata",
        )
    return violations


def _literal_exports(
    tree: ast.Module, *, path: str
) -> tuple[frozenset[str] | None, list[Violation]]:
    assignments: list[ast.expr | None] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in statement.targets
            )
        ) or (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "__all__"
        ):
            assignments.append(statement.value)

    if len(assignments) != 1 or assignments[0] is None:
        return None, [
            Violation(
                "ARC-SURFACE-EXPORT",
                path,
                1,
                "package entry point must define __all__ exactly once as a literal",
            )
        ]

    try:
        value = ast.literal_eval(assignments[0])
    except ValueError, TypeError:
        value = None
    if not isinstance(value, (tuple, list)) or not all(
        isinstance(item, str) for item in value
    ):
        return None, [
            Violation(
                "ARC-SURFACE-EXPORT",
                path,
                getattr(assignments[0], "lineno", 1),
                "__all__ must be a literal tuple or list of names",
            )
        ]

    violations = [
        Violation(
            "ARC-SURFACE-INTERNAL",
            path,
            getattr(assignments[0], "lineno", 1),
            f"private name {item!r} cannot be exported",
        )
        for item in value
        if item.startswith("_")
    ]
    bound_names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound_names.add(statement.name)
        elif isinstance(statement, ast.Import):
            bound_names.update(
                alias.asname or alias.name.split(".", maxsplit=1)[0]
                for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            bound_names.update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name != "*"
            )
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            bound_names.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
    violations.extend(
        Violation(
            "ARC-SURFACE-EXPORT",
            path,
            getattr(assignments[0], "lineno", 1),
            f"exported name {item!r} is not explicitly bound by the entry point",
        )
        for item in value
        if item not in bound_names
    )
    return frozenset(value), violations


def _distribution_for_module(module: str) -> str | None:
    root_module = module.split(".", maxsplit=1)[0]
    return MODULE_TO_DISTRIBUTION.get(root_module)


def _has_private_segment(module: str) -> bool:
    return any(segment.startswith("_") for segment in module.split("."))


def _resolve_import_from(
    node: ast.ImportFrom, *, current_module: str, is_package: bool
) -> str:
    if node.level == 0:
        return node.module or ""
    package = current_module if is_package else current_module.rpartition(".")[0]
    relative_name = "." * node.level + (node.module or "")
    try:
        return importlib.util.resolve_name(relative_name, package)
    except ImportError, ValueError:
        return relative_name


def _check_import(
    *,
    source_distribution: str,
    source_module: str,
    imported_module: str,
    imported_names: Sequence[str],
    public_exports: Mapping[str, frozenset[str]],
    path: str,
    line: int,
) -> list[Violation]:
    violations: list[Violation] = []
    target_distribution = _distribution_for_module(imported_module)
    imported_root = imported_module.split(".", maxsplit=1)[0]

    if (
        source_distribution == "armi-kernel"
        and imported_root in KERNEL_FORBIDDEN_TECHNOLOGY
    ):
        violations.append(
            Violation(
                "ARC-SURFACE-KERNEL-TECH",
                path,
                line,
                f"Kernel cannot import technical adapter package {imported_root!r}",
            )
        )

    reverse_dependency = (
        (
            source_distribution == "armi-kernel"
            and target_distribution in {"armi-runtime", "armi-admin"}
        )
        or (
            source_distribution == "armi-runtime"
            and target_distribution == "armi-admin"
        )
        or (
            source_distribution == "armi-admin"
            and target_distribution == "armi-runtime"
        )
    )
    if reverse_dependency:
        violations.append(
            Violation(
                "ARC-SURFACE-REVERSE",
                path,
                line,
                f"{source_distribution} cannot import {target_distribution}",
            )
        )

    if source_module.startswith("armi_kernel.domain") and imported_module.startswith(
        "armi_kernel.application"
    ):
        violations.append(
            Violation(
                "ARC-SURFACE-REVERSE",
                path,
                line,
                "Domain cannot depend on Application",
            )
        )

    runtime_layer = (
        source_module.split(".")[1]
        if source_module.startswith("armi_runtime.")
        and len(source_module.split(".")) > 1
        else None
    )
    inferred_modules = [imported_module]
    inferred_modules.extend(
        f"{imported_module}.{name}"
        for name in imported_names
        if name != "*" and "." not in name
    )
    if runtime_layer in {"interfaces", "adapters", "workers"} and any(
        module.startswith("armi_runtime.composition") for module in inferred_modules
    ):
        violations.append(
            Violation(
                "ARC-SURFACE-REVERSE",
                path,
                line,
                f"armi_runtime.{runtime_layer} cannot depend on composition",
            )
        )

    crosses_distribution = (
        target_distribution is not None and target_distribution != source_distribution
    )
    if crosses_distribution and (
        _has_private_segment(imported_module)
        or any(name.startswith("_") for name in imported_names)
    ):
        violations.append(
            Violation(
                "ARC-SURFACE-INTERNAL",
                path,
                line,
                "cross-distribution imports cannot expose private modules or names",
            )
        )

    if (
        source_distribution in {"armi-runtime", "armi-admin"}
        and target_distribution == "armi-kernel"
    ):
        if imported_module not in PUBLIC_KERNEL_MODULES:
            violations.append(
                Violation(
                    "ARC-SURFACE-DEEP",
                    path,
                    line,
                    f"cross-distribution import must use an explicit Kernel entry point, not {imported_module!r}",
                )
            )
        else:
            allowed_names = public_exports.get(imported_module, frozenset())
            for name in imported_names:
                if name == "*":
                    continue
                if name not in allowed_names:
                    violations.append(
                        Violation(
                            "ARC-SURFACE-EXPORT",
                            path,
                            line,
                            f"{name!r} is not exported by {imported_module}",
                        )
                    )
    return violations


def analyze_source(
    source: str,
    *,
    module: str,
    distribution: str,
    path: str,
    is_package: bool = False,
    public_exports: Mapping[str, frozenset[str]] | None = None,
) -> list[Violation]:
    """Analyze one source string; exposed for deterministic negative tests."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [
            Violation(
                "ARC-SURFACE-SYNTAX",
                path,
                error.lineno or 1,
                error.msg,
            )
        ]

    exports = public_exports or {}
    violations: list[Violation] = []
    if is_package:
        _, export_errors = _literal_exports(tree, path=path)
        violations.extend(export_errors)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                violations.extend(
                    _check_import(
                        source_distribution=distribution,
                        source_module=module,
                        imported_module=alias.name,
                        imported_names=(),
                        public_exports=exports,
                        path=path,
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(
                node, current_module=module, is_package=is_package
            )
            names = tuple(alias.name for alias in node.names)
            if "*" in names:
                violations.append(
                    Violation(
                        "ARC-SURFACE-STAR",
                        path,
                        node.lineno,
                        "star imports are forbidden",
                    )
                )
            violations.extend(
                _check_import(
                    source_distribution=distribution,
                    source_module=module,
                    imported_module=imported_module,
                    imported_names=names,
                    public_exports=exports,
                    path=path,
                    line=node.lineno,
                )
            )
    return violations


def _module_identity(path: Path, source_dir: Path) -> tuple[str, bool]:
    relative = path.relative_to(source_dir)
    if relative.name == "__init__.py":
        return ".".join(relative.parts[:-1]), True
    return ".".join((*relative.parts[:-1], relative.stem)), False


def _parse_python(path: Path, root: Path) -> tuple[ast.Module | None, list[Violation]]:
    relative = _relative(path, root)
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source, filename=relative), []
    except (OSError, UnicodeError, SyntaxError) as error:
        line = error.lineno if isinstance(error, SyntaxError) and error.lineno else 1
        return None, [
            Violation(
                "ARC-SURFACE-SYNTAX", relative, line, f"cannot parse source: {error}"
            )
        ]


def validate_source_boundaries(root: Path) -> list[Violation]:
    """Scan production Python sources and explicit package surfaces."""

    violations: list[Violation] = []
    public_exports: dict[str, frozenset[str]] = {}
    public_paths = {
        "armi_kernel": root / "packages/armi-kernel/src/armi_kernel/__init__.py",
        "armi_kernel.application": root
        / "packages/armi-kernel/src/armi_kernel/application/__init__.py",
        "armi_kernel.contracts": root
        / "packages/armi-kernel/src/armi_kernel/contracts/__init__.py",
    }
    for module, path in public_paths.items():
        tree, errors = _parse_python(path, root)
        violations.extend(errors)
        if tree is not None:
            exports, export_errors = _literal_exports(tree, path=_relative(path, root))
            violations.extend(export_errors)
            if exports is not None:
                public_exports[module] = exports

    for distribution in DISTRIBUTIONS:
        source_dir = root / distribution.source_dir
        for path in sorted(source_dir.rglob("*.py")):
            tree, errors = _parse_python(path, root)
            violations.extend(errors)
            if tree is None:
                continue
            relative = _relative(path, root)
            module, is_package = _module_identity(path, source_dir)
            source = path.read_text(encoding="utf-8")
            violations.extend(
                analyze_source(
                    source,
                    module=module,
                    distribution=distribution.name,
                    path=relative,
                    is_package=is_package,
                    public_exports=public_exports,
                )
            )
    return violations


def check_repository(root: Path) -> list[Violation]:
    violations = validate_workspace_metadata(root)
    violations.extend(validate_source_boundaries(root))
    return sorted(set(violations))


def exit_code_for(violations: Iterable[Violation]) -> int:
    return 1 if any(True for _ in violations) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate ARMI workspace and import boundaries."
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of tools/)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    violations = check_repository(root)
    if violations:
        for violation in violations:
            print(violation.render())
        print(f"workspace-boundaries: fail ({len(violations)} violation(s))")
        return 1
    source_count = sum(
        1
        for distribution in DISTRIBUTIONS
        for _ in (root / distribution.source_dir).rglob("*.py")
    )
    print(
        "workspace-boundaries: pass "
        f"({len(DISTRIBUTIONS)} distributions, {source_count} Python source files)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
