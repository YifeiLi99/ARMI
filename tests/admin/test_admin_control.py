from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from armi_admin.application import AdminConfig, AdminControlPlane, AdminCredentialPort
from armi_runtime.composition.admin_control import (
    RuntimeAdminControlServer,
    RuntimeAdminInjectedFault,
)

ENVIRONMENT_ID = "018f3f4a-7b8c-7def-8abc-1234567890ab"
DIGEST = "sha256:" + "1" * 64


def _config(root: Path) -> AdminConfig:
    template = root / "template.json"
    template.write_text(
        json.dumps(
            {
                "schema_version": "armi.admin-experiment-environment.v1",
                "environment_id": ENVIRONMENT_ID,
            }
        ),
        encoding="utf-8",
    )
    environment = root / "environment"
    environment.mkdir()
    (environment / "environment.toml").write_text("fixture = true\n", encoding="utf-8")
    return AdminConfig.model_validate(
        {
            "schema_version": "armi.admin-config.v4",
            "environment_kind": "system_test",
            "environment_id": ENVIRONMENT_ID,
            "environment_incarnation": 3,
            "resettable": True,
            "test_controls_enabled": True,
            "environment_root": environment,
            "experiment_root": root,
            "template_manifest": template,
            "postgresql_client_root": root / "postgresql",
            "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
            "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
            "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
            "expected": {
                "package_digest": DIGEST,
            },
        }
    )


class AdminResetPreviewTests(unittest.TestCase):
    def test_preview_is_session_environment_and_state_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = _config(root)
            credentials = AdminCredentialPort(
                locator=config.locator,
                migrator_locator=config.migrator_locator,
                preview_locator=config.preview_locator,
                config_root=root,
                environ={
                    "ARMI_SECRET_ADMIN_DATABASE": "unused",
                    "ARMI_SECRET_MIGRATOR_DATABASE": "unused",
                    "ARMI_SECRET_ADMIN_PREVIEW_KEY": "preview-key-for-tests",
                },
            )
            control = AdminControlPlane(config, credentials)
            with patch.object(
                AdminControlPlane,
                "_database_catalog_digest",
                return_value=DIGEST,
            ):
                preview = control.preview_reset()
                payload = control.validate_reset(str(preview["preview_token"]))
            self.assertEqual(payload["environment_id"], ENVIRONMENT_ID)
            self.assertEqual(payload["incarnation"], 3)
            (config.environment_root / "changed").write_text(
                "changed", encoding="utf-8"
            )
            with (
                patch.object(
                    AdminControlPlane,
                    "_database_catalog_digest",
                    return_value=DIGEST,
                ),
                self.assertRaisesRegex(RuntimeError, "ADMIN-RESET-PREVIEW-STALE"),
            ):
                control.validate_reset(str(preview["preview_token"]))


class RuntimeControlProtocolTests(unittest.TestCase):
    def test_internal_dispatch_error_is_not_reported_as_protocol_rejection(
        self,
    ) -> None:
        async def exercise(root: Path) -> None:
            run_root = root / "run" / "admin-control"
            run_root.mkdir(parents=True)
            token = "a" * 43
            digest = f"sha256:{hashlib.sha256(token.encode()).hexdigest()}"
            (run_root / "runtime-control.token").write_text(token, encoding="utf-8")
            (run_root / "runtime-control.manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "armi.runtime-admin-control.v1",
                        "environment_id": ENVIRONMENT_ID,
                        "incarnation": 3,
                        "descriptor": "runtime-control.json",
                        "token": "runtime-control.token",
                        "token_digest": digest,
                    }
                ),
                encoding="utf-8",
            )

            def fail_status() -> dict[str, object]:
                raise RuntimeError("internal status defect")

            server = RuntimeAdminControlServer(
                run_root=run_root,
                environment_id=ENVIRONMENT_ID,
                incarnation=3,
                instance_id="0198f3f4-7b8c-7def-8abc-1234567890ab",
                on_status=fail_status,
                on_drain=lambda: None,
                on_stop=lambda: None,
                on_input=None,
            )
            await server.start()
            descriptor = json.loads((run_root / "runtime-control.json").read_bytes())
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", descriptor["port"]
            )
            request = json.dumps(
                {
                    "schema_version": "armi.runtime-admin-control.v1",
                    "request_id": "0198f3f4-7b8c-7def-9abc-1234567890ab",
                    "environment_id": ENVIRONMENT_ID,
                    "incarnation": 3,
                    "instance_id": "0198f3f4-7b8c-7def-8abc-1234567890ab",
                    "token": token,
                    "command": "status",
                    "arguments": {},
                },
                separators=(",", ":"),
            ).encode()
            writer.write(struct.pack(">I", len(request)) + request)
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await reader.readexactly(4)
            writer.close()
            await writer.wait_closed()
            await server.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))

    def test_framed_status_and_stop_are_strict(self) -> None:
        async def exercise(root: Path) -> tuple[dict[str, object], bool]:
            run_root = root / "run" / "admin-control"
            run_root.mkdir(parents=True)
            token = "a" * 43
            digest = f"sha256:{hashlib.sha256(token.encode()).hexdigest()}"
            (run_root / "runtime-control.token").write_text(token, encoding="utf-8")
            (run_root / "runtime-control.manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "armi.runtime-admin-control.v1",
                        "environment_id": ENVIRONMENT_ID,
                        "incarnation": 3,
                        "descriptor": "runtime-control.json",
                        "token": "runtime-control.token",
                        "token_digest": digest,
                    }
                ),
                encoding="utf-8",
            )
            stopped = False

            def stop() -> None:
                nonlocal stopped
                stopped = True

            server = RuntimeAdminControlServer(
                run_root=run_root,
                environment_id=ENVIRONMENT_ID,
                incarnation=3,
                instance_id="0198f3f4-7b8c-7def-8abc-1234567890ab",
                on_status=lambda: {"runtime_state": "ready"},
                on_drain=lambda: None,
                on_stop=stop,
                on_input=None,
            )
            await server.start()
            descriptor = json.loads((run_root / "runtime-control.json").read_bytes())
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", descriptor["port"]
            )
            request = json.dumps(
                {
                    "schema_version": "armi.runtime-admin-control.v1",
                    "request_id": "0198f3f4-7b8c-7def-9abc-1234567890ab",
                    "environment_id": ENVIRONMENT_ID,
                    "incarnation": 3,
                    "instance_id": "0198f3f4-7b8c-7def-8abc-1234567890ab",
                    "token": token,
                    "command": "stop",
                    "arguments": {},
                },
                separators=(",", ":"),
            ).encode()
            writer.write(struct.pack(">I", len(request)) + request)
            await writer.drain()
            size = struct.unpack(">I", await reader.readexactly(4))[0]
            response = json.loads(await reader.readexactly(size))
            writer.close()
            await writer.wait_closed()
            await server.close()
            return response, stopped

        with tempfile.TemporaryDirectory() as directory:
            response, stopped = asyncio.run(exercise(Path(directory)))
        self.assertEqual(response["status"], "succeeded")
        self.assertTrue(stopped)

    def test_server_is_default_off_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(RuntimeAdminControlServer.configured(Path(directory)))

    def test_fault_is_bounded_and_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_root = root / "run" / "admin-control"
            run_root.mkdir(parents=True)
            token = "a" * 43
            digest = f"sha256:{hashlib.sha256(token.encode()).hexdigest()}"
            (run_root / "runtime-control.token").write_text(token, encoding="utf-8")
            (run_root / "runtime-control.manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "armi.runtime-admin-control.v1",
                        "environment_id": ENVIRONMENT_ID,
                        "incarnation": 3,
                        "descriptor": "runtime-control.json",
                        "token": "runtime-control.token",
                        "token_digest": digest,
                    }
                ),
                encoding="utf-8",
            )
            server = RuntimeAdminControlServer(
                run_root=run_root,
                environment_id=ENVIRONMENT_ID,
                incarnation=3,
                instance_id="0198f3f4-7b8c-7def-8abc-1234567890ab",
                on_status=lambda: {"runtime_state": "ready"},
                on_drain=lambda: None,
                on_stop=lambda: None,
                on_input=None,
            )
            server._fault(  # pyright: ignore[reportPrivateUsage]
                {
                    "action": "arm",
                    "fault": "subject_before_cas",
                    "duration_seconds": 60,
                }
            )
            with self.assertRaisesRegex(
                RuntimeAdminInjectedFault, "ADMIN-FAULT-INJECTED"
            ):
                server.trigger_fault("subject_before_cas")
            server.trigger_fault("subject_before_cas")


if __name__ == "__main__":
    unittest.main()
