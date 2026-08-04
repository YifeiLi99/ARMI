"""Build or independently verify the immutable M0 candidate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import cast
from zipfile import ZipFile

try:
    from tools.candidate_bundle import (
        COMPOSITION_MANIFEST,
        CREATOR_MANIFEST,
        SCHEMA_MANIFEST,
        CandidateError,
        build_identity,
        sha256_file,
        verify_bundle,
        write_deterministic_bundle,
    )
except ModuleNotFoundError:  # Direct execution from the tools directory.
    from candidate_bundle import (
        COMPOSITION_MANIFEST,
        CREATOR_MANIFEST,
        SCHEMA_MANIFEST,
        CandidateError,
        build_identity,
        sha256_file,
        verify_bundle,
        write_deterministic_bundle,
    )

_INSTALL_CHECK = r"""from __future__ import annotations
import hashlib, importlib.metadata, json, os, shutil, sys
from pathlib import Path

expected = json.loads(os.environ["ARMI_CANDIDATE_EXPECTED"])
entry_points = {
    "armi-admin": {"armi-admin-mcp": "armi_admin.mcp.entrypoint:main"},
    "armi-kernel": {},
    "armi-runtime": {
        "armi": "armi_runtime.cli:main",
        "armi-codex-runner": "armi_runtime.codex_runner_cli:main",
    },
}
for name, version in expected["versions"].items():
    distribution = importlib.metadata.distribution(name)
    if distribution.version != version:
        raise SystemExit(f"INSTALL-VERSION: {name}")
    actual = {item.name: item.value for item in distribution.entry_points if item.group == "console_scripts"}
    if actual != entry_points[name]:
        raise SystemExit(f"INSTALL-ENTRY: {name}")
runtime = importlib.metadata.distribution("armi-runtime")
for relative, digest in expected["resources"].items():
    path = Path(runtime.locate_file(relative))
    if not path.is_file() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(f"INSTALL-RESOURCE: {relative}")
for distribution in importlib.metadata.distributions():
    name = (distribution.metadata.get("Name") or "").lower().replace("_", "-")
    if name in expected["versions"]:
        for file in distribution.files or ():
            if file.name == "direct_url.json" or file.suffix == ".pth":
                text = Path(distribution.locate_file(file)).read_text(encoding="utf-8", errors="replace").lower()
                if "armi-runtime/src" in text or "armi-kernel/src" in text or "armi-admin/src" in text:
                    raise SystemExit(f"INSTALL-SOURCE-LINK: {name}")
if shutil.which("node") or shutil.which("npm"):
    raise SystemExit("INSTALL-NODE: Node leaked into install check")
print(json.dumps({"installed": sorted(expected["versions"]), "node": False}, separators=(",", ":")))
"""


def _run(
    command: list[str], root: Path, code: str, environment: dict[str, str] | None = None
) -> str:
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    if completed.returncode != 0:
        raise CandidateError(code, output or "command failed")
    return output


def git_facts(root: Path) -> tuple[str, str]:
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        root,
        "BND-GIT-STATUS",
    )
    if status:
        raise CandidateError("BND-GIT-DIRTY", "tracked or untracked workspace changes")
    revision = _run(["git", "rev-parse", "HEAD"], root, "BND-GIT-REVISION")
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        version = project["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as error:
        raise CandidateError(
            "BND-VERSION", "workspace version is unavailable"
        ) from error
    if not isinstance(version, str) or not version:
        raise CandidateError("BND-VERSION", "workspace version is invalid")
    return revision, version


def _export_requirements(root: Path, uv: Path) -> bytes:
    completed = subprocess.run(
        [
            str(uv),
            "export",
            "--all-packages",
            "--no-dev",
            "--no-emit-workspace",
            "--frozen",
            "--offline",
            "--no-header",
            "--no-annotate",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        message = (
            completed.stderr.strip() or completed.stdout.strip() or "export failed"
        )
        raise CandidateError("BND-LOCK-EXPORT", message)
    return (completed.stdout.rstrip("\n") + "\n").encode()


def publish_candidate(temporary: Path, destination: Path) -> None:
    if destination.exists():
        if destination.read_bytes() != temporary.read_bytes():
            raise CandidateError("BND-COLLISION", "existing candidate differs")
        temporary.unlink()
        return
    os.replace(temporary, destination)


def _quality_build(root: Path, tool_root: Path) -> list[Path]:
    python = root / ".venv/Scripts/python.exe"
    _run(
        [
            str(python),
            "-B",
            "tools/quality.py",
            "--tool-root",
            str(tool_root),
        ],
        root,
        "BND-QUALITY",
    )
    dist = root / ".tmp/quality/python-dist"
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 3:
        raise CandidateError("BND-WHEEL-SET", "quality build did not make three wheels")
    return wheels


def _install_check(
    bundle: Path, identity: dict[str, object], root: Path, tool_root: Path
) -> None:
    python = tool_root / "installs/python/cpython-3.14.6-windows-x86_64-none/python.exe"
    uv = tool_root / "installs/uv/0.11.33/uv.exe"
    if not python.is_file() or not uv.is_file():
        raise CandidateError("BND-INSTALL-TOOL", "pinned Python or uv is absent")
    temporary_root = root / ".tmp/candidate-install"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
        stage = Path(temporary)
        with ZipFile(bundle) as archive:
            archive.extractall(stage / "bundle")
        venv = stage / "venv"
        _run([str(python), "-m", "venv", str(venv)], root, "BND-INSTALL-VENV")
        wheels = sorted((stage / "bundle/wheels").glob("*.whl"))
        _run(
            [
                str(uv),
                "pip",
                "install",
                "--python",
                str(venv / "Scripts/python.exe"),
                "--offline",
                "--no-index",
                "--no-deps",
                *[str(path) for path in wheels],
            ],
            root,
            "BND-INSTALL-WHEELS",
        )
        wheel_items = cast(list[dict[str, object]], identity["wheels"])
        expected = {
            "versions": {
                cast(str, item["distribution"]): cast(str, item["version"])
                for item in wheel_items
            },
            "resources": {
                CREATOR_MANIFEST: cast(dict[str, object], identity["creator_static"])[
                    "manifest_sha256"
                ],
                SCHEMA_MANIFEST: cast(dict[str, object], identity["database_schema"])[
                    "manifest_sha256"
                ],
                COMPOSITION_MANIFEST: cast(
                    dict[str, object], identity["active_bindings"]
                )["manifest_sha256"],
            },
        }
        environment = {
            "ARMI_CANDIDATE_EXPECTED": json.dumps(expected, separators=(",", ":")),
            "PATH": os.pathsep.join(
                [str(venv / "Scripts"), str(Path(os.environ["WINDIR"]) / "System32")]
            ),
            "SYSTEMROOT": os.environ["SYSTEMROOT"],
            "WINDIR": os.environ["WINDIR"],
            "TEMP": str(stage),
            "TMP": str(stage),
        }
        _run(
            [str(venv / "Scripts/python.exe"), "-I", "-c", _INSTALL_CHECK],
            root,
            "BND-INSTALL-VERIFY",
            environment,
        )


def build(root: Path, tool_root: Path, output_dir: Path) -> dict[str, object]:
    revision, application_version = git_facts(root)
    uv = tool_root / "installs/uv/0.11.33/uv.exe"
    requirements = _export_requirements(root, uv)
    wheels = _quality_build(root, tool_root)
    final_revision, final_version = git_facts(root)
    if (final_revision, final_version) != (revision, application_version):
        raise CandidateError("BND-GIT-DRIFT", "workspace changed during build")
    wheel_files = [(f"wheels/{path.name}", path.read_bytes()) for path in wheels]
    lock_files = [
        ("uv-lock", "locks/uv.lock", (root / "uv.lock").read_bytes(), None),
        (
            "creator-package-lock",
            "locks/creator-package-lock.json",
            (root / "apps/armi-creator-web/package-lock.json").read_bytes(),
            None,
        ),
        (
            "toolchain-package-lock",
            "locks/toolchain-package-lock.json",
            (root / "tools/toolchain-node/package-lock.json").read_bytes(),
            None,
        ),
        (
            "runtime-requirements",
            "locks/runtime-requirements.txt",
            requirements,
            "locks/uv.lock",
        ),
    ]
    identity = build_identity(revision, wheel_files, lock_files)
    if identity["application_version"] != application_version:
        raise CandidateError("BND-VERSION", "workspace and wheel versions differ")
    bundle_id = cast(str, identity["bundle_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"armi-m0-{bundle_id[7:]}.zip"
    payloads = {path: data for path, data in wheel_files}
    payloads.update({path: data for _, path, data, _ in lock_files})
    temporary = output_dir / f".{destination.name}.tmp"
    if temporary.exists():
        temporary.unlink()
    write_deterministic_bundle(temporary, identity, payloads)
    verified = verify_bundle(temporary)
    _install_check(temporary, verified, root, tool_root)
    publish_candidate(temporary, destination)
    return {
        "bundle_id": bundle_id,
        "source_revision": revision,
        "bundle": str(destination.resolve()),
        "archive_sha256": sha256_file(destination),
    }


def verify(path: Path, root: Path, tool_root: Path) -> dict[str, object]:
    identity = verify_bundle(path)
    _install_check(path, identity, root, tool_root)
    return {
        "bundle_id": identity["bundle_id"],
        "source_revision": identity["source_revision"],
        "bundle": str(path.resolve()),
        "archive_sha256": sha256_file(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output-dir", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    tool_root = args.tool_root.resolve() if args.tool_root else root / ".armi-tools"
    try:
        if args.command == "build":
            output_dir = (
                args.output_dir.resolve()
                if args.output_dir
                else root / "dist/candidates"
            )
            result = build(root, tool_root, output_dir)
        else:
            result = verify(args.bundle.resolve(), root, tool_root)
    except CandidateError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
