"""The offline harness exercises the same public Owner rules as production."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def invoke(path: Path):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/test_mind.py"),
            "--scenario",
            str(path),
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_curiosity_scenario_is_deterministic_and_closes():
    path = ROOT / "tools/scenarios/mind-curiosity.yaml"
    first, second = invoke(path), invoke(path)
    assert first.returncode == second.returncode == 0, first.stdout + first.stderr
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)
    assert result["passed"]
    assert result["steps"][2]["signals"][0]["due"]
    assert result["steps"][-1]["signals"] == []
    assert result["steps"][7]["field_path"] == ["expected_version"]


def test_unexpected_rejection_stops_and_strict_yaml_rejects_extra_keys(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        "synthetic: true\nsteps:\n  - action: change\n    expected_version: 99\n  - action: snapshot\n",
        encoding="utf-8",
    )
    result = invoke(path)
    assert result.returncode == 1
    assert len(json.loads(result.stdout)["steps"]) == 1
    for text in (
        "synthetic: true\nsteps: []\nshell: echo unsafe\n",
        "synthetic: true\nsteps: []\nsteps: []\n",
        "synthetic: false\nsteps: []\n",
    ):
        path.write_text(text, encoding="utf-8")
        assert invoke(path).returncode == 1
