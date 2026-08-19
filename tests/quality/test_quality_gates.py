"""Prove stable failures for type, format, secret, and aggregation gates."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from tools.check_repository_hygiene import scan_paths
from tools.quality import (
    Gate,
    GateResult,
    aggregate_exit_code,
    run_gate,
    workspace_distribution_names,
)

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / ".venv/Scripts/python.exe"
TOOL_ROOT = Path(os.environ.get("ARMI_TOOL_ROOT", ROOT / ".armi-tools"))
NODE = TOOL_ROOT / "installs/node/node-v24.18.0-win-x64/node.exe"


class QualityGateTests(unittest.TestCase):
    def run_sample(self, gate: Gate):
        return run_gate(gate, os.environ.copy())

    def test_earlier_failure_cannot_be_masked(self) -> None:
        results = [
            GateResult("PY-TYPE", "fail", 1, "injected failure"),
            GateResult("PY-TEST", "pass", 0, ""),
        ]
        self.assertEqual(aggregate_exit_code(results), 1)

    def test_missing_tool_is_blocked(self) -> None:
        missing = ROOT / ".tmp/quality/does-not-exist.exe"
        result = self.run_sample(Gate("QLT-MISSING", ("unused",), ROOT, (missing,)))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(aggregate_exit_code([result]), 2)

    def test_python_format_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "bad.py"
            sample.write_text("value={  'a':1}\n", encoding="utf-8")
            result = self.run_sample(
                Gate(
                    "PY-FORMAT",
                    (
                        str(VENV_PYTHON),
                        "-m",
                        "ruff",
                        "format",
                        "--check",
                        str(sample),
                    ),
                    ROOT,
                    (VENV_PYTHON,),
                )
            )
        self.assertEqual(result.gate_id, "PY-FORMAT")
        self.assertEqual(result.status, "fail")

    def test_python_type_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.py").write_text("value: str = 1\n", encoding="utf-8")
            (root / "pyrightconfig.json").write_text(
                '{"include":["bad.py"],"typeCheckingMode":"strict"}\n',
                encoding="utf-8",
            )
            pyright = ROOT / "tools/toolchain-node/node_modules/pyright/index.js"
            result = self.run_sample(
                Gate(
                    "PY-TYPE",
                    (
                        str(NODE),
                        str(pyright),
                        "--project",
                        str(root / "pyrightconfig.json"),
                    ),
                    ROOT,
                    (NODE, pyright),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_typescript_type_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.ts").write_text("const value: string = 1;\n", encoding="utf-8")
            (root / "tsconfig.json").write_text(
                '{"compilerOptions":{"strict":true,"noEmit":true},'
                '"include":["bad.ts"]}\n',
                encoding="utf-8",
            )
            tsc = ROOT / "apps/armi-creator-web/node_modules/typescript/bin/tsc"
            result = self.run_sample(
                Gate(
                    "WEB-TYPE",
                    (
                        str(NODE),
                        str(tsc),
                        "--project",
                        str(root / "tsconfig.json"),
                    ),
                    ROOT,
                    (NODE, tsc),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_frontend_format_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "bad.ts"
            sample.write_text("const value={a:1}\n", encoding="utf-8")
            prettier = (
                ROOT / "apps/armi-creator-web/node_modules/prettier/bin/prettier.cjs"
            )
            result = self.run_sample(
                Gate(
                    "WEB-FORMAT",
                    (str(NODE), str(prettier), "--check", str(sample)),
                    ROOT,
                    (NODE, prettier),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_dynamic_secret_and_personal_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = "sk" + "-" + "A" * 24
            personal = "C:" + "\\Us" + "ers\\example\\file.txt"
            sample = root / "sample.txt"
            sample.write_text(f"{secret}\n{personal}\n", encoding="utf-8")
            codes = {item.code for item in scan_paths([sample], root)}
        self.assertIn("SEC-SECRET-TOKEN", codes)
        self.assertIn("SEC-PATH-PERSONAL", codes)

    def test_single_line_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample = root / "manifest.json"
            sample.write_text('{"active":true}\n', encoding="utf-8")
            codes = {item.code for item in scan_paths([sample], root)}
        self.assertIn("REP-JSON-FORMAT", codes)

    def test_default_python_tests_cover_every_workspace_scope(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            project["tool"]["pytest"]["ini_options"]["testpaths"],
            ["tests", "modules", "apps", "packages"],
        )

    def test_every_distribution_source_is_in_all_static_and_test_scopes(self) -> None:
        workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        members = workspace["tool"]["uv"]["workspace"]["members"]
        testpaths = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["tool"]["pytest"]["ini_options"]["testpaths"]
        pyright_config = json.loads(
            (ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
        )

        strict = set(pyright_config["strict"])
        included = set(pyright_config["include"])
        test_scopes = set(testpaths)
        for member in members:
            source = f"{member}/src"
            self.assertIn(source, strict, f"strict Pyright misses {source}")
            self.assertTrue(
                any(
                    member == scope or member.startswith(f"{scope}/")
                    for scope in included
                ),
                f"Pyright include misses {member}",
            )
            top_level = member.split("/", 1)[0]
            self.assertIn(top_level, test_scopes, f"pytest misses {member}")

    def test_build_inventory_follows_workspace_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "first").mkdir()
            (root / "second").mkdir()
            (root / "pyproject.toml").write_text(
                '[tool.uv.workspace]\nmembers = ["first", "second"]\n',
                encoding="utf-8",
            )
            (root / "first/pyproject.toml").write_text(
                '[project]\nname = "armi-first"\nversion = "0.0.0"\n',
                encoding="utf-8",
            )
            (root / "second/pyproject.toml").write_text(
                '[project]\nname = "armi.second"\nversion = "0.0.0"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                workspace_distribution_names(root),
                ("armi_first", "armi_second"),
            )


if __name__ == "__main__":
    unittest.main()
