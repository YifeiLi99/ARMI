"""Generate reproducible M0-S003 dependency, license, and tool digests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from tools.check_locked_environment import (
    CREATOR_DEPENDENCIES,
    CREATOR_DEV_DEPENDENCIES,
    PYTHON_DIRECT,
    TOOL_DEPENDENCIES,
)

INTERNAL_PACKAGES = {"armi-admin", "armi-kernel", "armi-runtime"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def normalized_name(value: str) -> str:
    return value.lower().replace("_", "-")


def python_license(distribution: importlib.metadata.Distribution) -> str | None:
    metadata = distribution.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    license_value = metadata.get("License")
    if license_value and license_value.strip().lower() not in {"unknown", "n/a"}:
        return license_value.strip()
    classifiers = [
        item.removeprefix("License :: ").strip()
        for item in metadata.get_all("Classifier", [])
        if item.startswith("License :: ")
    ]
    return " OR ".join(sorted(set(classifiers))) or None


def python_inventory(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = {
        normalized_name(str(item["name"])): item
        for item in lock.get("package", [])
        if isinstance(item, dict) and item.get("name")
    }
    site_packages = root / ".venv/Lib/site-packages"
    distributions = sorted(
        importlib.metadata.distributions(path=[str(site_packages)]),
        key=lambda item: normalized_name(item.metadata["Name"]),
    )
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    for distribution in distributions:
        name = normalized_name(distribution.metadata["Name"])
        lock_entry = locked.get(name, {})
        license_value = python_license(distribution)
        internal = name in INTERNAL_PACKAGES
        if internal:
            license_value = "project-private-unlicensed"
        hashes: set[str] = set()
        sdist = lock_entry.get("sdist")
        if isinstance(sdist, dict) and isinstance(sdist.get("hash"), str):
            hashes.add(sdist["hash"])
        for wheel in lock_entry.get("wheels", []):
            if isinstance(wheel, dict) and isinstance(wheel.get("hash"), str):
                hashes.add(wheel["hash"])
        nodes.append(
            {
                "name": name,
                "version": distribution.version,
                "direct": name in PYTHON_DIRECT or internal,
                "internal": internal,
                "source": lock_entry.get("source"),
                "integrity": sorted(hashes),
                "license": license_value,
            }
        )
        for dependency in lock_entry.get("dependencies", []):
            if isinstance(dependency, dict) and dependency.get("name"):
                edges.append(
                    {
                        "from": f"{name}@{distribution.version}",
                        "to": normalized_name(str(dependency["name"])),
                    }
                )
    return nodes, sorted(edges, key=lambda item: (item["from"], item["to"]))


def npm_name_from_key(key: str) -> str:
    marker = "node_modules/"
    return key.rsplit(marker, maxsplit=1)[-1]


def npm_inventory(
    root: Path,
    *,
    lock_relative: str,
    direct_runtime: dict[str, str],
    direct_development: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    lock = json.loads((root / lock_relative).read_text(encoding="utf-8"))
    packages = lock["packages"]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    direct = set(direct_runtime) | set(direct_development)
    for key in sorted(item for item in packages if item):
        entry = packages[key]
        name = npm_name_from_key(key)
        version = str(entry.get("version", ""))
        nodes.append(
            {
                "name": name,
                "version": version,
                "direct": name in direct,
                "development": name in direct_development,
                "resolved": entry.get("resolved"),
                "integrity": entry.get("integrity"),
                "license": entry.get("license"),
            }
        )
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            values = entry.get(field, {})
            if isinstance(values, dict):
                for dependency in values:
                    edges.append(
                        {
                            "from": f"{name}@{version}",
                            "to": dependency,
                            "kind": field,
                        }
                    )
    return nodes, sorted(
        edges, key=lambda item: (item["from"], item["to"], item["kind"])
    )


def directory_digest(root: Path) -> str:
    records: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        records.append(f"{relative}\t{sha256_file(path)}\n")
    return hashlib.sha256("".join(records).encode("utf-8")).hexdigest()


def update_tool_manifest(root: Path, tool_root: Path, graph_digest: str) -> None:
    path = root / "tools/toolchain-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    install_paths = {
        "cpython": tool_root
        / "installs/python/cpython-3.14.6-windows-x86_64-none/python.exe",
        "uv": tool_root / "installs/uv/0.11.33/uv.exe",
        "node": tool_root / "installs/node/node-v24.18.0-win-x64/node.exe",
        "npm": tool_root
        / "installs/node/node-v24.18.0-win-x64/node_modules/npm/bin/npm-cli.js",
        "codex-cli": root / "tools/toolchain-node/node_modules/@openai/codex",
        "pyright": root / "tools/toolchain-node/node_modules/pyright",
    }
    browsers = sorted((tool_root / "installs/playwright").rglob("chrome.exe"))
    for item in manifest["tools"]:
        tool_id = item["id"]
        install_path = install_paths.get(tool_id)
        if install_path and install_path.is_file():
            item["install_digest"] = sha256_file(install_path)
        elif install_path and install_path.is_dir():
            item["install_digest"] = directory_digest(install_path)
        if tool_id == "playwright-chromium":
            if not browsers:
                raise RuntimeError("Playwright Chromium executable is missing")
            item["version"] = "1228"
            item["install_digest"] = sha256_file(browsers[0])
    for item in manifest["lockfiles"]:
        lock_path = root / item["path"]
        item["sha256"] = sha256_file(lock_path)
    manifest["dependency_inventory"] = {
        "path": "tools/dependency-inventory.json",
        "graph_sha256": graph_digest,
    }
    write_json(path, manifest)


def generate(root: Path, tool_root: Path) -> dict[str, Any]:
    python_nodes, python_edges = python_inventory(root)
    creator_nodes, creator_edges = npm_inventory(
        root,
        lock_relative="apps/armi-creator-web/package-lock.json",
        direct_runtime=CREATOR_DEPENDENCIES,
        direct_development=CREATOR_DEV_DEPENDENCIES,
    )
    tool_nodes, tool_edges = npm_inventory(
        root,
        lock_relative="tools/toolchain-node/package-lock.json",
        direct_runtime={},
        direct_development=TOOL_DEPENDENCIES,
    )
    ecosystems = {
        "python": {"nodes": python_nodes, "edges": python_edges},
        "creator": {"nodes": creator_nodes, "edges": creator_edges},
        "tooling": {"nodes": tool_nodes, "edges": tool_edges},
    }
    unresolved = sorted(
        f"{ecosystem}:{item['name']}@{item['version']}"
        for ecosystem, graph in ecosystems.items()
        for item in graph["nodes"]
        if not item.get("license")
    )
    graph_digest = canonical_digest(ecosystems)
    inventory = {
        "schema_version": "armi.dependency-inventory.v1",
        "status": "pass" if not unresolved else "blocked",
        "ecosystems": ecosystems,
        "unresolved_licenses": unresolved,
        "graph_sha256": graph_digest,
    }
    write_json(root / "tools/dependency-inventory.json", inventory)
    update_tool_manifest(root, tool_root, graph_digest)
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    tool_root = args.tool_root.resolve() if args.tool_root else root / ".armi-tools"
    inventory = generate(root, tool_root)
    if inventory["unresolved_licenses"]:
        for item in inventory["unresolved_licenses"]:
            print(f"S003-INVENTORY unresolved license: {item}", file=sys.stderr)
        return 1
    print(f"dependency-inventory: pass ({inventory['graph_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
