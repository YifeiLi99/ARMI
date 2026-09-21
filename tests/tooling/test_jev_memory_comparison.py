"""Protect experiment fairness, scoring boundaries and network failures."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import experiment_jev_memory as experiment


def fixture_config():
    return {
        "seed": 12,
        "repetitions": 1,
        "threshold": 0.5,
        "deepseek_model": "deepseek-flash",
        "jev_model": "jev-1.13.0",
        "fillers": ["irrelevant"],
        "cases": [
            {
                "id": "one",
                "query": "where",
                "facts": ["here"],
                "options": ["here", "unknown"],
                "expected": 0,
                "noise_count": 1,
            }
        ],
    }


def test_preview_does_not_read_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(
        experiment, "load_key", lambda *_: pytest.fail("credential read")
    )
    result = asyncio.run(
        experiment.run(fixture_config(), tmp_path / "out", None, live=False, limit=None)
    )
    assert result == {"mode": "preview", "pairs": 1, "api_calls": 5}


def test_shuffling_preserves_ground_truth():
    config = fixture_config()
    for rep in range(10):
        state = experiment.build_case(config["cases"][0], config, rep)
        assert state["options"][str(state["expected"])] == "here"
        assert len(state["memories"]) == 2
        assert state == experiment.build_case(config["cases"][0], config, rep)


def test_hallucinated_ids_and_boolean_choices_fail():
    with pytest.raises(experiment.ProbeError):
        experiment.parse_selection({"selected_ids": ["invented"]}, {"real"})
    with pytest.raises(experiment.ProbeError):
        experiment.parse_answer(
            {"choice": True, "answer": "x", "evidence_ids": []},
            {"options": {"1": "x"}},
            set(),
        )


def test_cache_aware_price():
    low, high = experiment.cost_bounds(
        "deepseek",
        {
            "prompt_tokens": 1000,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens": 100,
        },
    )
    assert low == pytest.approx(0.0000924)
    assert high == pytest.approx(2 * low)


def test_http_failure_stops_without_retry_or_error_body(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="sensitive-provider-error")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        experiment.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(experiment, "load_key", lambda *_: "test-secret")
    monkeypatch.setattr(experiment, "deepseek_key", lambda *_: "test-secret")
    output = tmp_path / "out"
    result = asyncio.run(
        experiment.run(fixture_config(), output, tmp_path, live=True, limit=None)
    )
    assert result["stopped_on_error"]
    assert len(calls) == 1
    files = "".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    assert "test-secret" not in files
    assert "sensitive-provider-error" not in files
    assert (
        sum(arm["unconfirmed_usage_calls"] for arm in result["summary"].values()) == 1
    )


def test_three_arms_have_same_answer_question_and_no_gold(tmp_path, monkeypatch):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if request.url.host == "api.typesafe.ai":
            return httpx.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {
                        key: {"type": "noul", "noul": 0.9} for key in body["questions"]
                    },
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            )
        state = json.loads(body["messages"][1]["content"])
        ids = [memory["id"] for memory in state["memories"]]
        answer = (
            {"choice": 0, "answer": "sample", "evidence_ids": ids}
            if "options" in state
            else {"selected_ids": ids}
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(answer)},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 10,
                    "completion_tokens": 5,
                },
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        experiment.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(experiment, "load_key", lambda *_: "test-secret")
    monkeypatch.setattr(experiment, "deepseek_key", lambda *_: "test-secret")
    result = asyncio.run(
        experiment.run(
            fixture_config(), tmp_path / "out", tmp_path, live=True, limit=None
        )
    )
    assert not result["stopped_on_error"]
    assert len(requests) == 5
    assert all("expected" not in json.dumps(body) for body in requests)
    answers = [
        json.loads(body["messages"][1]["content"])
        for body in requests
        if "messages" in body
        and "options" in json.loads(body["messages"][1]["content"])
    ]
    assert len(answers) == 3
    assert answers[0] == answers[1] == answers[2]


def test_continuation_does_not_repeat_a_failed_attempt(tmp_path):
    config = fixture_config()
    prior = tmp_path / "prior"
    asyncio.run(experiment.run(config, prior, None, live=False, limit=None))
    experiment.save(
        prior / "one-0-jev.json",
        {"case": "one", "rep": 0, "arm": "jev", "status": "failed", "calls": []},
    )
    result = asyncio.run(
        experiment.run(
            config, tmp_path / "next", None, live=False, limit=None, continue_from=prior
        )
    )
    assert result["api_calls"] == 3
