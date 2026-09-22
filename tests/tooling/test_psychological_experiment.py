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
    assert len(list(output.glob("*-request.json"))) == len(module["CASES"]) * 2
    assert not list(output.glob("*-response.json"))
    for name, _ in module["CASES"]:
        mood = json.loads(
            (output / f"{name}-mood-request.json").read_text(encoding="utf-8")
        )
        joint = json.loads(
            (output / f"{name}-joint-request.json").read_text(encoding="utf-8")
        )
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
