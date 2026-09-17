"""The psychological probe is synthetic, bounded and uses production validation."""

import asyncio
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def experiment(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return runpy.run_path(str(ROOT / "tools/experiment_psychological_context.py"))


def test_dry_run_never_reads_credentials_and_does_not_overwrite(experiment, tmp_path):
    output = tmp_path / "probe"
    result = asyncio.run(experiment["run"](output, None, live=False))
    assert result["billable_calls"] == 0
    assert len(list(output.glob("*-request.json"))) == 6
    assert not list(output.glob("*-response.json"))
    assert not (output / "run").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(experiment["run"](output, None, live=False))


def test_pairs_share_contract_and_accept_silence_without_forcing_emotion(experiment):
    cases = [experiment["prepare_case"](text) for _, text in experiment["CASES"]]
    assert all(case["schema"] == cases[0]["schema"] for case in cases)
    for case in cases:
        response = {
            "kind": "no_activity",
            "next_consideration_seconds": 300,
            "expression": None,
            "concern_changes": [],
        }
        result = experiment["build_candidate_validator"](case["validation"]).validate(
            json.dumps(response).encode(), bases=case["bases"]
        )
        assert result.error_code is None
        assert result.change_set is not None
        assert not result.change_set.owner_drafts
        assert not result.change_set.action_choices
        kinds = set(case["schema"]["discriminator"]["mapping"])
        assert not kinds & {
            "web_research",
            "visual_observation",
            "codex_delegation",
            "exact_life_query",
        }


def test_live_requires_explicit_credential_source(experiment, tmp_path):
    with pytest.raises(ValueError, match="environment-root"):
        asyncio.run(experiment["run"](tmp_path / "probe", None, live=True))


def test_autonomous_mind_change_can_coexist_with_silence_and_rejects_unknown_basis(
    experiment,
):
    case = experiment["prepare_case"](experiment["CASES"][4][1])
    candidate = {
        "kind": "no_activity",
        "next_consideration_seconds": 300,
        "expression": None,
        "concern_changes": [],
        "mind_change": {
            "change": {"motivations": {"values": ["想换一种有新发现的投入方式"]}},
            "basis_refs": ["ctx:5"],
        },
    }
    validator = experiment["build_candidate_validator"](case["validation"])
    result = validator.validate(candidate, bases=case["bases"])
    assert result.error_code is None
    assert result.change_set is not None
    assert not result.change_set.experiences
    assert not result.change_set.action_choices
    assert [item.owner for item in result.change_set.owner_drafts] == ["mind"]
    draft = result.change_set.owner_drafts[0].candidate
    from datetime import UTC, datetime
    from uuid import uuid7

    from armi_mind.api import MindHead, initial_mind_state, prepare_mind_change

    state = prepare_mind_change(
        MindHead(uuid7(), 1, initial_mind_state()),
        draft,
        now=datetime(2026, 9, 17, tzinfo=UTC),
        commit_id=uuid7(),
    )
    assert json.loads(state)["motivations"] == ["想换一种有新发现的投入方式"]
    assert json.loads(state)["concerns"] == []
    candidate["mind_change"]["basis_refs"] = ["ctx:99"]
    rejected = validator.validate(candidate, bases=case["bases"])
    assert rejected.change_set is None
    assert rejected.error_code == "CANDIDATE-MIND-REFERENCE"


def test_provider_response_uses_production_envelope_extraction(experiment):
    case = experiment["prepare_case"](experiment["CASES"][0][1])
    value = {"kind": "no_activity", "next_consideration_seconds": 300}
    envelope = json.dumps(
        {
            "schema_version": "armi.model-response-artifact.v3",
            "output_text": json.dumps({"candidate": value}),
        }
    ).encode()
    result = experiment["build_candidate_validator"](case["validation"]).validate(
        experiment["model_response_candidate"](envelope), bases=case["bases"]
    )
    assert result.error_code is None


@pytest.mark.parametrize("malformed", [True, False])
def test_invalid_model_returns_are_rejected_without_repair(experiment, malformed):
    case = experiment["prepare_case"](experiment["CASES"][0][1])
    output = (
        '{"candidate":'
        if malformed
        else json.dumps(
            {
                "candidate": {
                    "kind": "no_activity",
                    "next_consideration_seconds": 43200,
                }
            }
        )
    )
    raw = json.dumps(
        {"schema_version": "armi.model-response-artifact.v3", "output_text": output}
    ).encode()
    result = experiment["validate_response"](case, raw)
    assert result["validation"] == "rejected"
    assert result["owners"] == []
    assert result["stage"] == (
        "response_envelope" if malformed else "candidate_validation"
    )


def test_autonomous_mind_and_concern_changes_form_one_owner_draft(experiment):
    from datetime import UTC, datetime
    from uuid import uuid7

    from armi_mind.api import MindHead, initial_mind_state, prepare_mind_change

    case = experiment["prepare_case"](experiment["CASES"][0][1])
    candidate = {
        "kind": "defer",
        "next_consideration_seconds": 300,
        "mind_change": {
            "change": {"motivations": {"values": ["理解观察到的变化"]}},
            "basis_refs": ["ctx:5"],
        },
        "concern_changes": [
            {
                "operation": "create",
                "question": "叶片为何改变方向?",
                "reason": "观察没有解释",
                "resolution_condition": "获得有依据的解释",
                "understanding": "目前没有新认识",
                "state": "waiting",
                "basis_refs": ["ctx:5"],
                "review": {"kind": "creator_input", "reason": "等待新线索"},
            }
        ],
    }
    result = experiment["build_candidate_validator"](case["validation"]).validate(
        candidate, bases=case["bases"]
    )
    assert result.error_code is None
    assert result.change_set is not None
    assert len(result.change_set.owner_drafts) == 1
    state = json.loads(
        prepare_mind_change(
            MindHead(uuid7(), 1, initial_mind_state()),
            result.change_set.owner_drafts[0].candidate,
            now=datetime(2026, 9, 17, tzinfo=UTC),
            commit_id=uuid7(),
        )
    )
    assert state["motivations"] == ["理解观察到的变化"]
    assert state["concerns"][0]["state"] == "waiting"
