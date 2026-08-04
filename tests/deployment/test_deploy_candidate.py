from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.candidate_bundle import canonical_bytes
from tools.deploy_candidate import (
    DEPLOYMENT_SCHEMA,
    DeploymentError,
    commit,
    deactivate,
    stage,
    status,
)

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
BUNDLE_ID = "sha256:" + "a" * 64
OTHER_BUNDLE_ID = "sha256:" + "b" * 64


def environment(root: Path) -> Path:
    target = root / "environment"
    target.mkdir()
    (target / "data").mkdir()
    (target / "secrets").mkdir()
    (target / "environment.toml").write_text(
        "\n".join(
            (
                "[environment]",
                f'environment_id = "{ENVIRONMENT_ID}"',
                f'data_root = "{(target / "data").as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    return target


def installation(root: Path, bundle_id: str = BUNDLE_ID) -> Path:
    target = root / "deployment" / "installations" / bundle_id[7:]
    (target / "venv/Scripts").mkdir(parents=True)
    (target / "venv/Scripts/pythonw.exe").write_bytes(b"python")
    return target


class DeploymentStateTests(unittest.TestCase):
    def test_initial_status_is_inactive(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary)
            environment_root = environment(root)
            observed = status(environment_root)

        self.assertIsNone(observed["active"])
        self.assertEqual(observed["generation"], 0)
        self.assertEqual(observed["pending_count"], 0)

    def test_stage_and_commit_publish_one_active_bundle(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary)
            environment_root = environment(root)
            install_root = installation(root)
            verified = {
                "status": "pass",
                "bundle_id": BUNDLE_ID,
                "source_revision": "0" * 40,
                "archive_sha256": "sha256:" + "1" * 64,
                "projection_sha256": "sha256:" + "2" * 64,
            }
            with patch(
                "tools.deploy_candidate.verify_installation", return_value=verified
            ):
                pending = stage(install_root, environment_root, expected_active="none")
            runtime = {
                "status": "running",
                "pid": 1234,
                "runtime": {
                    "runtime_state": "degraded",
                    "readiness": "ready",
                    "reason_codes": ["RUNTIME_MODEL_UNAVAILABLE"],
                },
            }
            with (
                patch(
                    "tools.deploy_candidate.verify_installation",
                    return_value=verified,
                ),
                patch("tools.deploy_candidate._runtime_status", return_value=runtime),
                patch(
                    "tools.deploy_candidate._windows_process_identity",
                    return_value=(
                        install_root / "venv/Scripts/pythonw.exe",
                        "S-1-5-21-123",
                    ),
                ),
            ):
                active = commit(
                    Path(pending["activation_id"]), runtime_sid="S-1-5-21-123"
                )

            observed = status(environment_root)

        self.assertEqual(active["status"], "active")
        self.assertEqual(observed["active"]["bundle_id"], BUNDLE_ID)
        self.assertEqual(observed["generation"], 1)

    def test_cross_bundle_stage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary)
            environment_root = environment(root)
            install_root = installation(root, OTHER_BUNDLE_ID)
            state_root = root / "deployment" / "environments" / ENVIRONMENT_ID
            state_root.mkdir(parents=True)
            (state_root / "active.json").write_bytes(
                canonical_bytes(
                    {
                        "schema_version": DEPLOYMENT_SCHEMA,
                        "environment_id": ENVIRONMENT_ID,
                        "generation": 1,
                        "active": {
                            "bundle_id": BUNDLE_ID,
                            "installation": f"installations/{BUNDLE_ID[7:]}",
                        },
                    }
                )
            )
            with (
                patch(
                    "tools.deploy_candidate.verify_installation",
                    return_value={"bundle_id": OTHER_BUNDLE_ID},
                ),
                self.assertRaises(DeploymentError) as raised,
            ):
                stage(install_root, environment_root, expected_active=BUNDLE_ID)

        self.assertEqual(raised.exception.code, "DEP-COMPATIBILITY-UNPROVEN")

    def test_deactivate_requires_stopped_runtime_and_preserves_state_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary)
            environment_root = environment(root)
            install_root = installation(root)
            state_root = root / "deployment" / "environments" / ENVIRONMENT_ID
            state_root.mkdir(parents=True)
            active = {
                "schema_version": DEPLOYMENT_SCHEMA,
                "environment_id": ENVIRONMENT_ID,
                "generation": 4,
                "active": {
                    "bundle_id": BUNDLE_ID,
                    "installation": f"installations/{BUNDLE_ID[7:]}",
                },
            }
            (state_root / "active.json").write_bytes(canonical_bytes(active))
            with patch(
                "tools.deploy_candidate._runtime_status",
                return_value={"status": "stopped", "pid": 1234},
            ):
                result = deactivate(environment_root, expected_active=BUNDLE_ID)
            stored = json.loads((state_root / "active.json").read_bytes())

        self.assertEqual(result, {"status": "inactive", "generation": 5})
        self.assertIsNone(stored["active"])
        self.assertTrue(install_root.name)


if __name__ == "__main__":
    unittest.main()
