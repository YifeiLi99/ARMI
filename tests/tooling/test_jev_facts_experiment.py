import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from tools import experiment_jev_facts as experiment


def case():
    return {
        "id": "one",
        "scene": "Synthetic text",
        "expected": {"agency": ["hidden_gold"]},
    }


def test_prompts_share_state_but_do_not_send_expectations():
    body = experiment.request_body(case())
    assert "hidden_gold" not in json.dumps(body)
    assert len(body["questions"]) == 15
    assert {q["type"] for q in body["questions"].values()} == {
        "choice",
        "score",
        "noul",
    }
    assert all(name not in body for name in ("affect", "emotions"))


def test_score_distribution_and_unknown_evidence_remain_separate():
    body = experiment.request_body(case())
    question = body["questions"]["urgency_score"]
    answer = {
        "type": "score",
        "score": 0.5,
        "confidence": 0.4,
        "legend": {str(i): s for i, s in enumerate(question["criteria"])},
        "probabilities": {"0": 0.5, "1": 0.5, "2": 0, "3": 0, "4": 0},
    }
    assert experiment.validate_answer(answer, question)
    assert not experiment.validate_answer(answer | {"score": 4}, question)
    evidence = body["questions"]["urgency_evidence"]
    assert experiment.validate_answer(
        {
            "type": "choice",
            "choice": "unknown",
            "confidence": 1,
            "probabilities": {"known": 0, "unknown": 1, "not_applicable": 0},
        },
        evidence,
    )


def test_preview_is_offline(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("must not read secrets")

    monkeypatch.setattr(experiment, "load_key", forbidden)
    rows = asyncio.run(experiment.run({"cases": [case()]}, tmp_path / "preview"))
    assert rows[0]["status"] == "preview"


def test_http_failure_stops_without_retry_or_secret_logging(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "load_key", lambda _: "test-secret")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, text="test-secret")

    output = tmp_path / "run"
    rows = asyncio.run(
        experiment.run(
            {"cases": [case(), case() | {"id": "two"}]},
            output,
            live=True,
            transport=httpx.MockTransport(handler),
        )
    )
    assert len(requests) == 1
    assert rows[0]["status"] == "call_failed"
    assert "test-secret" not in (output / "results.json").read_text(encoding="utf-8")
