"""Validate one installed ARMI wheel environment without importing workspace code."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def _normalized_requirement(raw: str) -> tuple[object, ...]:
    requirement = Requirement(raw)
    return (
        canonicalize_name(requirement.name),
        tuple(sorted(requirement.extras)),
        str(requirement.specifier),
        requirement.url or "",
        str(requirement.marker or ""),
    )


def validate_wheel_environment(contract_path: Path) -> None:
    contract = cast(
        dict[str, Any],
        json.loads(contract_path.read_text(encoding="utf-8")),
    )
    wheel_site = Path(cast(str, contract["wheel_site"])).resolve()
    forbidden = tuple(
        Path(item).resolve() for item in cast(list[str], contract["forbidden_paths"])
    )
    active_paths = tuple(Path(item).resolve() for item in sys.path if item)
    leaked = tuple(
        path
        for path in active_paths
        if any(path == root or root in path.parents for root in forbidden)
    )
    if leaked:
        raise RuntimeError(f"WHEEL-INSTALL-SOURCE-LEAK: {leaked}")

    specifications = cast(list[dict[str, Any]], contract["distributions"])
    for specification in specifications:
        module = importlib.import_module(cast(str, specification["module"]))
        module_path = Path(cast(str, module.__file__)).resolve()
        if wheel_site not in module_path.parents:
            raise RuntimeError(
                f"WHEEL-INSTALL-MODULE-ORIGIN: {specification['name']} {module_path}"
            )

    installed = tuple(metadata.distributions(path=[str(wheel_site)]))
    by_name: dict[str, metadata.Distribution] = {}
    for distribution in installed:
        name = canonicalize_name(distribution.metadata["Name"])
        if name in by_name:
            raise RuntimeError(f"WHEEL-INSTALL-DUPLICATE-DISTRIBUTION: {name}")
        by_name[name] = distribution

    for specification in specifications:
        name = canonicalize_name(cast(str, specification["name"]))
        distribution = by_name.get(name)
        if distribution is None:
            raise RuntimeError(f"WHEEL-INSTALL-MISSING-DISTRIBUTION: {name}")
        location = Path(str(distribution.locate_file(""))).resolve()
        if location != wheel_site:
            raise RuntimeError(f"WHEEL-INSTALL-DISTRIBUTION-ORIGIN: {name} {location}")
        actual = {
            _normalized_requirement(raw)
            for raw in distribution.requires or ()
            if "extra" not in str(Requirement(raw).marker or "")
        }
        expected = {
            _normalized_requirement(raw)
            for raw in cast(list[str], specification["requirements"])
        }
        if actual != expected:
            raise RuntimeError(f"WHEEL-INSTALL-METADATA: {name}")

    for distribution in installed:
        owner = distribution.metadata["Name"]
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            dependency = by_name.get(canonicalize_name(requirement.name))
            if dependency is None:
                raise RuntimeError(
                    f"WHEEL-INSTALL-MISSING-DEPENDENCY: {owner} requires {requirement}"
                )
            if requirement.specifier and not requirement.specifier.contains(
                dependency.version,
                prereleases=True,
            ):
                raise RuntimeError(
                    "WHEEL-INSTALL-DEPENDENCY-VERSION: "
                    f"{owner} requires {requirement}, found {dependency.version}"
                )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_wheel_environment(args.contract.resolve(strict=True))
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("wheel-environment: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
