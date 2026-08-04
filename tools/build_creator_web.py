"""Generate and verify the deterministic Creator OpenAPI and static resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import rfc8785
from armi_runtime.interfaces.creator_contract import build_creator_openapi

RESOURCE_RELATIVE = Path(
    "apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources"
)
GENERATED_RELATIVE = Path("apps/armi-creator-web/src/api/generated/creator.ts")
CREATOR_RELATIVE = Path("apps/armi-creator-web")
EXPECTED_NODE = "v24.18.0"
EXPECTED_NPM = "11.16.0"
EXPECTED_GENERATOR = "7.13.0"
PERSONAL_PATH = re.compile(rb"[A-Za-z]:\\(?:Users|WorkSpace)\\", re.IGNORECASE)
SECRET_TOKEN = re.compile(rb"(?:sk|ghp|xox[baprs])-[A-Za-z0-9_-]{20,}")
EXTERNAL_URL = re.compile(rb"https?://", re.IGNORECASE)
INERT_LIBRARY_URLS = (
    b"https://react.dev/errors/",
    b"http://www.w3.org/2000/svg",
    b"http://www.w3.org/1998/Math/MathML",
    b"http://www.w3.org/1999/xlink",
    b"http://www.w3.org/XML/1998/namespace",
)


class CreatorBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: object) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CreatorBuildError("WEB-GEN-INPUT", f"cannot read {path.name}") from error
    if not isinstance(value, dict):
        raise CreatorBuildError("WEB-GEN-INPUT", f"{path.name} must be an object")
    return value


def run(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        output = "\n".join(
            item.strip()
            for item in (completed.stdout, completed.stderr)
            if item.strip()
        )
        raise CreatorBuildError(
            "WEB-GEN-COMMAND",
            f"command failed with exit {completed.returncode}: {output}",
        )
    return completed.stdout.strip()


def media_type(path: Path) -> str:
    return {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
    }.get(path.suffix.lower(), "application/octet-stream")


def cache_class(relative: str) -> str:
    if relative.startswith("static/assets/"):
        return "immutable"
    if relative == "static/index.html":
        return "entrypoint-no-store"
    return "metadata-no-store"


def validate_tools(root: Path, tool_root: Path) -> tuple[Path, dict[str, Any]]:
    node = tool_root / "installs/node/node-v24.18.0-win-x64/node.exe"
    package_path = root / CREATOR_RELATIVE / "package.json"
    package = read_json(package_path)
    generator = root / CREATOR_RELATIVE / "node_modules/openapi-typescript/bin/cli.js"
    vite = root / CREATOR_RELATIVE / "node_modules/vite/bin/vite.js"
    prettier = root / CREATOR_RELATIVE / "node_modules/prettier/bin/prettier.cjs"
    for path in (node, generator, vite, prettier):
        if not path.is_file():
            raise CreatorBuildError(
                "WEB-GEN-TOOL",
                f"required isolated tool is missing: {path.name}",
            )
    environment = os.environ.copy()
    environment.update(
        {
            "NPM_CONFIG_OFFLINE": "true",
            "NO_UPDATE_NOTIFIER": "1",
        }
    )
    actual_node = run((str(node), "--version"), cwd=root, environment=environment)
    if actual_node != EXPECTED_NODE:
        raise CreatorBuildError(
            "WEB-GEN-VERSION",
            f"Node must be {EXPECTED_NODE}, observed {actual_node}",
        )
    if package.get("packageManager") != f"npm@{EXPECTED_NPM}":
        raise CreatorBuildError(
            "WEB-GEN-VERSION",
            "Creator packageManager does not match the frozen npm version",
        )
    generator_package = read_json(
        root / CREATOR_RELATIVE / "node_modules/openapi-typescript/package.json"
    )
    if generator_package.get("version") != EXPECTED_GENERATOR:
        raise CreatorBuildError(
            "WEB-GEN-VERSION",
            "openapi-typescript version does not match the frozen generator",
        )
    return node, package


def validate_openapi(schema: dict[str, object]) -> None:
    if schema.get("openapi") != "3.1.0":
        raise CreatorBuildError("CON-OPENAPI-VERSION", "OpenAPI must be 3.1.0")
    if "servers" in schema:
        raise CreatorBuildError("CON-OPENAPI-SERVERS", "servers are forbidden")
    paths = schema.get("paths")
    if not isinstance(paths, dict) or set(paths) != {
        "/health/live",
        "/health/ready",
        "/v1/browser-bootstrap-codes",
        "/v1/browser-sessions",
        "/v1/browser-sessions/current",
        "/v1/activities",
        "/v1/activities/{activity_id}/timeline",
        "/v1/runtime/status",
        "/v1/operations/{result_ref}",
        "/v1/effects/{effect_id}",
        "/v1/effects/{effect_id}/artifacts/{artifact_kind}",
        "/v1/subject/summary",
        "/v1/capability-requests",
        "/v1/capability-requests/{capability_request_id}/decision",
        "/v1/scenes/{scene_key}/events",
        "/v1/scenes/{scene_key}/codex-tasks",
        "/v1/scenes/{scene_key}/messages",
        "/v1/scenes/{scene_key}/timeline",
    }:
        raise CreatorBuildError(
            "CON-OPENAPI-PATHS",
            "OpenAPI paths do not match the frozen Creator surface",
        )
    operation_ids = {
        str(operation.get("operationId"))
        for item in paths.values()
        if isinstance(item, dict)
        for operation in item.values()
        if isinstance(operation, dict)
    }
    if operation_ids != {
        "createBrowserBootstrapCode",
        "createBrowserSession",
        "deleteCurrentBrowserSession",
        "getCurrentBrowserSession",
        "getHealthLive",
        "getHealthReady",
        "getRuntimeStatus",
        "getCreatorOperation",
        "getCreatorActivityTimeline",
        "getEffect",
        "getEffectArtifact",
        "getSubjectSummary",
        "listCapabilityRequests",
        "listCreatorActivities",
        "decideCapabilityRequest",
        "getSceneTimeline",
        "acceptCreatorCodexTask",
        "acceptCreatorMessage",
        "streamSceneEvents",
    }:
        raise CreatorBuildError(
            "CON-OPENAPI-OPERATION",
            "OpenAPI operation IDs do not match the frozen set",
        )


def validate_static_bytes(path: Path, value: bytes) -> None:
    if path.suffix == ".map":
        raise CreatorBuildError("WEB-ASSET-SOURCEMAP", "source maps are forbidden")
    if PERSONAL_PATH.search(value):
        raise CreatorBuildError("SEC-WEB-PATH", f"personal path in {path.name}")
    if SECRET_TOKEN.search(value):
        raise CreatorBuildError("SEC-WEB-SECRET", f"secret-like token in {path.name}")
    inspected = value
    for allowed in INERT_LIBRARY_URLS:
        inspected = inspected.replace(allowed, b"")
    if EXTERNAL_URL.search(inspected):
        raise CreatorBuildError("SEC-WEB-EXTERNAL", f"external URL in {path.name}")


def generate(root: Path, tool_root: Path, stage: Path) -> tuple[Path, Path]:
    node, package = validate_tools(root, tool_root)
    creator = root / CREATOR_RELATIVE
    generated = stage / "generated/creator.ts"
    resources = stage / "resources"
    static = resources / "static"
    generated.parent.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "__init__.py").write_text(
        '"""Packaged Creator OpenAPI and deterministic static resources."""\n\n'
        "__all__ = ()\n",
        encoding="utf-8",
        newline="\n",
    )

    schema = build_creator_openapi()
    validate_openapi(schema)
    openapi_bytes = canonical_json(schema)
    openapi_path = resources / "openapi.json"
    openapi_path.write_bytes(openapi_bytes)

    environment = os.environ.copy()
    environment.update({"NPM_CONFIG_OFFLINE": "true", "NO_UPDATE_NOTIFIER": "1"})
    generator = creator / "node_modules/openapi-typescript/bin/cli.js"
    run(
        (
            str(node),
            str(generator),
            str(openapi_path),
            "--output",
            str(generated),
        ),
        cwd=creator,
        environment=environment,
    )
    generated.write_bytes(generated.read_bytes().replace(b"\r\n", b"\n"))
    prettier = creator / "node_modules/prettier/bin/prettier.cjs"
    formatted = subprocess.run(
        (
            str(node),
            str(prettier),
            "--stdin-filepath",
            str(root / GENERATED_RELATIVE),
        ),
        cwd=creator,
        env=environment,
        input=generated.read_text(encoding="utf-8"),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if formatted.returncode != 0:
        raise CreatorBuildError(
            "WEB-GEN-COMMAND",
            "Prettier failed to normalize generated transport types",
        )
    generated.write_text(
        formatted.stdout.replace("\r\n", "\n"),
        encoding="utf-8",
        newline="\n",
    )

    vite = creator / "node_modules/vite/bin/vite.js"
    run(
        (
            str(node),
            str(vite),
            "build",
            "--outDir",
            str(static),
            "--emptyOutDir",
        ),
        cwd=creator,
        environment=environment,
    )

    assets: list[dict[str, object]] = []
    for path in sorted(
        (item for item in static.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(resources).as_posix(),
    ):
        value = path.read_bytes()
        validate_static_bytes(path, value)
        relative = path.relative_to(resources).as_posix()
        assets.append(
            {
                "path": relative,
                "size": len(value),
                "media_type": media_type(path),
                "sha256": sha256_bytes(value),
                "cache_class": cache_class(relative),
            }
        )

    dependencies = package.get("dependencies")
    development = package.get("devDependencies")
    if not isinstance(dependencies, dict) or not isinstance(development, dict):
        raise CreatorBuildError("WEB-GEN-INPUT", "Creator dependencies are malformed")
    vite_manifest = static / ".vite/manifest.json"
    if not vite_manifest.is_file():
        raise CreatorBuildError("WEB-ASSET-MANIFEST", "Vite manifest is missing")
    manifest = {
        "schema_version": "armi.creator-static.v1",
        "base_path": "/ui/",
        "entrypoint": "static/index.html",
        "openapi": {
            "path": "openapi.json",
            "sha256": sha256_bytes(openapi_bytes),
        },
        "generated_types": {
            "path": GENERATED_RELATIVE.as_posix(),
            "sha256": sha256_file(generated),
        },
        "package_lock_sha256": sha256_file(creator / "package-lock.json"),
        "toolchain": {
            "node": EXPECTED_NODE.removeprefix("v"),
            "npm": EXPECTED_NPM,
            "react": dependencies.get("react"),
            "react_dom": dependencies.get("react-dom"),
            "typescript": development.get("typescript"),
            "vite": development.get("vite"),
            "openapi_typescript": development.get("openapi-typescript"),
        },
        "vite_manifest_sha256": sha256_file(vite_manifest),
        "assets": assets,
        "runtime_discovery": False,
    }
    (resources / "manifest.json").write_bytes(canonical_json(manifest))
    return generated, resources


def files_under(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix != ".pyc"
    }


def compare_file(expected: Path, actual: Path, *, code: str) -> None:
    if not actual.is_file() or expected.read_bytes() != actual.read_bytes():
        raise CreatorBuildError(code, f"committed artifact drift: {actual}")


def compare_tree(expected: Path, actual: Path) -> None:
    expected_files = files_under(expected)
    actual_files = files_under(actual)
    if expected_files.keys() != actual_files.keys():
        raise CreatorBuildError(
            "WEB-ASSET-SET",
            "committed Creator resource file set has drifted",
        )
    for path, value in expected_files.items():
        if actual_files[path] != value:
            raise CreatorBuildError(
                "WEB-ASSET-DIGEST",
                f"committed Creator resource drift: {path}",
            )


def write_artifacts(
    root: Path,
    generated: Path,
    resources: Path,
) -> None:
    generated_target = root / GENERATED_RELATIVE
    resource_target = root / RESOURCE_RELATIVE
    generated_target.parent.mkdir(parents=True, exist_ok=True)
    generated_target.write_bytes(generated.read_bytes())
    if resource_target.exists():
        resolved = resource_target.resolve()
        allowed = (root / "apps/armi-runtime/src/armi_runtime/interfaces").resolve()
        if allowed not in resolved.parents:
            raise CreatorBuildError("WEB-ASSET-PATH", "unsafe resource target")
        shutil.rmtree(resource_target)
    shutil.copytree(resources, resource_target)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--tool-root", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    tool_root = (
        args.tool_root.resolve()
        if args.tool_root
        else Path(os.environ.get("ARMI_TOOL_ROOT", str(root / ".armi-tools"))).resolve()
    )
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="creator-build-",
            dir=temporary_root,
        ) as temporary:
            generated, resources = generate(root, tool_root, Path(temporary))
            if args.write:
                write_artifacts(root, generated, resources)
            else:
                compare_file(
                    generated,
                    root / GENERATED_RELATIVE,
                    code="WEB-GEN-DRIFT",
                )
                compare_tree(resources, root / RESOURCE_RELATIVE)
        action = "written" if args.write else "verified"
        print(f"creator-static: {action}")
        return 0
    except CreatorBuildError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
