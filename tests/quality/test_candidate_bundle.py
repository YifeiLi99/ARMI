"""Contract tests for the content-addressed M0 candidate bundle."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import warnings
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from tools.build_candidate import git_facts, publish_candidate
from tools.candidate_bundle import (
    COMPOSITION_MANIFEST,
    CREATOR_PREFIX,
    CandidateError,
    build_identity,
    canonical_bytes,
    verify_bundle,
    write_deterministic_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_RESOURCES = (
    ROOT / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources"
)
CREATOR_RESOURCES = (
    ROOT / "apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources"
)
REVISION = "1" * 40


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return output.getvalue()


def _metadata(distribution: str) -> bytes:
    return f"Metadata-Version: 2.4\nName: {distribution}\nVersion: 0.0.0\n".encode()


def _entry_points(distribution: str) -> bytes | None:
    entries = {
        "armi-admin": "armi-admin-mcp = armi_admin.mcp.entrypoint:main\n",
        "armi-runtime": (
            "armi = armi_runtime.cli:main\n"
            "armi-codex-runner = armi_runtime.codex_runner_cli:main\n"
        ),
    }
    value = entries.get(distribution)
    return f"[console_scripts]\n{value}\n".encode() if value else None


def _wheel(distribution: str) -> bytes:
    normalized = distribution.replace("-", "_")
    dist_info = f"{normalized}-0.0.0.dist-info"
    files = {f"{dist_info}/METADATA": _metadata(distribution)}
    entries = _entry_points(distribution)
    if entries is not None:
        files[f"{dist_info}/entry_points.txt"] = entries
    if distribution == "armi-runtime":
        for path in CREATOR_RESOURCES.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                relative = path.relative_to(CREATOR_RESOURCES).as_posix()
                files[f"{CREATOR_PREFIX}{relative}"] = path.read_bytes()
        for path in (RUNTIME_RESOURCES / "schema").rglob("*"):
            if path.is_file():
                relative = path.relative_to(RUNTIME_RESOURCES).as_posix()
                files[f"armi_runtime/composition/runtime_resources/{relative}"] = (
                    path.read_bytes()
                )
        files[COMPOSITION_MANIFEST] = (
            RUNTIME_RESOURCES / "runtime-composition.manifest.json"
        ).read_bytes()
    return _zip_bytes(files)


def _fixture() -> tuple[dict[str, object], dict[str, bytes]]:
    wheel_files = [
        (f"wheels/{name.replace('-', '_')}-0.0.0-py3-none-any.whl", _wheel(name))
        for name in ("armi-admin", "armi-kernel", "armi-runtime")
    ]
    lock_files: list[tuple[str, str, bytes, str | None]] = [
        ("uv-lock", "locks/uv.lock", b"version = 1\n", None),
        ("creator-package-lock", "locks/creator-package-lock.json", b"{}\n", None),
        (
            "toolchain-package-lock",
            "locks/toolchain-package-lock.json",
            b"{}\n",
            None,
        ),
        (
            "runtime-requirements",
            "locks/runtime-requirements.txt",
            b"httpx==1.0.0 --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            "locks/uv.lock",
        ),
    ]
    identity = build_identity(REVISION, wheel_files, lock_files)
    payloads = {path: data for path, data in wheel_files}
    payloads.update({path: data for _, path, data, _ in lock_files})
    return identity, payloads


def _rewrite_bundle(
    source: Path, destination: Path, mutate: Callable[[dict[str, bytes]], None]
) -> None:
    with ZipFile(source) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    mutate(members)
    with ZipFile(destination, "w", compression=ZIP_STORED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)


class CandidateBundleTests(unittest.TestCase):
    def test_identity_and_archive_are_deterministic_and_recomputable(self) -> None:
        identity, payloads = _fixture()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            write_deterministic_bundle(first, identity, payloads)
            write_deterministic_bundle(second, identity, payloads)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(verify_bundle(first), identity)
        self.assertEqual(identity["schema_version"], "armi.bundle-identity.v1")
        self.assertEqual(identity["application_version"], "0.0.0")
        self.assertNotIn("timestamp", identity)

    def test_tampered_lock_and_extra_member_are_rejected(self) -> None:
        identity, payloads = _fixture()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            root = Path(temporary)
            source = root / "candidate.zip"
            write_deterministic_bundle(source, identity, payloads)
            tampered = root / "tampered.zip"
            _rewrite_bundle(
                source,
                tampered,
                lambda members: members.__setitem__("locks/uv.lock", b"changed\n"),
            )
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(tampered)
            self.assertEqual(raised.exception.code, "BND-ARTIFACT-SIZE")
            extra = root / "extra.zip"
            _rewrite_bundle(
                source,
                extra,
                lambda members: members.__setitem__("unexpected.txt", b"extra\n"),
            )
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(extra)
            self.assertEqual(raised.exception.code, "BND-ARCHIVE-SET")

    def test_tampered_identity_wheel_and_duplicate_member_are_rejected(self) -> None:
        identity, payloads = _fixture()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            root = Path(temporary)
            source = root / "candidate.zip"
            write_deterministic_bundle(source, identity, payloads)
            identity_drift = root / "identity-drift.zip"

            def drift_identity(members: dict[str, bytes]) -> None:
                document = json.loads(members["bundle-identity.json"])
                document["application_version"] = "0.0.1"
                members["bundle-identity.json"] = canonical_bytes(document)

            _rewrite_bundle(source, identity_drift, drift_identity)
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(identity_drift)
            self.assertEqual(raised.exception.code, "BND-IDENTITY-ID")
            wheel_drift = root / "wheel-drift.zip"

            def drift_wheel(members: dict[str, bytes]) -> None:
                wheel = next(name for name in members if name.endswith(".whl"))
                members[wheel] = members[wheel][:-1] + bytes([members[wheel][-1] ^ 1])

            _rewrite_bundle(source, wheel_drift, drift_wheel)
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(wheel_drift)
            self.assertEqual(raised.exception.code, "BND-ARTIFACT-DIGEST")
            duplicate = root / "duplicate.zip"
            duplicate.write_bytes(source.read_bytes())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(duplicate, "a", compression=ZIP_STORED) as archive:
                    archive.writestr("bundle-identity.json", canonical_bytes(identity))
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(duplicate)
            self.assertEqual(raised.exception.code, "BND-ARCHIVE-PATH")

    def test_path_traversal_and_secret_are_rejected(self) -> None:
        identity, payloads = _fixture()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            root = Path(temporary)
            source = root / "candidate.zip"
            write_deterministic_bundle(source, identity, payloads)
            traversal = root / "traversal.zip"
            _rewrite_bundle(
                source,
                traversal,
                lambda members: members.__setitem__("../escape", b"bad"),
            )
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(traversal)
            self.assertEqual(raised.exception.code, "BND-ARCHIVE-PATH")
            payloads["locks/runtime-requirements.txt"] += b"sk-" + b"A" * 24
            unsafe_locks = _fixture_locks()
            unsafe_locks[-1] = (
                "runtime-requirements",
                "locks/runtime-requirements.txt",
                payloads["locks/runtime-requirements.txt"],
                "locks/uv.lock",
            )
            unsafe_identity = build_identity(
                REVISION,
                [
                    (path, data)
                    for path, data in payloads.items()
                    if path.endswith(".whl")
                ],
                unsafe_locks,
            )
            unsafe = root / "unsafe.zip"
            write_deterministic_bundle(unsafe, unsafe_identity, payloads)
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(unsafe)
            self.assertEqual(raised.exception.code, "SEC-SECRET-TOKEN")

    def test_old_runtime_entry_and_missing_latest_migration_are_rejected(self) -> None:
        runtime = _wheel("armi-runtime")
        with ZipFile(io.BytesIO(runtime)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        entry = next(name for name in files if name.endswith("entry_points.txt"))
        files[entry] = b"[console_scripts]\narmi = armi_runtime.cli:main\n\n"
        with self.assertRaises(CandidateError) as raised:
            build_identity(
                REVISION,
                [
                    ("wheels/admin.whl", _wheel("armi-admin")),
                    ("wheels/kernel.whl", _wheel("armi-kernel")),
                    ("wheels/runtime.whl", _zip_bytes(files)),
                ],
                _fixture_locks(),
            )
        self.assertEqual(raised.exception.code, "BND-WHEEL-ENTRY")
        files[entry] = _entry_points("armi-runtime") or b""
        latest = next(
            name
            for name in files
            if name.endswith("0027_creator_dialogue_candidate_profile.sql")
        )
        del files[latest]
        with self.assertRaises(CandidateError) as raised:
            build_identity(
                REVISION,
                [
                    ("wheels/admin.whl", _wheel("armi-admin")),
                    ("wheels/kernel.whl", _wheel("armi-kernel")),
                    ("wheels/runtime.whl", _zip_bytes(files)),
                ],
                _fixture_locks(),
            )
        self.assertEqual(raised.exception.code, "DB-MANIFEST-DRIFT")

    def test_source_map_and_absolute_runtime_requirement_are_rejected(self) -> None:
        runtime = _wheel("armi-runtime")
        with ZipFile(io.BytesIO(runtime)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files[f"{CREATOR_PREFIX}static/assets/forbidden.js.map"] = b"{}"
        with self.assertRaises(CandidateError) as raised:
            build_identity(
                REVISION,
                [
                    ("wheels/admin.whl", _wheel("armi-admin")),
                    ("wheels/kernel.whl", _wheel("armi-kernel")),
                    ("wheels/runtime.whl", _zip_bytes(files)),
                ],
                _fixture_locks(),
            )
        self.assertEqual(raised.exception.code, "BND-WHEEL-FORBIDDEN")
        _, payloads = _fixture()
        unsafe_locks = _fixture_locks()
        unsafe_locks[-1] = (
            "runtime-requirements",
            "locks/runtime-requirements.txt",
            b"demo @ C:\\build\\demo.whl\n",
            "locks/uv.lock",
        )
        wheel_files = [
            (path, data) for path, data in payloads.items() if path.endswith(".whl")
        ]
        unsafe_identity = build_identity(REVISION, wheel_files, unsafe_locks)
        unsafe_payloads = {path: data for path, data in wheel_files}
        unsafe_payloads.update({path: data for _, path, data, _ in unsafe_locks})
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            bundle = Path(temporary) / "absolute.zip"
            write_deterministic_bundle(bundle, unsafe_identity, unsafe_payloads)
            with self.assertRaises(CandidateError) as raised:
                verify_bundle(bundle)
        self.assertEqual(raised.exception.code, "BND-LOCK-LOCAL")

    def test_active_web_binding_drift_is_rejected(self) -> None:
        runtime = _wheel("armi-runtime")
        with ZipFile(io.BytesIO(runtime)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        composition = json.loads(files[COMPOSITION_MANIFEST])
        web = next(
            item for item in composition["seams"] if item["seam_id"] == "M0-SEAM-WEB"
        )
        web["active_binding"] = "armi.web.forbidden-v1"
        files[COMPOSITION_MANIFEST] = json.dumps(
            composition, sort_keys=True, separators=(",", ":")
        ).encode()
        with self.assertRaises(CandidateError) as raised:
            build_identity(
                REVISION,
                [
                    ("wheels/admin.whl", _wheel("armi-admin")),
                    ("wheels/kernel.whl", _wheel("armi-kernel")),
                    ("wheels/runtime.whl", _zip_bytes(files)),
                ],
                _fixture_locks(),
            )
        self.assertEqual(raised.exception.code, "BND-BINDING-WEB")

    def test_dirty_workspace_and_candidate_collision_are_stable_failures(self) -> None:
        with (
            patch("tools.build_candidate._run", return_value=" M tracked.py"),
            self.assertRaises(CandidateError) as raised,
        ):
            git_facts(ROOT)
        self.assertEqual(raised.exception.code, "BND-GIT-DIRTY")
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            root = Path(temporary)
            temporary_file = root / "candidate.tmp"
            destination = root / "candidate.zip"
            destination.write_bytes(b"first")
            temporary_file.write_bytes(b"second")
            with self.assertRaises(CandidateError) as raised:
                publish_candidate(temporary_file, destination)
            self.assertEqual(raised.exception.code, "BND-COLLISION")
            temporary_file.write_bytes(b"first")
            publish_candidate(temporary_file, destination)
            self.assertFalse(temporary_file.exists())


def _fixture_locks() -> list[tuple[str, str, bytes, str | None]]:
    return [
        ("uv-lock", "locks/uv.lock", b"version = 1\n", None),
        ("creator-package-lock", "locks/creator-package-lock.json", b"{}\n", None),
        (
            "toolchain-package-lock",
            "locks/toolchain-package-lock.json",
            b"{}\n",
            None,
        ),
        (
            "runtime-requirements",
            "locks/runtime-requirements.txt",
            b"httpx==1.0.0 --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            "locks/uv.lock",
        ),
    ]


if __name__ == "__main__":
    unittest.main()
