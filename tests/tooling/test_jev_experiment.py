"""The Jev trial is isolated, explicit about billing, and preserves real failures."""

import importlib
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/jev-experiment.yaml"


@pytest.fixture
def experiment(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return importlib.import_module("experiment_jev")


def reply(request):
    body = json.loads(request.content)
    return {
        "model": body["model"],
        "answers": {name: {"type": "noul", "noul": 0.8} for name in body["questions"]},
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


def test_preview_never_reads_credentials_or_calls_network(
    experiment, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("preview accessed credentials or network")

    monkeypatch.setattr(experiment, "load_key", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    output = tmp_path / "preview"
    result = experiment.run(CONFIG, output)
    assert result["planned_requests"] == 11
    assert result["attempted_requests"] == 0
    assert result["labelled_decisions"] == 0
    assert not list(output.glob("*-response.json"))
    requests = list(output.glob("*-request.json"))
    assert len(requests) == 11
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert set(request) == {"model", "state", "questions"}
        assert "expected" not in path.read_text(encoding="utf-8")
        assert "evaluation" not in path.read_text(encoding="utf-8")
    before = (output / "results.json").read_bytes()
    with pytest.raises(FileExistsError):
        experiment.run(CONFIG, output)
    assert (output / "results.json").read_bytes() == before


def test_live_official_request_response_usage_and_no_key_in_artifacts(
    experiment, tmp_path, monkeypatch
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-jev-secret")
    sent = []

    def handle(request):
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-only-jev-secret"
        assert request.method == "POST"
        sent.append(request)
        return httpx.Response(200, json=reply(request))

    output = tmp_path / "live"
    result = experiment.run(
        CONFIG, output, live=True, suite="memory", transport=httpx.MockTransport(handle)
    )
    assert len(sent) == result["successful_requests"] == 3
    assert result["labelled_decisions"] == 8
    row = result["results"][0]
    assert row["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert row["estimated_input_cost_usd"] == "0.0000042"
    assert row["ranking"] == ["river_walk", "weekend_work", "spelling"]
    for path in output.glob("*.json"):
        assert "test-only-jev-secret" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_http_failure_stops_without_retry_redirect_or_error_body(
    experiment, tmp_path, monkeypatch, status
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="sensitive-error-body",
            headers={"Location": "https://other.invalid"},
        )

    output = tmp_path / "failure"
    result = experiment.run(
        CONFIG, output, live=True, transport=httpx.MockTransport(handle)
    )
    assert len(calls) == result["attempted_requests"] == 1
    assert result["technical_failures"] == 1
    assert result["results"][0]["status"] == "http_error"
    assert result["results"][0]["outcome_unknown"] == (status >= 500)
    assert "decisions" not in result["results"][0]
    assert not list(output.glob("*-response.json"))
    assert "sensitive-error-body" not in (output / "results.json").read_text()


def test_timeout_is_unknown_and_never_retried(experiment, tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-in-exception", request=request)

    result = experiment.run(
        CONFIG, tmp_path / "timeout", live=True, transport=httpx.MockTransport(handle)
    )
    assert len(calls) == 1
    row = result["results"][0]
    assert row["status"] == "timeout"
    assert row["outcome_unknown"] is True
    assert "usage" not in row
    assert "secret-in-exception" not in json.dumps(result)


@pytest.mark.parametrize(
    "fault",
    [
        "model",
        "missing_question",
        "extra_question",
        "probability",
        "boolean",
        "usage",
        "json",
    ],
)
def test_invalid_provider_response_retained_but_not_a_decision(
    experiment, tmp_path, monkeypatch, fault
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")

    def handle(request):
        value = reply(request)
        if fault == "model":
            value["model"] = "other-model"
        elif fault == "missing_question":
            value["answers"] = {}
        elif fault == "extra_question":
            value["answers"]["unknown"] = {"type": "noul", "noul": 0.8}
        elif fault == "probability":
            value["answers"]["engage"]["noul"] = 1.01
        elif fault == "boolean":
            value["answers"]["engage"]["noul"] = True
        elif fault == "usage":
            value["usage"]["input_tokens"] = "100"
        elif fault == "json":
            return httpx.Response(200, content=b"{broken")
        return httpx.Response(200, json=value)

    output = tmp_path / fault
    result = experiment.run(
        CONFIG, output, live=True, transport=httpx.MockTransport(handle)
    )
    assert result["attempted_requests"] == result["technical_failures"] == 1
    assert result["results"][0]["status"] == "invalid_response"
    assert "decisions" not in result["results"][0]
    assert len(list(output.glob("*-response.json"))) == 1


def test_key_file_precedence_missing_key_and_no_output(
    experiment, tmp_path, monkeypatch
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-test-key")
    path = tmp_path / "api.key"
    path.write_text("file-test-key\n", encoding="utf-8-sig")
    assert experiment.load_key(path) == "file-test-key"
    assert experiment.load_key(None) == "environment-test-key"
    path.write_text("", encoding="utf-8")
    with pytest.raises(experiment.ExperimentError, match="JEV-KEY-MISSING"):
        experiment.run(CONFIG, tmp_path / "missing", live=True, key_file=path)
    assert not (tmp_path / "missing").exists()


def test_split_and_ambiguous_labels_are_not_passes(experiment, tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")
    result = experiment.run(
        CONFIG,
        tmp_path / "eval",
        live=True,
        suite="autonomy",
        split="evaluation",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=reply(request))
        ),
    )
    assert result["planned_requests"] == 3
    assert result["labelled_decisions"] == 2
    assert result["matched_decisions"] == 1
    assert result["results"][-1]["decisions"][0]["match"] is None
