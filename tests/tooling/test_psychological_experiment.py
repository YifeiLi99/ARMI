import asyncio
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_batch_has_no_credentials_or_provider_calls_by_default(tmp_path):
    module = runpy.run_path(str(ROOT / "tools/experiment_psychological_context.py"))
    output = tmp_path / "experiment"
    report = asyncio.run(module["run"](output, None, live=False))
    assert report["billable_calls"] == report["main_model_calls"] == 0
    assert not report["calibrated"]
    assert len(list(output.glob("*-request.json"))) == len(module["CASES"]) * 3
    assert not list(output.glob("*-response.json"))
    for name, _ in module["CASES"]:
        mood = json.loads(
            (output / f"{name}-mood-request.json").read_text(encoding="utf-8")
        )
        joint = json.loads(
            (output / f"{name}-joint-request.json").read_text(encoding="utf-8")
        )
        mind = json.loads(
            (output / f"{name}-mind-request.json").read_text(encoding="utf-8")
        )
        assert mind["questions"] == {
            k: v for k, v in joint["questions"].items() if k.startswith("mind_")
        }
        assert name in module["EXPECTED_CHOICES"]
        assert module["EXPECTED_CHOICES"][name]
        assert mood["state"] == joint["state"]
        assert all(
            joint["questions"][key] == value for key, value in mood["questions"].items()
        )
        assert len(joint["questions"]) - len(mood["questions"]) == 18
    with pytest.raises(FileExistsError):
        asyncio.run(module["run"](output, None, live=False))


@pytest.mark.parametrize(
    "root,approved", [(None, False), (None, True), (Path("unopened"), False)]
)
def test_real_probe_requires_explicit_isolation_and_cost_authorization(
    tmp_path, root, approved
):
    module = runpy.run_path(str(ROOT / "tools/experiment_psychological_context.py"))
    with pytest.raises(ValueError, match="isolated"):
        asyncio.run(
            module["run"](
                tmp_path / "experiment", root, live=True, allow_billable=approved
            )
        )
    assert not (tmp_path / "experiment").exists()


def test_grader_does_not_confuse_schema_success_with_correct_appraisal():
    module = runpy.run_path(str(ROOT / "tools/experiment_psychological_context.py"))
    assert not module["grade_choices"]("rest", {})["passed"]
    answers = {
        f"mind_0_{key}": {"choice": accepted[0]}
        for key, accepted in module["EXPECTED_CHOICES"]["rest"].items()
    }
    assert module["grade_choices"]("rest", answers)["passed"]
    answers["mind_0_understimulation"]["choice"] = "level_4"
    assert not module["grade_choices"]("rest", answers)["passed"]


def test_recorded_replay_preserves_failures_and_frozen_expectations(tmp_path):
    module = runpy.run_path(str(ROOT / "tools/experiment_psychological_context.py"))
    source = tmp_path / "source"
    asyncio.run(module["run"](source, None, live=False, modes=("mind",)))
    answers = {}
    request = json.loads(
        (source / "rest-mind-request.json").read_text(encoding="utf-8")
    )
    for name, question in request["questions"].items():
        choice = (
            "active"
            if name.endswith("_association")
            else "available"
            if name.endswith("_opportunity")
            else "unknown"
        )
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": 1.0,
            "probabilities": {k: float(k == choice) for k in question["criteria"]},
        }
    (source / "rest-mind-response.json").write_text(
        json.dumps({"body": json.dumps({"answers": answers})}), encoding="utf-8"
    )
    (source / "summary.json").write_text(
        json.dumps(
            {
                "results": [
                    {"case": "rest", "mode": "mind", "status": "valid"},
                    {"case": "new_question", "mode": "mind", "status": "failed"},
                ]
            }
        ),
        encoding="utf-8",
    )
    before = (source / "summary.json").read_bytes()
    result = module["replay"](source, tmp_path / "replay")
    assert result["provider_calls"] == 0
    assert not result["results"][0]["appraisal_grade"]["passed"]
    assert result["results"][1]["source_status"] == "failed"
    assert (source / "summary.json").read_bytes() == before
    frozen = json.loads((source / "frozen.json").read_text(encoding="utf-8"))
    frozen["expected_choices"]["rest"] = {}
    (source / "frozen.json").write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen expectations"):
        module["replay"](source, tmp_path / "forbidden")
