"""SEC-SECRET-* coverage for v1 credential locators and preflight."""

from __future__ import annotations

import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from armi_kernel.application import CredentialLocator, CredentialPurpose
from armi_runtime.composition import (
    ConfigurationViolation,
    DeploymentProfile,
    EnvironmentFileCredentialPort,
    PreflightRequirements,
    load_effective_config,
    preflight_config,
)
from armi_runtime.composition.credential_scope import ScopedCredentialPort

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "configs/runtime.yaml"
ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


def _load(root: Path, locator_lines: str):
    environment_path = root / "environment.yaml"
    environment_path.write_text(
        (
            "environment:\n"
            f"  environment_id: {ENVIRONMENT_ID}\n"
            f'  data_root: "{root.as_posix()}"\n'
            "creator:\n"
            "  port: 43123\n"
            +
            (
                f"secret_locators:\n{locator_lines}"
                if locator_lines
                else "secret_locators: {}\n"
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    return load_effective_config(
        defaults_path=DEFAULTS,
        environment_path=environment_path,
        environment={},
    )


class SecretResolutionTests(unittest.TestCase):
    def test_scoped_port_requires_exact_purpose_and_locator_identity(self) -> None:
        approved = CredentialLocator.parse("env:ARMI_SECRET_DATABASE")
        other = CredentialLocator.parse("env:ARMI_SECRET_OTHER")
        delegate = EnvironmentFileCredentialPort(
            environment={
                "ARMI_SECRET_DATABASE": "database-value",
                "ARMI_SECRET_OTHER": "other-value",
            },
            secret_roots=(Path.cwd(),),
        )
        port = ScopedCredentialPort(
            delegate,
            allowed={"database.runtime": approved},
        )
        with port.resolve(approved, CredentialPurpose("database.runtime")) as handle:
            self.assertEqual(handle.consume(bytes), b"database-value")
        for locator, purpose in (
            (approved, CredentialPurpose("database.migrator")),
            (other, CredentialPurpose("database.runtime")),
        ):
            with self.subTest(locator=repr(locator), purpose=str(purpose)):
                with self.assertRaises(ConfigurationViolation) as raised:
                    port.resolve(locator, purpose)
                self.assertEqual(raised.exception.code, "SEC-SECRET-PURPOSE")

    def test_environment_locator_resolves_with_bounded_handle(self) -> None:
        value = "ephemeral-" + "credential"
        port = EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL": value},
            secret_roots=(Path.cwd(),),
        )
        handle = port.resolve(
            CredentialLocator.parse("env:ARMI_SECRET_MODEL"),
            CredentialPurpose("model.request"),
        )
        observed = handle.consume(lambda view: bytes(view).decode())
        self.assertEqual(observed, value)
        self.assertNotIn(value, repr(handle))
        handle.close()
        self.assertTrue(handle.closed)
        with self.assertRaises(ConfigurationViolation) as raised:
            handle.consume(bytes)
        self.assertEqual(raised.exception.code, "SEC-SECRET-CLOSED")

    def test_handle_zeroes_buffer_and_is_not_serializable(self) -> None:
        port = EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL": "erase-" + "this"},
            secret_roots=(Path.cwd(),),
        )
        handle = port.resolve(
            CredentialLocator.parse("env:ARMI_SECRET_MODEL"),
            CredentialPurpose("model.request"),
        )
        buffer = getattr(handle, "_" + "buffer")
        with self.assertRaises(TypeError):
            pickle.dumps(handle)
        handle.close()
        self.assertEqual(bytes(buffer), bytes(len(buffer)))

    def test_each_resolution_returns_a_distinct_handle(self) -> None:
        port = EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL": "one-" + "value"},
            secret_roots=(Path.cwd(),),
        )
        locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL")
        first = port.resolve(locator, CredentialPurpose("model.first"))
        second = port.resolve(locator, CredentialPurpose("model.second"))
        self.assertIsNot(first, second)
        first.close()
        self.assertFalse(second.closed)
        second.close()

    def test_environment_locator_negative_cases(self) -> None:
        port = EnvironmentFileCredentialPort(environment={}, secret_roots=(Path.cwd(),))
        cases = [
            ("env:NOT_APPROVED", "SEC-SECRET-ENV"),
            ("env:ARMI_SECRET_MISSING", "SEC-SECRET-MISSING"),
            ("command:registered-name", "SEC-SECRET-SCHEME"),
            ("os-store:registered-name", "SEC-SECRET-SCHEME"),
            ("vault:registered-name", "SEC-SECRET-SCHEME"),
        ]
        for raw, code in cases:
            with (
                self.subTest(raw=raw),
                self.assertRaises(ConfigurationViolation) as raised,
            ):
                port.resolve(
                    CredentialLocator.parse(raw),
                    CredentialPurpose("preflight.check"),
                )
            self.assertEqual(raised.exception.code, code)

    def test_empty_and_oversized_environment_values_are_rejected(self) -> None:
        for value, code in [
            ("", "SEC-SECRET-EMPTY"),
            ("x" * 65_537, "SEC-SECRET-SIZE"),
        ]:
            port = EnvironmentFileCredentialPort(
                environment={"ARMI_SECRET_MODEL": value},
                secret_roots=(Path.cwd(),),
            )
            with self.assertRaises(ConfigurationViolation) as raised:
                port.resolve(
                    CredentialLocator.parse("env:ARMI_SECRET_MODEL"),
                    CredentialPurpose("model.request"),
                )
            self.assertEqual(raised.exception.code, code)

    def test_file_locator_resolves_and_removes_one_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_path = root / "credential"
            value = b"short-lived-" + b"value"
            secret_path.write_bytes(value + b"\r\n")
            port = EnvironmentFileCredentialPort(
                environment={},
                secret_roots=(root,),
            )
            with port.resolve(
                CredentialLocator("file", str(secret_path)),
                CredentialPurpose("database.connect"),
            ) as handle:
                observed = handle.consume(bytes)
            self.assertEqual(observed, value)
            self.assertTrue(handle.closed)

    def test_file_locator_rejects_escape_directory_empty_and_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            allowed.mkdir()
            outside = root / "outside"
            outside.write_bytes(b"value")
            empty = allowed / "empty"
            empty.write_bytes(b"")
            large = allowed / "large"
            large.write_bytes(b"x" * 17)
            port = EnvironmentFileCredentialPort(
                environment={},
                secret_roots=(allowed,),
                maximum_bytes=16,
            )
            cases = [
                (outside, "SEC-SECRET-ROOT"),
                (allowed, "SEC-SECRET-FILE"),
                (empty, "SEC-SECRET-EMPTY"),
                (large, "SEC-SECRET-SIZE"),
            ]
            for path, code in cases:
                with (
                    self.subTest(code=code),
                    self.assertRaises(ConfigurationViolation) as raised,
                ):
                    port.resolve(
                        CredentialLocator("file", str(path)),
                        CredentialPurpose("preflight.check"),
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn(str(path), str(raised.exception))

    def test_reparse_point_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_path = root / "credential"
            secret_path.write_bytes(b"value")
            port = EnvironmentFileCredentialPort(
                environment={},
                secret_roots=(root,),
            )
            with (
                patch(
                    "armi_runtime.composition.configuration.secrets.has_reparse_point",
                    return_value=True,
                ),
                self.assertRaises(ConfigurationViolation) as raised,
            ):
                port.resolve(
                    CredentialLocator("file", str(secret_path)),
                    CredentialPurpose("preflight.check"),
                )
        self.assertEqual(raised.exception.code, "SEC-SECRET-REPARSE")

    def test_preflight_resolves_only_explicit_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective = _load(
                root,
                (
                    "  required: env:ARMI_SECRET_REQUIRED\n"
                    "  unused: env:ARMI_SECRET_UNUSED\n"
                ),
            )
            profile = DeploymentProfile.create(
                allowed_data_roots=(root,),
                allowed_secret_roots=(root,),
            )
            preflight_config(
                effective,
                profile=profile,
                requirements=PreflightRequirements(("required",)),
                environment={"ARMI_SECRET_REQUIRED": "available-" + "value"},
            )

    def test_preflight_rejects_missing_requirement_and_unsupported_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = DeploymentProfile.create(
                allowed_data_roots=(root,),
                allowed_secret_roots=(root,),
            )
            effective = _load(root, "  unused: env:ARMI_SECRET_UNUSED\n")
            with self.assertRaises(ConfigurationViolation) as missing:
                preflight_config(
                    effective,
                    profile=profile,
                    requirements=PreflightRequirements(("required",)),
                    environment={},
                )
            self.assertEqual(missing.exception.code, "SEC-SECRET-MISSING")
            unsupported = _load(root, "  future: command:future-provider\n")
            with self.assertRaises(ConfigurationViolation) as scheme:
                preflight_config(
                    unsupported,
                    profile=profile,
                    requirements=PreflightRequirements(),
                    environment={},
                )
            self.assertEqual(scheme.exception.code, "SEC-SECRET-SCHEME")

    def test_preflight_rejects_data_root_outside_trusted_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = root / "trusted"
            trusted.mkdir()
            actual = root / "actual"
            actual.mkdir()
            effective = _load(actual, "")
            profile = DeploymentProfile.create(
                allowed_data_roots=(trusted,),
                allowed_secret_roots=(trusted,),
            )
            with self.assertRaises(ConfigurationViolation) as raised:
                preflight_config(
                    effective,
                    profile=profile,
                    requirements=PreflightRequirements(),
                    environment={},
                )
        self.assertEqual(raised.exception.code, "CFG-DATA-ROOT")

    def test_safe_surfaces_never_render_secret_or_locator_target(self) -> None:
        value = "sensitive-" + "material"
        locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL")
        port = EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL": value},
            secret_roots=(Path.cwd(),),
        )
        handle = port.resolve(locator, CredentialPurpose("model.request"))
        rendered = f"{locator!r} {locator} {handle!r}"
        handle.close()
        self.assertNotIn(value, rendered)
        self.assertNotIn("ARMI_SECRET_MODEL", rendered)


if __name__ == "__main__":
    unittest.main()
