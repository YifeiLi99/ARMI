"""Validate the M0 workspace metadata and static import boundaries."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from tools.schema_ownership import (
        TABLE_OWNERSHIP,
        ownership_registry_errors,
        scan_repository_foreign_table_accesses,
    )
except ModuleNotFoundError:  # Direct execution places tools/ first on sys.path.
    from schema_ownership import (
        TABLE_OWNERSHIP,
        ownership_registry_errors,
        scan_repository_foreign_table_accesses,
    )

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
        dependencies=("pyyaml==6.0.3",),
    ),
    Distribution(
        name="armi-artifact-store",
        module="armi_artifact_store",
        project_dir=Path("packages/armi-artifact-store"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-postgresql-contract",
        module="armi_postgresql_contract",
        project_dir=Path("packages/armi-postgresql-contract"),
        layers=(),
        dependencies=(),
    ),
    Distribution(
        name="armi-channel-napcat",
        module="armi_channel_napcat",
        project_dir=Path("packages/armi-channel-napcat"),
        layers=(),
        dependencies=("httpx==0.28.1",),
    ),
    Distribution(
        name="armi-adapter-qq",
        module="armi_adapter_qq",
        project_dir=Path("packages/armi-adapter-qq"),
        layers=(),
        dependencies=(
            "armi-channel-napcat==0.0.0",
            "armi-effect==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-perception==0.0.0",
            "fastapi==0.140.13",
        ),
    ),
    Distribution(
        name="armi-runtime-foundation",
        module="armi_runtime_foundation",
        project_dir=Path("packages/armi-runtime-foundation"),
        layers=(),
        dependencies=("armi-kernel==0.0.0",),
    ),
    Distribution(
        name="armi-capability",
        module="armi_capability",
        project_dir=Path("modules/capability"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-relationship",
        module="armi_relationship",
        project_dir=Path("modules/relationship"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "pydantic==2.13.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-memory",
        module="armi_memory",
        project_dir=Path("modules/memory"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-sleep",
        module="armi_sleep",
        project_dir=Path("modules/sleep"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-activity",
        module="armi_activity",
        project_dir=Path("modules/activity"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-material",
        module="armi_material",
        project_dir=Path("modules/material"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-subject-state",
        module="armi_subject_state",
        project_dir=Path("modules/subject-state"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-mood",
        module="armi_mood",
        project_dir=Path("modules/mood"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-prompt",
        module="armi_prompt",
        project_dir=Path("modules/prompt"),
        layers=(),
        dependencies=(
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-evidence",
        module="armi_evidence",
        project_dir=Path("modules/evidence"),
        layers=(),
        dependencies=("armi-runtime-foundation==0.0.0",),
    ),
    Distribution(
        name="armi-interaction",
        module="armi_interaction",
        project_dir=Path("modules/interaction"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-evidence==0.0.0",
            "armi-kernel==0.0.0",
            "armi-attention==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-subject-state==0.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-attention",
        module="armi_attention",
        project_dir=Path("modules/attention"),
        layers=(),
        dependencies=(
            "armi-activity==0.0.0",
            "armi-kernel==0.0.0",
            "armi-material==0.0.0",
            "armi-relationship==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-sleep==0.0.0",
            "armi-subject-state==0.0.0",
        ),
    ),
    Distribution(
        name="armi-context",
        module="armi_context",
        project_dir=Path("modules/context"),
        layers=(),
        dependencies=(
            "armi-activity==0.0.0",
            "armi-artifact-store==0.0.0",
            "armi-capability==0.0.0",
            "armi-codex==0.0.0",
            "armi-effect==0.0.0",
            "armi-evidence==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-material==0.0.0",
            "armi-memory==0.0.0",
            "armi-mood==0.0.0",
            "armi-attention==0.0.0",
            "armi-prompt==0.0.0",
            "armi-relationship==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-sleep==0.0.0",
            "armi-subject-state==0.0.0",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-expression",
        module="armi_expression",
        project_dir=Path("modules/expression"),
        layers=(),
        dependencies=(
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-relationship==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-effect",
        module="armi_effect",
        project_dir=Path("modules/effect"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-capability==0.0.0",
            "armi-data-rights==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-web-observation",
        module="armi_web_observation",
        project_dir=Path("modules/web-observation"),
        layers=(),
        dependencies=(
            "armi-evidence==0.0.0",
            "armi-kernel==0.0.0",
            "armi-attention==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "httpx==0.28.1",
            "openai==2.49.0",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-codex",
        module="armi_codex",
        project_dir=Path("modules/codex"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-effect==0.0.0",
            "armi-evidence==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-attention==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "openai-codex==0.144.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-data-rights",
        module="armi_data_rights",
        project_dir=Path("modules/data-rights"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-kernel==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "psycopg[binary]==3.3.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-cognition",
        module="armi_cognition",
        project_dir=Path("modules/cognition"),
        layers=(),
        dependencies=(
            "armi-activity==0.0.0",
            "armi-artifact-store==0.0.0",
            "armi-capability==0.0.0",
            "armi-codex==0.0.0",
            "armi-context==0.0.0",
            "armi-evidence==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-material==0.0.0",
            "armi-memory==0.0.0",
            "armi-mood==0.0.0",
            "armi-attention==0.0.0",
            "armi-prompt==0.0.0",
            "armi-relationship==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-sleep==0.0.0",
            "armi-subject-state==0.0.0",
            "armi-web-observation==0.0.0",
            "pydantic==2.13.4",
            "rfc8785==0.1.4",
        ),
    ),
    Distribution(
        name="armi-perception",
        module="armi_perception",
        project_dir=Path("modules/perception"),
        layers=(),
        dependencies=(
            "armi-artifact-store==0.0.0",
            "armi-evidence==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-attention==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "openpyxl==3.1.5",
            "pillow==12.3.0",
            "python-docx==1.2.0",
            "python-pptx==1.0.2",
        ),
    ),
    Distribution(
        name="armi-runtime",
        module="armi_runtime",
        project_dir=Path("apps/armi-runtime"),
        layers=("adapters", "interfaces", "workers", "composition"),
        dependencies=(
            "alembic==1.18.5",
            "armi-adapter-qq==0.0.0",
            "armi-artifact-store==0.0.0",
            "armi-capability==0.0.0",
            "armi-cognition==0.0.0",
            "armi-codex==0.0.0",
            "armi-context==0.0.0",
            "armi-data-rights==0.0.0",
            "armi-evidence==0.0.0",
            "armi-effect==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-attention==0.0.0",
            "armi-perception==0.0.0",
            "armi-postgresql-contract==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-relationship==0.0.0",
            "armi-memory==0.0.0",
            "armi-sleep==0.0.0",
            "armi-activity==0.0.0",
            "armi-material==0.0.0",
            "armi-subject-state==0.0.0",
            "armi-web-observation==0.0.0",
            "armi-mood==0.0.0",
            "armi-prompt==0.0.0",
            "fastapi==0.140.13",
            "httpx==0.28.1",
            "openai==2.49.0",
            "openai-codex==0.144.4",
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
            "armi-artifact-store==0.0.0",
            "armi-cognition==0.0.0",
            "armi-codex==0.0.0",
            "armi-effect==0.0.0",
            "armi-evidence==0.0.0",
            "armi-expression==0.0.0",
            "armi-interaction==0.0.0",
            "armi-kernel==0.0.0",
            "armi-material==0.0.0",
            "armi-mood==0.0.0",
            "armi-attention==0.0.0",
            "armi-perception==0.0.0",
            "armi-prompt==0.0.0",
            "armi-subject-state==0.0.0",
            "armi-web-observation==0.0.0",
            "armi-runtime-foundation==0.0.0",
            "armi-postgresql-contract==0.0.0",
            "mcp==2.0.0",
            "psycopg[binary]==3.3.4",
            "psycopg-pool==3.3.1",
            "pydantic==2.13.4",
            "rfc8785==0.1.4",
        ),
    ),
)

DATA_RIGHTS_PARTICIPANT_DISTRIBUTIONS = frozenset(
    {
        "armi-activity",
        "armi-capability",
        "armi-codex",
        "armi-cognition",
        "armi-context",
        "armi-effect",
        "armi-evidence",
        "armi-expression",
        "armi-interaction",
        "armi-material",
        "armi-memory",
        "armi-mood",
        "armi-attention",
        "armi-perception",
        "armi-prompt",
        "armi-relationship",
        "armi-sleep",
        "armi-subject-state",
        "armi-web-observation",
    }
)

EXPECTED_MEMBERS = [
    distribution.project_dir.as_posix() for distribution in DISTRIBUTIONS
]
PUBLIC_KERNEL_MODULES = frozenset(
    {"armi_kernel", "armi_kernel.application", "armi_kernel.contracts"}
)
KERNEL_FORBIDDEN_TECHNOLOGY = frozenset(
    {
        "fastapi",
        "mcp",
        "openai",
        "playwright",
        "psycopg",
        "psycopg_pool",
        "pydantic",
        "rfc8785",
        "sqlalchemy",
    }
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
                "playwright==1.61.0",
                "pytest==9.1.1",
                "pytest-asyncio==1.4.0",
                "ruff==0.16.0",
            ],
        ),
        ("tool.uv.package", False),
        (
            "tool.uv.build-constraint-dependencies",
            ["hatchling==1.31.0", "uv_build==0.11.33"],
        ),
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
        runtime_distribution = distribution.name == "armi-runtime"
        expected_dependencies = distribution.dependencies
        if distribution.name == "armi-evidence":
            expected_dependencies = ("armi-kernel==0.0.0", *expected_dependencies)
        if distribution.name in DATA_RIGHTS_PARTICIPANT_DISTRIBUTIONS:
            data_rights_dependency = "armi-data-rights==0.0.0"
            if data_rights_dependency not in expected_dependencies:
                expected_dependencies = (
                    data_rights_dependency,
                    *expected_dependencies,
                )
        expected_fields = (
            ("project.name", project.get("name"), distribution.name),
            ("project.version", project.get("version"), WORKSPACE_VERSION),
            ("project.requires-python", project.get("requires-python"), PYTHON_RANGE),
            (
                "project.dependencies",
                project.get("dependencies"),
                list(expected_dependencies),
            ),
            (
                "project.scripts",
                project.get("scripts"),
                (
                    {
                        "armi": "armi_runtime.cli:main",
                        "armi-codex-runner": "armi_runtime.codex_runner_cli:main",
                    }
                    if distribution.name == "armi-runtime"
                    else (
                        {"armi-admin-mcp": "armi_admin.mcp.entrypoint:main"}
                        if distribution.name == "armi-admin"
                        else None
                    )
                ),
            ),
            (
                "build-system.requires",
                build_system.get("requires"),
                ["hatchling==1.31.0"] if runtime_distribution else BUILD_REQUIREMENTS,
            ),
            (
                "build-system.build-backend",
                build_system.get("build-backend"),
                "hatchling.build" if runtime_distribution else BUILD_BACKEND,
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

        sources = (
            tool.get("uv", {}).get("sources", {}) if isinstance(tool, dict) else {}
        )
        local_dependencies = tuple(
            candidate.name
            for candidate in DISTRIBUTIONS
            if f"{candidate.name}=={WORKSPACE_VERSION}" in distribution.dependencies
        )
        for local_dependency in local_dependencies:
            source = (
                sources.get(local_dependency, {}) if isinstance(sources, dict) else {}
            )
            _expect(
                violations,
                actual=source,
                expected={"workspace": True},
                path=metadata_path,
                root=root,
                field=f"tool.uv.sources.{local_dependency}",
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
            "dev": "vite --host 127.0.0.1 --port 5173 --strictPort",
            "format:check": "prettier --check package.json index.html tsconfig.json vite.config.ts vitest.config.ts src",
            "lint": "oxlint --deny-warnings src",
            "typecheck": "tsc --project tsconfig.json --noEmit",
            "test": "vitest run --config vitest.config.ts",
            "build": "vite build",
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
        elif isinstance(statement, ast.TypeAlias) and isinstance(
            statement.name, ast.Name
        ):
            bound_names.add(statement.name.id)
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
            and target_distribution not in {None, "armi-kernel"}
        )
        or (
            source_distribution == "armi-channel-napcat"
            and target_distribution not in {None, "armi-channel-napcat"}
        )
        or (
            source_distribution == "armi-adapter-qq"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-channel-napcat",
                "armi-adapter-qq",
                "armi-effect",
                "armi-interaction",
                "armi-perception",
            }
        )
        or (
            source_distribution == "armi-runtime"
            and target_distribution == "armi-admin"
        )
        or (
            source_distribution == "armi-admin"
            and target_distribution == "armi-runtime"
        )
        or (
            source_distribution == "armi-runtime-foundation"
            and target_distribution
            not in {None, "armi-kernel", "armi-runtime-foundation"}
        )
        or (
            source_distribution == "armi-capability"
            and target_distribution
            not in {
                None,
                "armi-capability",
                "armi-kernel",
                "armi-runtime-foundation",
            }
        )
        or (
            source_distribution == "armi-relationship"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-relationship",
            }
        )
        or (
            source_distribution == "armi-memory"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-memory",
            }
        )
        or (
            source_distribution == "armi-sleep"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-sleep",
            }
        )
        or (
            source_distribution == "armi-activity"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-activity",
            }
        )
        or (
            source_distribution == "armi-material"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-material",
            }
        )
        or (
            source_distribution == "armi-prompt"
            and target_distribution
            not in {
                None,
                "armi-kernel",
                "armi-runtime-foundation",
                "armi-prompt",
            }
        )
        or (
            source_distribution == "armi-evidence"
            and target_distribution
            not in {None, "armi-runtime-foundation", "armi-evidence"}
        )
        or (
            source_distribution == "armi-interaction"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-evidence",
                "armi-kernel",
                "armi-attention",
                "armi-runtime-foundation",
                "armi-subject-state",
                "armi-interaction",
            }
        )
        or (
            source_distribution == "armi-attention"
            and target_distribution
            not in {
                None,
                "armi-activity",
                "armi-kernel",
                "armi-material",
                "armi-attention",
                "armi-relationship",
                "armi-runtime-foundation",
                "armi-sleep",
                "armi-subject-state",
            }
        )
        or (
            source_distribution == "armi-context"
            and target_distribution
            not in {
                None,
                "armi-activity",
                "armi-artifact-store",
                "armi-capability",
                "armi-codex",
                "armi-context",
                "armi-effect",
                "armi-evidence",
                "armi-expression",
                "armi-interaction",
                "armi-kernel",
                "armi-material",
                "armi-memory",
                "armi-mood",
                "armi-attention",
                "armi-prompt",
                "armi-relationship",
                "armi-runtime-foundation",
                "armi-sleep",
                "armi-subject-state",
            }
        )
        or (
            source_distribution == "armi-expression"
            and target_distribution
            not in {
                None,
                "armi-expression",
                "armi-interaction",
                "armi-kernel",
                "armi-relationship",
                "armi-runtime-foundation",
            }
        )
        or (
            source_distribution == "armi-effect"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-capability",
                "armi-data-rights",
                "armi-effect",
                "armi-expression",
                "armi-interaction",
                "armi-kernel",
                "armi-runtime-foundation",
            }
        )
        or (
            source_distribution == "armi-web-observation"
            and target_distribution
            not in {
                None,
                "armi-evidence",
                "armi-kernel",
                "armi-attention",
                "armi-runtime-foundation",
                "armi-web-observation",
            }
        )
        or (
            source_distribution == "armi-codex"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-codex",
                "armi-effect",
                "armi-evidence",
                "armi-expression",
                "armi-interaction",
                "armi-kernel",
                "armi-attention",
                "armi-runtime-foundation",
            }
        )
        or (
            source_distribution == "armi-data-rights"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-data-rights",
                "armi-kernel",
                "armi-runtime-foundation",
            }
        )
        or (
            source_distribution == "armi-cognition"
            and target_distribution
            not in {
                None,
                "armi-activity",
                "armi-artifact-store",
                "armi-capability",
                "armi-codex",
                "armi-cognition",
                "armi-context",
                "armi-evidence",
                "armi-expression",
                "armi-interaction",
                "armi-kernel",
                "armi-material",
                "armi-memory",
                "armi-mood",
                "armi-attention",
                "armi-prompt",
                "armi-relationship",
                "armi-runtime-foundation",
                "armi-sleep",
                "armi-subject-state",
                "armi-web-observation",
            }
        )
        or (
            source_distribution == "armi-perception"
            and target_distribution
            not in {
                None,
                "armi-artifact-store",
                "armi-evidence",
                "armi-interaction",
                "armi-kernel",
                "armi-attention",
                "armi-runtime-foundation",
                "armi-perception",
            }
        )
    )
    if (
        target_distribution == "armi-data-rights"
        and source_distribution in DATA_RIGHTS_PARTICIPANT_DISTRIBUTIONS
    ):
        reverse_dependency = False
    if ".tests." in source_module and imported_module in {
        "armi_runtime.composition.candidate_validation_tool",
        "armi_runtime.composition.postgresql_test",
    }:
        reverse_dependency = False
    if source_distribution == "armi-evidence" and target_distribution == "armi-kernel":
        reverse_dependency = False
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

    public_modules = {
        "armi-kernel": PUBLIC_KERNEL_MODULES,
        "armi-channel-napcat": frozenset({"armi_channel_napcat"}),
        "armi-adapter-qq": frozenset({"armi_adapter_qq"}),
        "armi-runtime-foundation": frozenset({"armi_runtime_foundation"}),
        "armi-capability": frozenset(
            {"armi_capability", "armi_capability.api", "armi_capability.bootstrap"}
        ),
        "armi-relationship": frozenset(
            {
                "armi_relationship",
                "armi_relationship.api",
                "armi_relationship.bootstrap",
            }
        ),
        "armi-memory": frozenset(
            {"armi_memory", "armi_memory.api", "armi_memory.bootstrap"}
        ),
        "armi-sleep": frozenset(
            {"armi_sleep", "armi_sleep.api", "armi_sleep.bootstrap"}
        ),
        "armi-activity": frozenset(
            {"armi_activity", "armi_activity.api", "armi_activity.bootstrap"}
        ),
        "armi-material": frozenset(
            {"armi_material", "armi_material.api", "armi_material.bootstrap"}
        ),
        "armi-subject-state": frozenset(
            {
                "armi_subject_state",
                "armi_subject_state.api",
                "armi_subject_state.bootstrap",
            }
        ),
        "armi-mood": frozenset({"armi_mood", "armi_mood.api", "armi_mood.bootstrap"}),
        "armi-prompt": frozenset(
            {"armi_prompt", "armi_prompt.api", "armi_prompt.bootstrap"}
        ),
        "armi-evidence": frozenset(
            {"armi_evidence", "armi_evidence.api", "armi_evidence.bootstrap"}
        ),
        "armi-attention": frozenset(
            {
                "armi_attention",
                "armi_attention.api",
                "armi_attention.bootstrap",
            }
        ),
        "armi-context": frozenset(
            {"armi_context", "armi_context.api", "armi_context.bootstrap"}
        ),
        "armi-cognition": frozenset(
            {"armi_cognition", "armi_cognition.api", "armi_cognition.bootstrap"}
        ),
        "armi-expression": frozenset(
            {"armi_expression", "armi_expression.api", "armi_expression.bootstrap"}
        ),
        "armi-effect": frozenset(
            {"armi_effect", "armi_effect.api", "armi_effect.bootstrap"}
        ),
        "armi-web-observation": frozenset(
            {
                "armi_web_observation",
                "armi_web_observation.api",
                "armi_web_observation.bootstrap",
            }
        ),
        "armi-codex": frozenset(
            {"armi_codex", "armi_codex.api", "armi_codex.bootstrap"}
        ),
        "armi-data-rights": frozenset(
            {
                "armi_data_rights",
                "armi_data_rights.api",
                "armi_data_rights.bootstrap",
            }
        ),
        "armi-interaction": frozenset(
            {"armi_interaction", "armi_interaction.api", "armi_interaction.bootstrap"}
        ),
        "armi-perception": frozenset(
            {"armi_perception", "armi_perception.api", "armi_perception.bootstrap"}
        ),
    }
    if crosses_distribution and target_distribution in public_modules:
        if (
            imported_module == "armi_relationship.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "relationship bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_capability.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "capability bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module == "armi_memory.bootstrap" and not source_module.startswith(
            "armi_runtime.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "memory bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module == "armi_sleep.bootstrap" and not source_module.startswith(
            "armi_runtime.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "sleep bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_activity.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "Activity bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module == "armi_material.bootstrap" and not (
            source_module.startswith("armi_runtime.composition")
            or source_module == "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "material bootstrap is reserved for Runtime/Admin composition",
                )
            )
        if imported_module == "armi_subject_state.bootstrap" and not (
            source_module.startswith("armi_runtime.composition")
            or source_module == "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "subject-state bootstrap is reserved for Runtime/Admin composition",
                )
            )
        if imported_module == "armi_mood.bootstrap" and not (
            source_module.startswith("armi_runtime.composition")
            or source_module == "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "mood bootstrap is reserved for Runtime/Admin composition",
                )
            )
        if imported_module == "armi_prompt.bootstrap" and not (
            source_module.startswith("armi_runtime.composition")
            or source_module == "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "Prompt bootstrap is reserved for Runtime/Admin composition",
                )
            )
        if (
            imported_module == "armi_interaction.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "interaction bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_perception.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "perception bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_evidence.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "evidence bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_attention.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "Attention bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module == "armi_context.bootstrap" and not source_module.startswith(
            "armi_runtime.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "Context bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_cognition.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "cognition bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_expression.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "expression bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module == "armi_effect.bootstrap" and not (
            source_module.startswith("armi_runtime.composition")
            or source_module == "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "effect bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_web_observation.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "web-observation bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_codex.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
            and source_module != "armi_runtime.codex_runner_cli"
            and source_module != "armi_admin.composition"
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "Codex bootstrap is reserved for Runtime composition",
                )
            )
        if (
            imported_module == "armi_data_rights.bootstrap"
            and not source_module.startswith("armi_runtime.composition")
        ):
            violations.append(
                Violation(
                    "ARC-SURFACE-BOOTSTRAP",
                    path,
                    line,
                    "data-rights bootstrap is reserved for Runtime composition",
                )
            )
        if imported_module not in public_modules[target_distribution]:
            violations.append(
                Violation(
                    "ARC-SURFACE-DEEP",
                    path,
                    line,
                    "cross-distribution import must use an explicit public entry "
                    f"point, not {imported_module!r}",
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
    if module.endswith(".api") or distribution == "armi-runtime-foundation":
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                violations.append(
                    Violation(
                        "ARC-PUBLIC-ANY",
                        path,
                        node.lineno,
                        "public contracts and Runtime Foundation cannot expose Any",
                    )
                )
    if is_package and distribution in DATA_RIGHTS_PARTICIPANT_DISTRIBUTIONS:
        for node in tree.body:
            if isinstance(node, ast.Import) or (
                isinstance(node, ast.ImportFrom) and node.module != "__future__"
            ):
                violations.append(
                    Violation(
                        "ARC-PACKAGE-ROOT",
                        path,
                        node.lineno,
                        "business package roots cannot re-export implementation symbols",
                    )
                )
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
        "armi_channel_napcat": root
        / "packages/armi-channel-napcat/src/armi_channel_napcat/__init__.py",
        "armi_adapter_qq": root
        / "packages/armi-adapter-qq/src/armi_adapter_qq/__init__.py",
        "armi_runtime_foundation": root
        / "packages/armi-runtime-foundation/src/armi_runtime_foundation/__init__.py",
        "armi_capability": root / "modules/capability/src/armi_capability/__init__.py",
        "armi_capability.api": root / "modules/capability/src/armi_capability/api.py",
        "armi_capability.bootstrap": root
        / "modules/capability/src/armi_capability/bootstrap.py",
        "armi_relationship": root
        / "modules/relationship/src/armi_relationship/__init__.py",
        "armi_relationship.api": root
        / "modules/relationship/src/armi_relationship/api.py",
        "armi_relationship.bootstrap": root
        / "modules/relationship/src/armi_relationship/bootstrap.py",
        "armi_memory": root / "modules/memory/src/armi_memory/__init__.py",
        "armi_memory.api": root / "modules/memory/src/armi_memory/api.py",
        "armi_memory.bootstrap": root / "modules/memory/src/armi_memory/bootstrap.py",
        "armi_sleep": root / "modules/sleep/src/armi_sleep/__init__.py",
        "armi_sleep.api": root / "modules/sleep/src/armi_sleep/api.py",
        "armi_sleep.bootstrap": root / "modules/sleep/src/armi_sleep/bootstrap.py",
        "armi_activity": root / "modules/activity/src/armi_activity/__init__.py",
        "armi_activity.api": root / "modules/activity/src/armi_activity/api.py",
        "armi_activity.bootstrap": root
        / "modules/activity/src/armi_activity/bootstrap.py",
        "armi_material": root / "modules/material/src/armi_material/__init__.py",
        "armi_material.api": root / "modules/material/src/armi_material/api.py",
        "armi_material.bootstrap": root
        / "modules/material/src/armi_material/bootstrap.py",
        "armi_subject_state": root
        / "modules/subject-state/src/armi_subject_state/__init__.py",
        "armi_subject_state.api": root
        / "modules/subject-state/src/armi_subject_state/api.py",
        "armi_subject_state.bootstrap": root
        / "modules/subject-state/src/armi_subject_state/bootstrap.py",
        "armi_mood": root / "modules/mood/src/armi_mood/__init__.py",
        "armi_mood.api": root / "modules/mood/src/armi_mood/api.py",
        "armi_mood.bootstrap": root / "modules/mood/src/armi_mood/bootstrap.py",
        "armi_prompt": root / "modules/prompt/src/armi_prompt/__init__.py",
        "armi_prompt.api": root / "modules/prompt/src/armi_prompt/api.py",
        "armi_prompt.bootstrap": root / "modules/prompt/src/armi_prompt/bootstrap.py",
        "armi_interaction": root
        / "modules/interaction/src/armi_interaction/__init__.py",
        "armi_interaction.api": root
        / "modules/interaction/src/armi_interaction/api.py",
        "armi_interaction.bootstrap": root
        / "modules/interaction/src/armi_interaction/bootstrap.py",
        "armi_perception": root / "modules/perception/src/armi_perception/__init__.py",
        "armi_perception.api": root / "modules/perception/src/armi_perception/api.py",
        "armi_perception.bootstrap": root
        / "modules/perception/src/armi_perception/bootstrap.py",
        "armi_evidence": root / "modules/evidence/src/armi_evidence/__init__.py",
        "armi_evidence.api": root / "modules/evidence/src/armi_evidence/api.py",
        "armi_evidence.bootstrap": root
        / "modules/evidence/src/armi_evidence/bootstrap.py",
        "armi_attention": root / "modules/attention/src/armi_attention/__init__.py",
        "armi_attention.api": root / "modules/attention/src/armi_attention/api.py",
        "armi_attention.bootstrap": root
        / "modules/attention/src/armi_attention/bootstrap.py",
        "armi_context": root / "modules/context/src/armi_context/__init__.py",
        "armi_context.api": root / "modules/context/src/armi_context/api.py",
        "armi_context.bootstrap": root
        / "modules/context/src/armi_context/bootstrap.py",
        "armi_cognition": root / "modules/cognition/src/armi_cognition/__init__.py",
        "armi_cognition.api": root / "modules/cognition/src/armi_cognition/api.py",
        "armi_cognition.bootstrap": root
        / "modules/cognition/src/armi_cognition/bootstrap.py",
        "armi_expression": root / "modules/expression/src/armi_expression/__init__.py",
        "armi_expression.api": root / "modules/expression/src/armi_expression/api.py",
        "armi_expression.bootstrap": root
        / "modules/expression/src/armi_expression/bootstrap.py",
        "armi_effect": root / "modules/effect/src/armi_effect/__init__.py",
        "armi_effect.api": root / "modules/effect/src/armi_effect/api.py",
        "armi_effect.bootstrap": root / "modules/effect/src/armi_effect/bootstrap.py",
        "armi_web_observation": root
        / "modules/web-observation/src/armi_web_observation/__init__.py",
        "armi_web_observation.api": root
        / "modules/web-observation/src/armi_web_observation/api.py",
        "armi_web_observation.bootstrap": root
        / "modules/web-observation/src/armi_web_observation/bootstrap.py",
        "armi_codex": root / "modules/codex/src/armi_codex/__init__.py",
        "armi_codex.api": root / "modules/codex/src/armi_codex/api.py",
        "armi_codex.bootstrap": root / "modules/codex/src/armi_codex/bootstrap.py",
        "armi_data_rights": root
        / "modules/data-rights/src/armi_data_rights/__init__.py",
        "armi_data_rights.api": root
        / "modules/data-rights/src/armi_data_rights/api.py",
        "armi_data_rights.bootstrap": root
        / "modules/data-rights/src/armi_data_rights/bootstrap.py",
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

            if (
                distribution.name != "armi-codex"
                and ".runtime_resources.schema.alembic." not in module
                and "armi_runtime.adapters.persistence.recovery" not in module
                and not module.startswith("armi_admin.persistence.")
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:codex_task_sources|codex_verification_results|"
                    r"codex_result_sources)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-CODEX-SQL",
                        relative,
                        1,
                        "Codex task and verification writes are owned by armi-codex",
                    )
                )
            if (
                distribution.name != "armi-data-rights"
                and ".runtime_resources.schema.alembic." not in module
                and not module.startswith("armi_admin.persistence.")
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:deletion_orders|deletion_items|creator_exports)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-DATA-RIGHTS-SQL",
                        relative,
                        1,
                        "data-right orders, items and exports are owned by "
                        "armi-data-rights",
                    )
                )
            if (
                distribution.name != "armi-web-observation"
                and ".runtime_resources.schema.alembic." not in module
                and "armi_runtime.adapters.persistence.recovery" not in module
                and not module.startswith("armi_admin.persistence.")
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:web_observation_requests|observation_attempts|"
                    r"observation_tool_calls|web_research_intents|web_evidence_sources)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-WEB-OBSERVATION-SQL",
                        relative,
                        1,
                        "web observation writes are owned by armi-web-observation",
                    )
                )
            if (
                distribution.name != "armi-relationship"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE)\s+armi\."
                    r"(?:relationships|relationship_revisions|relationship_experience_links)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-RELATIONSHIP-SQL",
                        relative,
                        1,
                        "relationship table SQL is owned by armi-relationship",
                    )
                )
            if (
                distribution.name != "armi-memory"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:subjective_memories|subjective_memory_revisions|memory_relations)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-MEMORY-SQL",
                        relative,
                        1,
                        "memory table SQL is owned by armi-memory",
                    )
                )
            if (
                distribution.name != "armi-sleep"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:sleep_decisions|maintenance_sessions|"
                    r"maintenance_session_revisions|maintenance_phase_results)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-SLEEP-SQL",
                        relative,
                        1,
                        "sleep table SQL is owned by armi-sleep",
                    )
                )
            if (
                distribution.name != "armi-activity"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:activities|activity_revisions|activity_decisions)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-ACTIVITY-SQL",
                        relative,
                        1,
                        "Activity table SQL is owned by armi-activity",
                    )
                )
            if (
                distribution.name != "armi-material"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:life_materials|life_material_revisions)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-MATERIAL-SQL",
                        relative,
                        1,
                        "life-material table SQL is owned by armi-material",
                    )
                )
            if (
                distribution.name != "armi-subject-state"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:subject_component_heads|subject_component_revisions)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-SUBJECT-STATE-SQL",
                        relative,
                        1,
                        "subject-state table SQL is owned by armi-subject-state",
                    )
                )
            if (
                distribution.name != "armi-mood"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:mood_heads|mood_revisions)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-MOOD-SQL",
                        relative,
                        1,
                        "mood table SQL is owned by armi-mood",
                    )
                )
            if (
                distribution.name != "armi-prompt"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:prompt_documents|prompt_revisions)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-PROMPT-SQL",
                        relative,
                        1,
                        "Prompt table SQL is owned by armi-prompt",
                    )
                )
            if (
                distribution.name != "armi-evidence"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\bINSERT\s+INTO\s+armi\."
                    r"(?:external_evidence|experience_evidence_links)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-EVIDENCE-SQL",
                        relative,
                        1,
                        "accepted-evidence writes are owned by armi-evidence",
                    )
                )
            if (
                distribution.name != "armi-perception"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"external_content_recognition_attempts\b",
                    source,
                    re.IGNORECASE,
                )
                and "armi_data_rights._deletion_postgresql" not in module
            ):
                violations.append(
                    Violation(
                        "ARC-PERCEPTION-SQL",
                        relative,
                        1,
                        "recognition attempt SQL is owned by armi-perception",
                    )
                )
            if (
                distribution.name != "armi-context"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:cognitive_context_items|context_embedding_attempts)\b"
                    r"|\bINSERT\s+INTO\s+armi\.context_embedding_projections\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-CONTEXT-SQL",
                        relative,
                        1,
                        "Context and embedding projection writes are owned by armi-context",
                    )
                )
            if (
                distribution.name != "armi-cognition"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:cognitive_candidate_validations|"
                    r"cognitive_candidate_validation_items|"
                    r"cognitive_candidate_basis_links)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-COGNITION-SQL",
                        relative,
                        1,
                        "candidate validation writes are owned by armi-cognition",
                    )
                )
            if (
                distribution.name != "armi-cognition"
                and ".runtime_resources.schema.alembic." not in module
                and "armi_runtime.adapters.persistence.recovery" not in module
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
                    r"armi\.cognitive_attempts\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-COGNITION-SQL",
                        relative,
                        1,
                        "model attempt writes are owned by armi-cognition",
                    )
                )
            if (
                distribution.name != "armi-expression"
                and ".runtime_resources.schema.alembic." not in module
                and "armi_runtime.adapters.persistence.subject_commit" not in module
                and not module.startswith("armi_codex.")
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:action_intents|action_intent_revisions)\b"
                    r"|\bINSERT\s+INTO\s+armi\.dialogue_decisions\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-EXPRESSION-SQL",
                        relative,
                        1,
                        "expression intent writes are owned by armi-expression",
                    )
                )
            if (
                distribution.name != "armi-capability"
                and ".runtime_resources.schema.alembic." not in module
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:capability_requests|capability_request_decisions|"
                    r"capability_request_basis_links|permission_grants|capabilities)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-CAPABILITY-SQL",
                        relative,
                        1,
                        "capability and permission writes are owned by armi-capability",
                    )
                )
            if (
                distribution.name != "armi-effect"
                and ".runtime_resources.schema.alembic." not in module
                and "armi_codex._postgresql" not in module
                and "armi_data_rights._deletion_postgresql" not in module
                and not module.startswith("armi_admin.persistence.")
                and re.search(
                    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+armi\."
                    r"(?:effects|effect_outbox_items|effect_attempts|"
                    r"effect_observations|external_effect_receipts)\b",
                    source,
                    re.IGNORECASE,
                )
            ):
                violations.append(
                    Violation(
                        "ARC-EFFECT-SQL",
                        relative,
                        1,
                        "effect ledger writes are owned by armi-effect",
                    )
                )
    test_roots: list[tuple[Path, str]] = [
        (root / "tests", "workspace-tests"),
        (root / "tools", "workspace-tools"),
    ]
    test_roots.extend(
        (root / distribution.project_dir / "tests", distribution.name)
        for distribution in DISTRIBUTIONS
    )
    for source_root, source_distribution in test_roots:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            tree, errors = _parse_python(path, root)
            violations.extend(errors)
            if tree is None:
                continue
            relative_path = path.relative_to(root).with_suffix("")
            module = ".".join(relative_path.parts)
            violations.extend(
                analyze_source(
                    path.read_text(encoding="utf-8"),
                    module=module,
                    distribution=source_distribution,
                    path=_relative(path, root),
                    public_exports=public_exports,
                )
            )

    business_distributions = tuple(
        distribution
        for distribution in DISTRIBUTIONS
        if distribution.project_dir.parts[0] == "modules"
    )
    public_contract_paths = [
        root / distribution.module_dir / "api.py"
        for distribution in business_distributions
    ]
    public_contract_paths.extend(
        (root / "packages/armi-runtime-foundation/src/armi_runtime_foundation").rglob(
            "*.py"
        )
    )
    for path in sorted(public_contract_paths):
        tree, errors = _parse_python(path, root)
        violations.extend(errors)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                violations.append(
                    Violation(
                        "ARC-PUBLIC-ANY",
                        _relative(path, root),
                        node.lineno,
                        "public contracts and Runtime Foundation cannot expose Any",
                    )
                )
    for distribution in business_distributions:
        path = root / distribution.module_dir / "__init__.py"
        tree, errors = _parse_python(path, root)
        violations.extend(errors)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                violations.append(
                    Violation(
                        "ARC-PACKAGE-ROOT",
                        _relative(path, root),
                        node.lineno,
                        "business package roots cannot re-export implementation symbols",
                    )
                )
    kernel_foundation_paths = tuple(
        (root / source_root).rglob("*.py")
        for source_root in (
            Path("packages/armi-kernel/src"),
            Path("packages/armi-runtime-foundation/src"),
        )
    )
    forbidden_kernel_tokens = (
        "armi_activity",
        "armi_cognition",
        "armi_context",
        "armi_effect",
        "armi_interaction",
        "armi_attention",
        "creator-activity.v1",
        "creator-effect.v3",
        "creator-operation.v2",
    )
    for paths in kernel_foundation_paths:
        for path in paths:
            source = path.read_text(encoding="utf-8")
            for token in forbidden_kernel_tokens:
                if token in source:
                    violations.append(
                        Violation(
                            "ARC-FOUNDATION-BUSINESS",
                            _relative(path, root),
                            1,
                            f"Kernel/Foundation cannot enumerate {token!r}",
                        )
                    )

    runtime_path = root / "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
    runtime_source = runtime_path.read_text(encoding="utf-8")
    for module_name, required in {
        "relationship": (
            "relationship_module = compose_relationship_module(",
            "relationship_module.read",
            "relationship_module.commit",
        ),
        "memory": (
            "memory_module = compose_memory_module(",
            "memory_module.read",
            "memory_module.commit",
        ),
        "sleep": (
            "sleep_module = compose_sleep_module(",
            "sleep_module.read",
            "sleep_module.cognition",
            "sleep_module.commit",
            "sleep_module.maintenance",
        ),
        "Activity": (
            "activity_module = compose_activity_module(",
            "activity_module.read",
            "activity_module.cognition",
            "activity_module.commit",
        ),
        "life material": (
            "material_module = compose_material_module(",
            "material_module.read",
            "material_module.cognition",
            "material_module.commit",
            "material_module.projection",
        ),
        "subject state": (
            "subject_state_module = compose_subject_state_module()",
            "subject_state_module.read",
            "subject_state_module.cognition",
            "subject_state_module.commit",
        ),
        "mood": (
            "mood_module = compose_mood_module()",
            "mood_module.read",
            "mood_module.cognition",
            "mood_module.commit",
        ),
        "Prompt": (
            "prompt_module = compose_prompt_module(",
            "prompt_module.read",
            "prompt_module.cognition",
            "prompt_module.commit",
        ),
        "interaction": (
            "interaction_module = compose_interaction_module(",
            "interaction_module.creator_input",
            "interaction_module.creator_scenes",
            "interaction_module.scene_timeline",
            "interaction_module.other_human_input",
            "interaction_module.external_message_input",
        ),
        "perception": (
            "perception_module = compose_perception_module(",
            "perception_module.worker.run_worker()",
        ),
        "evidence": (
            "evidence_module = compose_evidence_module()",
            "evidence=evidence_module.write",
        ),
        "Attention": (
            "life_opportunity_pipeline = compose_life_opportunity_pipeline(",
            "sleep_maintenance=sleep_module.maintenance",
            "activity_read=activity_module.read",
        ),
        "Context": (
            "context_pipeline = compose_context_pipeline(",
            "context_embedding_pipeline = compose_context_embedding_pipeline(",
        ),
        "cognition": (
            "model_pipeline = compose_model_pipeline(",
            "candidate_pipeline = compose_candidate_validation_pipeline(",
        ),
        "effect": (
            "effect_pipeline = compose_effect_registration_pipeline(",
            "response_pipeline = compose_response_admission_pipeline(",
            "effect_ledger=effect_pipeline",
        ),
        "web observation": (
            "web_search_pipeline = compose_web_search_pipeline(",
            "web_research_pipeline = compose_web_research_admission_pipeline(",
        ),
        "Codex delegation": (
            "codex_pipeline = compose_codex_pipeline(",
            "codex_pipeline.task_sources",
        ),
        "data rights": (
            "data_rights_module = compose_data_rights_module(",
            "data_rights_module.exports",
            "data_rights_module.orders",
            "data_rights=data_rights_core.gate",
            "core=data_rights_core",
            "parties=interaction_module.identity",
        ),
    }.items():
        if any(item not in runtime_source for item in required):
            violations.append(
                Violation(
                    "ARC-ACTIVE-MODULE",
                    _relative(runtime_path, root),
                    1,
                    f"default Runtime composition must bind the {module_name} module",
                )
            )
    database_path = root / "apps/armi-runtime/src/armi_runtime/composition/database.py"
    database_source = database_path.read_text(encoding="utf-8")
    if "return bootstrap_expression(" not in database_source:
        violations.append(
            Violation(
                "ARC-ACTIVE-MODULE",
                _relative(database_path, root),
                1,
                "default Runtime composition must bind the expression module",
            )
        )
    if "return bootstrap_capability(" not in database_source:
        violations.append(
            Violation(
                "ARC-ACTIVE-MODULE",
                _relative(database_path, root),
                1,
                "default Runtime composition must bind the capability module",
            )
        )
    if "return bootstrap_effect_runtime(" not in database_source:
        violations.append(
            Violation(
                "ARC-ACTIVE-MODULE",
                _relative(database_path, root),
                1,
                "default Runtime composition must bind the effect module",
            )
        )
    singleton_calls = {
        "Artifact Catalog": "artifact_catalog = bootstrap_artifact_catalog()",
        "Cognition owner": "cognition_owner = bootstrap_cognition_owner()",
        "Effect owner": "effect_owner = bootstrap_effect_operation_read()",
        "Attention owner": "opportunity_owner = bootstrap_opportunity_owner()",
        "owner participant roster": "owner_roster = compose_runtime_owner_roster(",
        "Runtime UoW pool": (
            "runtime_unit_of_work_factory = compose_runtime_unit_of_work_factory("
        ),
    }
    for resource_name, construction in singleton_calls.items():
        count = runtime_source.count(construction)
        if count != 1:
            violations.append(
                Violation(
                    "ARC-ACTIVE-SINGLETON",
                    _relative(runtime_path, root),
                    1,
                    f"{resource_name} must be constructed exactly once; found {count}",
                )
            )
    for legacy_call in (
        "bootstrap_cognition_operation(",
        "bootstrap_cognition_life_records(",
        "bootstrap_interaction_cognition(",
        "bootstrap_interaction_subject_commit(",
        "bootstrap_opportunity_cognition(",
        "bootstrap_opportunity_operation(",
    ):
        if legacy_call in runtime_source:
            violations.append(
                Violation(
                    "ARC-ACTIVE-DUPLICATE",
                    _relative(runtime_path, root),
                    1,
                    f"Active Runtime must consume the shared owner aggregate, not {legacy_call}",
                )
            )
    return violations


def check_repository(root: Path) -> list[Violation]:
    violations = validate_workspace_metadata(root)
    violations.extend(validate_source_boundaries(root))
    schema_root = (
        root / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
    )
    registry_path = root / "tools/schema_ownership.py"
    violations.extend(
        Violation(
            "ARC-SQL-OWNER-REGISTRY",
            _relative(registry_path, root),
            1,
            error,
        )
        for error in ownership_registry_errors(schema_root)
    )
    export_tables: dict[str, list[tuple[str, Path]]] = {}
    participant_sources = (
        *root.glob("modules/*/src/armi_*/_data_rights.py"),
        root / "modules/data-rights/src/armi_data_rights/_data_rights_participant.py",
        root / "apps/armi-runtime/src/armi_runtime/composition/data_rights.py",
    )
    for participant_path in participant_sources:
        if not participant_path.exists():
            continue
        tree = ast.parse(participant_path.read_text(encoding="utf-8"))
        for node in tree.body:
            segment_value: ast.expr | None = None
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id in {"_SEGMENTS", "_RUNTIME_SEGMENTS"}
                    for target in node.targets
                )
            ) or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in {"_SEGMENTS", "_RUNTIME_SEGMENTS"}
            ):
                segment_value = node.value
            if segment_value is None:
                continue
            value = ast.literal_eval(segment_value)
            for segment_name, statement in value:
                tables = re.findall(r"\bFROM\s+armi\.([a-z][a-z0-9_]*)", statement)
                if len(tables) != 1 or tables[0] != segment_name:
                    violations.append(
                        Violation(
                            "ARC-DATA-RIGHTS-EXPORT-SEGMENT",
                            _relative(participant_path, root),
                            node.lineno,
                            f"segment {segment_name!r} must select its matching owner table",
                        )
                    )
                    continue
                export_tables.setdefault(tables[0], []).append(
                    (segment_name, participant_path)
                )
    export_tables["artifacts"] = [
        (
            "artifacts",
            root / "apps/armi-runtime/src/armi_runtime/composition/data_rights.py",
        )
    ]
    for table in TABLE_OWNERSHIP:
        mappings = export_tables.get(table, [])
        if len(mappings) != 1:
            violations.append(
                Violation(
                    "ARC-DATA-RIGHTS-EXPORT-COVERAGE",
                    _relative(registry_path, root),
                    1,
                    f"armi.{table} must map to exactly one owner export segment",
                )
            )
    foreign_accesses = scan_repository_foreign_table_accesses(root)
    production_accesses = tuple(
        access for access in foreign_accesses if "/schema/" not in access.path
    )
    frozen_revision_paths = (
        "/schema/alembic/versions/0004_context_embedding_projections.py",
        "/schema/alembic/versions/0006_relationship_lifecycle.py",
        "/schema/alembic/versions/0007_mood_owner.py",
        "/schema/alembic/versions/0009_remove_shared_action_operations.py",
        "/schema/alembic/versions/0011_creator_cognition_branches.py",
    )
    unexpected_frozen_accesses = tuple(
        access
        for access in foreign_accesses
        if not any(access.path.endswith(path) for path in frozen_revision_paths)
    )
    if len(foreign_accesses) != 29:
        violations.append(
            Violation(
                "ARC-SQL-OWNER-BUDGET",
                _relative(registry_path, root),
                1,
                "foreign SQL must be limited to the 29 frozen revision accesses: "
                f"raw={len(foreign_accesses)}",
            )
        )
    if production_accesses:
        violations.append(
            Violation(
                "ARC-SQL-OWNER-BUDGET",
                _relative(registry_path, root),
                1,
                "production foreign SQL must be zero: "
                f"production={len(production_accesses)}",
            )
        )
    for access in unexpected_frozen_accesses:
        violations.append(
            Violation(
                "ARC-SQL-OWNER-FROZEN",
                access.path,
                access.line,
                f"armi.{access.table} is not an approved frozen revision access",
            )
        )
    for access in production_accesses:
        if access.table_owner == "data-rights":
            violations.append(
                Violation(
                    "ARC-DATA-RIGHTS-PRIVATE-SQL",
                    access.path,
                    access.line,
                    f"armi.{access.table} must be read through Data Rights ports",
                )
            )
    admin_accesses = tuple(
        access for access in foreign_accesses if access.source_owner == "admin"
    )
    for access in admin_accesses:
        violations.append(
            Violation(
                "ARC-ADMIN-SQL-OWNER",
                access.path,
                access.line,
                f"Admin must use owner ports for armi.{access.table}",
            )
        )
    runtime_admin_path = (
        root / "apps/armi-admin/src/armi_admin/persistence/runtime_foundation.py"
    )
    runtime_admin_source = runtime_admin_path.read_text(encoding="utf-8")
    if (
        "sql.Identifier" in runtime_admin_source
        or "psycopg.sql" in runtime_admin_source
    ):
        violations.append(
            Violation(
                "ARC-ADMIN-DYNAMIC-SQL",
                _relative(runtime_admin_path, root),
                1,
                "Runtime Admin maintenance adapter must use fixed statements",
            )
        )
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
    from check_creator_web import check_repository as check_creator_repository

    creator_violations = check_creator_repository(root)
    if violations:
        for violation in violations:
            print(violation.render())
    if creator_violations:
        for violation in creator_violations:
            print(violation.render())
    if violations or creator_violations:
        print(
            "workspace-boundaries: fail "
            f"({len(violations) + len(creator_violations)} violation(s))"
        )
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
    print("creator-web-boundaries: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
