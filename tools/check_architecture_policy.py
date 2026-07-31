"""Validate owner write surfaces, composition, and obsolete entry points."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRODUCTION_ROOTS = (
    Path("packages/armi-kernel/src"),
    Path("apps/armi-runtime/src"),
    Path("apps/armi-admin/src"),
)
DISCOVERY_CALLS = {
    "importlib.metadata.entry_points",
    "pkgutil.iter_modules",
    "pkgutil.walk_packages",
}
LOCATOR_NAMES = {
    "service_locator",
    "service_registry",
    "global_services",
    "register_service",
    "resolve_service",
}


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def imported_modules(tree: ast.Module) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                yield f"{node.module}.{alias.name}", node.lineno


def module_matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def policy_ids(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]


def validate_policy(policy: dict[str, Any], path: str) -> list[Violation]:
    violations: list[Violation] = []
    if policy.get("schema_version") != "armi.architecture-policy.v1":
        violations.append(
            Violation("ARC-POLICY-METADATA", path, 1, "unsupported schema_version")
        )
    for field, reason_field in (
        ("write_surfaces", "write_surfaces_not_applicable_reason"),
        ("named_coordinators", "named_coordinators_not_applicable_reason"),
        (
            "transaction_control_exemptions",
            "transaction_control_exemptions_not_applicable_reason",
        ),
        ("forbidden_entry_points", "forbidden_entry_points_not_applicable_reason"),
    ):
        items = policy.get(field)
        if not isinstance(items, list):
            violations.append(
                Violation("ARC-POLICY-METADATA", path, 1, f"{field} must be an array")
            )
            continue
        ids = policy_ids(items)
        if len(ids) != len(set(ids)):
            violations.append(
                Violation("ARC-POLICY-METADATA", path, 1, f"{field} IDs must be unique")
            )
        if not items and not str(policy.get(reason_field, "")).strip():
            violations.append(
                Violation(
                    "ARC-POLICY-METADATA",
                    path,
                    1,
                    f"empty {field} requires {reason_field}",
                )
            )
    composition = policy.get("runtime_composition")
    expected_composition = {
        "entry_point": "armi",
        "manifest": (
            "apps/armi-runtime/src/armi_runtime/composition/"
            "runtime_resources/runtime-composition.manifest.json"
        ),
        "active_bindings": {
            "M0-SEAM-CONTEXT": "armi.context-compiler.deterministic-v1",
            "M0-SEAM-MODEL": "armi.model-adapter.volcengine-ark-responses-v1",
            "M0-SEAM-WORK-SELECTION": ("armi.opportunity-selector.creator-fifo-v1"),
            "M0-SEAM-CREATOR-PROJECTION": "armi.scene-timeline-query.v2",
            "M0-SEAM-CREATOR-UI": "armi.creator-static.v1",
        },
        "runtime_discovery": False,
    }
    if composition != expected_composition:
        violations.append(
            Violation(
                "ARC-BINDING-MANIFEST",
                path,
                1,
                "runtime composition policy must declare the exact active bindings",
            )
        )
    return violations


def analyze_source(
    source: str,
    *,
    module: str,
    path: str,
    policy: dict[str, Any],
) -> list[Violation]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [
            Violation(
                "ARC-POLICY-SYNTAX",
                path,
                error.lineno or 1,
                error.msg,
            )
        ]

    violations: list[Violation] = []
    write_surfaces = [
        item for item in policy.get("write_surfaces", []) if isinstance(item, dict)
    ]
    coordinators = [
        item for item in policy.get("named_coordinators", []) if isinstance(item, dict)
    ]
    obsolete = [
        item
        for item in policy.get("forbidden_entry_points", [])
        if isinstance(item, dict)
    ]
    driver_roots = set(policy.get("database_driver_roots", []))
    markers = set(policy.get("persistence_markers", []))
    registered_modules = {
        str(item.get("module")) for item in write_surfaces if item.get("module")
    }
    coordinator_modules = {
        str(item.get("module")) for item in coordinators if item.get("module")
    }
    driver_boundary_modules = {
        str(item.get("module"))
        for item in policy.get("database_driver_boundaries", [])
        if isinstance(item, dict) and item.get("module")
    }
    transaction_exemptions = {
        str(item.get("module"))
        for item in policy.get("transaction_control_exemptions", [])
        if isinstance(item, dict) and item.get("module")
    }
    forbidden_coordinator_io = set(policy.get("coordinator_forbidden_io_roots", []))
    imports = list(imported_modules(tree))

    imports_driver = False
    for imported, line in imports:
        root = imported.split(".", maxsplit=1)[0]
        if module in coordinator_modules and root in forbidden_coordinator_io:
            violations.append(
                Violation(
                    "ARC-OWNER-COORDINATOR-IO",
                    path,
                    line,
                    f"transaction coordinator cannot import slow external I/O: {root}",
                )
            )
        if root in driver_roots:
            imports_driver = True
            if (
                module not in registered_modules
                and module not in coordinator_modules
                and module not in driver_boundary_modules
            ):
                violations.append(
                    Violation(
                        "ARC-OWNER-DIRECT-DRIVER",
                        path,
                        line,
                        f"{module} is not a registered write surface or coordinator",
                    )
                )
        for surface in write_surfaces:
            target = str(surface.get("module", ""))
            if not target or not module_matches(imported, target):
                continue
            allowed = [str(item) for item in surface.get("allowed_callers", [])]
            if module not in coordinator_modules and not any(
                module_matches(module, prefix) for prefix in allowed
            ):
                violations.append(
                    Violation(
                        "ARC-OWNER-CROSS-WRITE",
                        path,
                        line,
                        f"{module} cannot reference owner write surface {target}",
                    )
                )
        for entry in obsolete:
            target = str(entry.get("module", ""))
            if target and module_matches(imported, target):
                violations.append(
                    Violation(
                        "EVO-CLEAN-OLD-ENTRY",
                        path,
                        line,
                        f"forbidden entry point remains reachable: {target}",
                    )
                )

    module_segments = set(module.split("."))
    has_implementation = any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in tree.body
    )
    if (
        markers.intersection(module_segments)
        and (imports_driver or has_implementation)
        and module not in registered_modules
        and module not in coordinator_modules
    ):
        violations.append(
            Violation(
                "ARC-OWNER-UNREGISTERED-WRITE-SURFACE",
                path,
                1,
                f"persistence module {module} requires an exact policy entry",
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"commit", "rollback", "transaction"}
                and module not in coordinator_modules
                and module not in transaction_exemptions
            ):
                violations.append(
                    Violation(
                        "ARC-OWNER-TRANSACTION-CONTROL",
                        path,
                        node.lineno,
                        "transaction control is reserved for the registered coordinator",
                    )
                )
            if name in DISCOVERY_CALLS:
                violations.append(
                    Violation(
                        "ARC-BINDING-DISCOVERY",
                        path,
                        node.lineno,
                        f"dynamic implementation discovery is forbidden: {name}",
                    )
                )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            normalized = node.name.lower()
            if normalized in LOCATOR_NAMES or normalized == "servicelocator":
                violations.append(
                    Violation(
                        "ARC-BINDING-GLOBAL-LOCATOR",
                        path,
                        node.lineno,
                        f"global service locator API is forbidden: {node.name}",
                    )
                )
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id.lower() in LOCATOR_NAMES:
                violations.append(
                    Violation(
                        "ARC-BINDING-GLOBAL-LOCATOR",
                        path,
                        statement.lineno,
                        f"module-level service registry is forbidden: {target.id}",
                    )
                )
    return violations


def module_identity(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def check_repository(
    root: Path, policy: dict[str, Any] | None = None
) -> list[Violation]:
    root = root.resolve()
    policy_path = root / "tools/architecture-policy.json"
    if policy is None:
        try:
            loaded = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return [
                Violation("ARC-POLICY-METADATA", policy_path.as_posix(), 1, str(error))
            ]
        if not isinstance(loaded, dict):
            return [
                Violation(
                    "ARC-POLICY-METADATA",
                    policy_path.as_posix(),
                    1,
                    "policy root must be an object",
                )
            ]
        policy = loaded
    violations = validate_policy(policy, policy_path.as_posix())
    for source_relative in PRODUCTION_ROOTS:
        source_root = root / source_relative
        for path in sorted(source_root.rglob("*.py")):
            violations.extend(
                analyze_source(
                    path.read_text(encoding="utf-8"),
                    module=module_identity(path, source_root),
                    path=path.relative_to(root).as_posix(),
                    policy=policy,
                )
            )
    for entry in policy.get("forbidden_entry_points", []):
        if not isinstance(entry, dict):
            continue
        relative = entry.get("path")
        if isinstance(relative, str) and (root / relative).exists():
            violations.append(
                Violation(
                    "EVO-CLEAN-OLD-ENTRY",
                    relative,
                    1,
                    "forbidden entry point still exists",
                )
            )
    return sorted(set(violations))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--family", choices=("all", "owner", "clean"), default="all")
    args = parser.parse_args()
    violations = check_repository(args.root)
    if args.family == "owner":
        violations = [item for item in violations if item.code.startswith("ARC-")]
    elif args.family == "clean":
        violations = [item for item in violations if item.code.startswith("EVO-CLEAN-")]
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1
    print("architecture-policy: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
