"""Synthetic probes use production questions and never expose grading labels."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from armi_mood.api import DynamicsParameters, initial_dynamics

from tools import experiment_jev_mood as experiment


def case():
    return {
        "id": "quiet",
        "sequence": "quiet",
        "scene": "没有发生变化。",
        "expected": {"loss": ["level_0"]},
        "required_emotions": [],
    }


def test_grading_labels_are_not_sent_to_provider():
    value = case() | {"expected": {"hidden_gold": ["secret"]}}
    body = experiment.request_body(
        value, initial_dynamics(datetime.now(UTC), DynamicsParameters()), "event"
    )
    assert "secret" not in json.dumps(body)
    assert "hidden_gold" not in json.dumps(body)
    assert "sadness" not in body["questions"]
    assert body["model"] == "jev-1.13.0"


def test_preview_does_not_resolve_credentials_or_call_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preview must be offline")

    monkeypatch.setattr(experiment, "load_key", forbidden)
    result = asyncio.run(experiment.run({"cases": [case()]}, tmp_path))
    assert result["attempted_calls"] == 0
    assert (tmp_path / "quiet.json").exists()


def test_failure_stops_sequence_without_retry_or_secret_output(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "load_key", lambda _: "test-secret-never-save")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="unavailable")

    result = asyncio.run(
        experiment.run(
            {"cases": [case(), case() | {"id": "next"}]},
            tmp_path,
            live=True,
            transport=httpx.MockTransport(handler),
        )
    )
    assert len(calls) == 1
    assert result["failures"] == 1
    assert not (tmp_path / "next.json").exists()
    assert all(
        "test-secret-never-save" not in p.read_text(encoding="utf-8")
        for p in tmp_path.glob("*.json")
    )
