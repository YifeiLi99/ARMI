"""CON-CONFIG-* coverage for runtime-config v1."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from armi_runtime.composition import (
    ConfigurationViolation,
    RuntimeConfig,
    load_effective_config,
    schema_bytes,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "config/runtime.defaults.toml"
ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


def _environment_toml(data_root: Path, extra: str = "") -> str:
    return (
        "[environment]\n"
        f'environment_id = "{ENVIRONMENT_ID}"\n'
        f"data_root = {json.dumps(str(data_root))}\n"
        "\n[creator]\n"
        "port = 43123\n"
        f"{extra}"
    )


class RuntimeConfigurationTests(unittest.TestCase):
    def load(
        self,
        root: Path,
        *,
        extra: str = "",
        environment: dict[str, str] | None = None,
        raw: str | None = None,
    ):
        environment_path = root / "environment.toml"
        environment_path.write_text(
            raw if raw is not None else _environment_toml(root, extra),
            encoding="utf-8",
            newline="\n",
        )
        return load_effective_config(
            defaults_path=DEFAULTS,
            environment_path=environment_path,
            environment=environment or {},
        )

    def test_defaults_environment_and_explicit_override_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective = self.load(
                root,
                extra="\n[database]\npool_max = 20\n",
                environment={
                    "ARMI_DB_POOL_MAX": "24",
                    "ARMI_ARTIFACT_ORPHAN_GRACE_SECONDS": "172800",
                },
            )
        self.assertEqual(effective.config.database.pool_min, 2)
        self.assertEqual(effective.config.database.pool_max, 24)
        self.assertFalse(effective.config.model.semantic_recall_enabled)
        self.assertEqual(effective.config.artifacts.orphan_grace_seconds, 172_800)
        self.assertEqual(
            effective.applied_sources,
            ("defaults.toml", "environment.toml", "explicit-environment"),
        )

    def test_maintenance_window_defaults_overrides_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective = self.load(
                root,
                environment={
                    "ARMI_MAINTENANCE_CONSIDERATION_AFTER_SECONDS": "3600",
                    "ARMI_MAINTENANCE_DEADLINE_AFTER_SECONDS": "7200",
                },
            )
        self.assertEqual(effective.config.maintenance.consideration_after_seconds, 3600)
        self.assertEqual(effective.config.maintenance.deadline_after_seconds, 7200)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigurationViolation),
        ):
            self.load(
                Path(directory),
                environment={
                    "ARMI_MAINTENANCE_CONSIDERATION_AFTER_SECONDS": "7200",
                    "ARMI_MAINTENANCE_DEADLINE_AFTER_SECONDS": "7200",
                },
            )

    def test_observability_retention_defaults_overrides_and_watermarks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective = self.load(
                root,
                environment={
                    "ARMI_DB_MAINTENANCE_TIMEOUT_SECONDS": "600",
                    "ARMI_DIAGNOSTIC_ROTATION_MAX_BYTES": "1048576",
                    "ARMI_DIAGNOSTIC_RETENTION_SECONDS": "172800",
                    "ARMI_OBSERVABILITY_SAMPLE_INTERVAL_SECONDS": "5",
                    "ARMI_DISK_WARNING_FREE_BYTES": "2147483648",
                    "ARMI_DISK_CRITICAL_FREE_BYTES": "1073741824",
                },
            )
        self.assertEqual(
            effective.config.database.maintenance_statement_timeout_seconds,
            600,
        )
        self.assertEqual(effective.config.diagnostics.rotation_max_bytes, 1_048_576)
        self.assertEqual(effective.config.diagnostics.retention_seconds, 172_800)
        self.assertEqual(effective.config.observability.sample_interval_seconds, 5)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigurationViolation),
        ):
            self.load(
                Path(directory),
                environment={
                    "ARMI_DISK_WARNING_FREE_BYTES": "1073741824",
                    "ARMI_DISK_CRITICAL_FREE_BYTES": "1073741824",
                },
            )

    def test_environment_overrides_all_required_deployment_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment.toml"
            environment_path.write_text("", encoding="utf-8")
            effective = load_effective_config(
                defaults_path=DEFAULTS,
                environment_path=environment_path,
                environment={
                    "ARMI_ENVIRONMENT_ID": ENVIRONMENT_ID,
                    "ARMI_DATA_ROOT": str(root),
                    "ARMI_CREATOR_PORT": "43123",
                },
            )
        self.assertEqual(
            str(effective.config.environment.environment_id), ENVIRONMENT_ID
        )
        self.assertEqual(effective.config.creator.bind_host, "127.0.0.1")

    def test_digest_is_stable_and_excludes_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extra = '\n[secret_locators]\nmodel = "env:ARMI_SECRET_MODEL"\n'
            first = self.load(
                root,
                extra=extra,
                environment={"ARMI_SECRET_MODEL": "first-" + "value"},
            )
            second = self.load(
                root,
                extra=extra,
                environment={"ARMI_SECRET_MODEL": "second-" + "value"},
            )
        self.assertEqual(first.config, second.config)

    def test_redacted_view_hides_absolute_path_and_locator_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            effective = self.load(
                root,
                extra=('\n[secret_locators]\nmodel = "env:ARMI_SECRET_MODEL"\n'),
            )
            rendered = json.dumps(effective.redacted_view(), sort_keys=True)
        self.assertNotIn(str(root), rendered)
        self.assertNotIn("ARMI_SECRET_MODEL", rendered)
        self.assertIn("reference_digest", rendered)

    def test_runtime_schema_is_derived_from_the_code_contract(self) -> None:
        schema = json.loads(schema_bytes())
        self.assertEqual(schema["title"], "RuntimeConfig")
        self.assertIn("maintenance", schema["properties"])
        self.assertIn("diagnostics", schema["properties"])
        self.assertIn("observability", schema["properties"])

    def test_model_is_frozen_and_forbids_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            effective = self.load(Path(directory))
        with self.assertRaises(ValidationError):
            effective.config.creator.port = 5000
        mutable_locators = cast(dict[str, object], effective.config.secret_locators)
        with self.assertRaises(TypeError):
            mutable_locators["new"] = "env:ARMI_SECRET_NEW"
        payload = effective.config.model_dump(mode="json")
        payload["unknown"] = True
        with self.assertRaises(ValidationError):
            RuntimeConfig.model_validate(payload)

    def test_unknown_armi_environment_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigurationViolation) as raised,
        ):
            self.load(
                Path(directory),
                environment={"ARMI_UNREGISTERED_SETTING": "1"},
            )
        self.assertEqual(raised.exception.code, "CFG-UNKNOWN-ENV")

    def test_secret_namespace_is_not_a_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            effective = self.load(
                Path(directory),
                environment={"ARMI_SECRET_UNUSED": "runtime-" + "only"},
            )
        self.assertEqual(effective.config.secret_locators, {})

    def test_malformed_toml_is_safely_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigurationViolation) as raised,
        ):
            self.load(Path(directory), raw="[environment")
        self.assertEqual(raised.exception.code, "CFG-TOML")
        self.assertNotIn(str(directory), str(raised.exception))

    def test_plaintext_sensitive_key_is_rejected_without_value(self) -> None:
        sensitive_value = "do-not-" + "expose"
        sensitive_key = "pass" + "word"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = _environment_toml(
                root,
                f'\n[database]\n{sensitive_key} = "{sensitive_value}"\n',
            )
            with self.assertRaises(ConfigurationViolation) as raised:
                self.load(root, raw=raw)
        self.assertEqual(raised.exception.code, "CFG-SECRET-PLAINTEXT")
        self.assertNotIn(sensitive_value, str(raised.exception))

    def test_missing_required_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment_path = root / "environment.toml"
            environment_path.write_text("", encoding="utf-8")
            with self.assertRaises(ConfigurationViolation) as raised:
                load_effective_config(
                    defaults_path=DEFAULTS,
                    environment_path=environment_path,
                    environment={},
                )
        self.assertEqual(raised.exception.code, "CFG-MISSING")

    def test_missing_environment_file_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConfigurationViolation) as raised,
        ):
            load_effective_config(
                defaults_path=DEFAULTS,
                environment_path=Path(directory) / "missing.toml",
                environment={},
            )
        self.assertEqual(raised.exception.code, "CFG-FILE")

    def test_uuid_port_path_and_strict_integer_rules(self) -> None:
        cases = [
            _environment_toml(Path("relative"), ""),
            _environment_toml(Path.cwd()).replace(
                ENVIRONMENT_ID, ENVIRONMENT_ID.upper()
            ),
            _environment_toml(Path.cwd()).replace(
                ENVIRONMENT_ID, "00000000-0000-4000-8000-000000000000"
            ),
            _environment_toml(Path.cwd()).replace("port = 43123", "port = 1000"),
            _environment_toml(Path.cwd(), "\n[database]\npool_min = true\n"),
        ]
        for raw in cases:
            with (
                self.subTest(raw=raw[:40]),
                tempfile.TemporaryDirectory() as directory,
                self.assertRaises(ConfigurationViolation),
            ):
                self.load(Path(directory), raw=raw)

    def test_fixed_numeric_relations_are_rejected(self) -> None:
        fragments = [
            "\n[database]\npool_min = 13\npool_max = 12\n",
            "\n[runtime]\nlease_seconds = 30\nheartbeat_seconds = 15\n",
            "\n[work]\nlease_seconds = 60\nheartbeat_seconds = 30\n",
            "\n[web]\nstep_timeout_seconds = 90\ntotal_timeout_seconds = 90\n",
            "\n[scheduler]\nidle_poll_initial_seconds = 11\nidle_poll_max_seconds = 10\n",
            "\n[codex]\ntotal_timeout_seconds = 3600\n",
        ]
        for fragment in fragments:
            with (
                self.subTest(fragment=fragment),
                tempfile.TemporaryDirectory() as directory,
            ):
                with self.assertRaises(ConfigurationViolation) as raised:
                    self.load(Path(directory), extra=fragment)
                self.assertEqual(raised.exception.code, "CFG-RELATION")

    def test_unsigned_decimal_environment_rule(self) -> None:
        invalid = ["-1", "+1", " 1", "1.0", "true"]
        for value in invalid:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ConfigurationViolation) as raised:
                    self.load(
                        Path(directory),
                        environment={"ARMI_DB_POOL_MAX": value},
                    )
                self.assertEqual(raised.exception.code, "CFG-ENV-TYPE")

    @settings(max_examples=20, deadline=None)
    @given(st.integers(min_value=2, max_value=1000))
    def test_unsigned_pool_override_property(self, pool_max: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            effective = self.load(
                Path(directory),
                environment={"ARMI_DB_POOL_MAX": str(pool_max)},
            )
        self.assertEqual(effective.config.database.pool_max, pool_max)


if __name__ == "__main__":
    unittest.main()
