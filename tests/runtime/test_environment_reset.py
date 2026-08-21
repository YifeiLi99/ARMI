from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import UUID

from armi_runtime.adapters.database_errors import DatabaseViolation
from armi_runtime.composition.environment import PreparedEnvironment
from armi_runtime.composition.environment_reset import reset_environment


class EnvironmentResetTests(unittest.TestCase):
    def _prepared(self, root: Path) -> PreparedEnvironment:
        data_root = root / "data"
        data_root.mkdir()
        for name in ("artifacts", "backups", "codex-runner", "exports", "logs"):
            target = data_root / name
            target.mkdir()
            (target / "old-state").write_text("old", encoding="utf-8")
        run = root / "run"
        run.mkdir()
        (run / "runtime-state").write_text("old", encoding="utf-8")
        for name in ("secrets", "models", "tools", "channels"):
            preserved = root / name
            preserved.mkdir()
            (preserved / "keep").write_text("configured", encoding="utf-8")
        return cast(
            PreparedEnvironment,
            SimpleNamespace(
                root=root,
                data_root=data_root,
                effective=SimpleNamespace(
                    config=SimpleNamespace(
                        environment=SimpleNamespace(
                            environment_id=UUID("019fe49a-bee7-751b-a6b4-370671749831")
                        ),
                        model=SimpleNamespace(semantic_recall_enabled=True),
                    ),
                ),
            ),
        )

    def test_reset_stops_rebuilds_clears_and_births(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared = self._prepared(Path(directory))
            process = Mock()
            semantic = Mock()
            birth = Mock()
            birth.safe_view.return_value = {"status": "born"}
            with (
                patch(
                    "armi_runtime.composition.environment_reset.RuntimeProcessManager",
                    return_value=process,
                ),
                patch(
                    "armi_runtime.composition.environment_reset.SemanticRecallProcessManager",
                    return_value=semantic,
                ),
                patch(
                    "armi_runtime.composition.environment_reset.reset_operator_schema"
                ) as reset_schema,
                patch(
                    "armi_runtime.composition.environment_reset.install_operator_schema"
                ) as install_schema,
                patch(
                    "armi_runtime.composition.environment_reset.execute_birth",
                    return_value=birth,
                ) as execute_birth,
            ):
                result = reset_environment(prepared)

            process.stop.assert_called_once_with()
            semantic.stop.assert_called_once_with()
            reset_schema.assert_called_once_with(prepared)
            install_schema.assert_called_once_with(prepared)
            execute_birth.assert_called_once_with(prepared)
            self.assertEqual(result.safe_view()["birth"], {"status": "born"})
            for target in (
                *(
                    prepared.data_root / name
                    for name in (
                        "artifacts",
                        "backups",
                        "codex-runner",
                        "exports",
                        "logs",
                    )
                ),
                prepared.root / "run",
            ):
                self.assertEqual(list(target.iterdir()), [])
            for name in ("secrets", "models", "tools", "channels"):
                self.assertEqual(
                    (prepared.root / name / "keep").read_text(encoding="utf-8"),
                    "configured",
                )

    def test_database_reset_failure_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared = self._prepared(Path(directory))
            with (
                patch(
                    "armi_runtime.composition.environment_reset.RuntimeProcessManager"
                ) as process,
                patch(
                    "armi_runtime.composition.environment_reset.SemanticRecallProcessManager"
                ),
                patch(
                    "armi_runtime.composition.environment_reset.reset_operator_schema",
                    side_effect=DatabaseViolation("DB-SCHEMA-RESET-FAILED", "failed"),
                ),
                patch(
                    "armi_runtime.composition.environment_reset.execute_birth"
                ) as execute_birth,
                self.assertRaises(DatabaseViolation),
            ):
                reset_environment(prepared)

            process.return_value.stop.assert_called_once_with()
            execute_birth.assert_not_called()
            self.assertTrue((prepared.data_root / "artifacts" / "old-state").is_file())


if __name__ == "__main__":
    unittest.main()
