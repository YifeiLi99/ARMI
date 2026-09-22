import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def invoke(path):
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
    )


def test_frozen_trajectory_is_repeatable_and_resolves_without_time_growth():
    first = invoke(ROOT / "tools/scenarios/mind-curiosity.yaml")
    second = invoke(ROOT / "tools/scenarios/mind-curiosity.yaml")
    assert first.returncode == second.returncode == 0, first.stdout + first.stderr
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["passed"] and not report["calibrated"]
    assert report["main_model_calls"] == 0
    assert report["steps"][2]["state"]["association"] == "satisfied"


def test_scenario_rejects_extra_fields_and_non_synthetic_input(tmp_path):
    path = tmp_path / "input.yaml"
    for text in (
        "synthetic: false\nsteps: []\n",
        "synthetic: true\nsteps: []\nshell: ignored\n",
        "synthetic: true\nsteps: []\nsteps: []\n",
    ):
        path.write_text(text, encoding="utf-8")
        result = invoke(path)
        assert result.returncode == 1
        assert not json.loads(result.stdout)["passed"]
