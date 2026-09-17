"""Directory-owned groups; explicit tags describe cross-module scenarios."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest


def normalized(value: str) -> str:
    return (
        re.sub(r"(?<=[a-z])([A-Z])", r"-\1", value.removeprefix("armi-"))
        .replace("_", "-")
        .lower()
    )


def web_files(root: Path) -> dict[Path, set[str]]:
    source = root / "apps/armi-creator-web/src"
    result = {}
    for path in source.rglob("*"):
        if path.name.endswith((".test.ts", ".test.tsx")):
            parts = path.relative_to(source).parts
            result[path] = {
                "web",
                "creator-web",
                normalized(parts[1] if parts[0] == "features" else parts[0]),
            }
    return result


def directory_groups(root: Path) -> set[str]:
    return {
        normalized(path.name)
        for area in ("modules", "packages", "apps", "tests")
        for path in (root / area).glob("*")
        if path.is_dir() and not path.name.startswith((".", "__"))
    }


def path_groups(relative: Path, known: set[str]) -> set[str]:
    parts = relative.parts
    groups = {normalized(parts[1])} if len(parts) > 1 else set()
    stem = normalized(relative.stem.removeprefix("test_"))
    groups.update(group for group in known if f"-{group}-" in f"-{stem}-")
    return groups


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--test-group", action="append", default=[])
    parser.addoption("--test-lane", choices=("offline", "database"))
    parser.addoption("--test-inventory", type=Path)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "test_group(*names): cross-module test groups")
    encoded = os.environ.get("ARMI_TEST_POSTGRESQL_WORKER_DSNS")
    if encoded is not None:
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
        values = json.loads(encoded)
        if (
            not worker_id.startswith("gw")
            or not worker_id[2:].isdigit()
            or not isinstance(values, list)
            or not all(isinstance(value, str) and value for value in values)
            or int(worker_id[2:]) >= len(values)
        ):
            raise pytest.UsageError("PG-INTEGRATION-WORKER-DSN")
        os.environ["S009_ADMIN_DSN"] = values[int(worker_id[2:])]
    if (
        config.getoption("test_lane") == "database"
        and not config.option.collectonly
        and not os.environ.get("S009_ADMIN_DSN")
    ):
        raise pytest.UsageError("Database tests require isolated PostgreSQL")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    requested = set(config.getoption("test_group") or ())
    lane = config.getoption("test_lane")
    inventory_path = config.getoption("test_inventory")
    if not requested and lane is None and inventory_path is None:
        return
    known = directory_groups(config.rootpath)
    groups: dict[str, Counter[str]] = {}
    selected: list[pytest.Item] = []
    excluded: list[pytest.Item] = []
    counts: Counter[str] = Counter()
    out_of_scope: dict[str, list[str]] = {}
    for labels in web_files(config.rootpath).values():
        for label in labels:
            groups.setdefault(label, Counter())["web_files"] += 1
        if not requested or requested & labels:
            counts["web_files"] += 1
    for item in items:
        labels = path_groups(item.path.relative_to(config.rootpath), known)
        for mark in item.iter_markers("test_group"):
            labels.update(mark.args)
        exclusions = [
            mark
            for mark in ("creator_system", "browser", "live", "installation")
            if item.get_closest_marker(mark)
        ]
        if exclusions:
            out_of_scope[item.nodeid] = exclusions
        kind = (
            "excluded"
            if exclusions
            else "database"
            if item.get_closest_marker("postgresql")
            else "offline"
        )
        for label in labels:
            groups.setdefault(label, Counter())[kind] += 1
        if (
            kind != "excluded"
            and (not requested or requested & labels)
            and (lane is None or lane == kind)
        ):
            selected.append(item)
            counts[kind] += 1
        else:
            excluded.append(item)
    if inventory_path is not None:
        inventory_path.write_text(
            json.dumps(
                {
                    "collected": len(items),
                    "selected": dict(counts),
                    "excluded": len(excluded),
                    "out_of_scope": out_of_scope,
                    "groups": groups,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if requested - groups.keys():
        raise pytest.UsageError(
            f"Unknown test groups: {', '.join(sorted(requested - groups.keys()))}"
        )
    items[:] = selected
    config.hook.pytest_deselected(items=excluded)
