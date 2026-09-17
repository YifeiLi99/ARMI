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


@pytest.mark.parametrize("mode", ["appraisal", "autonomous"])
def test_experiment_evidence_matches_actual_transport_schema_order(
    experiment, tmp_path, mode
):
    case = experiment["appraisal_case" if mode == "appraisal" else "prepare_case"](
        "合成处境"
    )
    prices = experiment["load_price_catalog"](ROOT / "configs/provider-pricing.yaml")
    request = experiment["checked_model_request"](
        binding=case["binding"],
        request_bytes=case["request"],
        context_digest=case["digest"],
        input_tokens=100,
        prices=prices,
    )
    transport = experiment["EvidenceTransport"](
        case["schema"],
        instructions="合成测试",
        schema_name="test",
        output=tmp_path / "response.json",
    )
    adapter = experiment["VolcengineArkModelAdapter"](
        binding=case["binding"],
        credential_port=None,  # No tokenization or network invocation in this test.
        locator=None,
        candidate_schema=experiment["CognitionSchemaDocument"](
            experiment["rfc8785"].dumps(case["schema"])
        ),
        instructions="合成测试",
        schema_name="test",
        transport=transport,
    )
    actual = transport.request_parameters(case["binding"], request)
    recorded = json.loads(adapter.request_evidence(request))["provider_request"]
    assert actual == recorded


def test_appraisal_contract_derives_but_does_not_accept_emotion_scores(experiment):
    def evaluate(candidate):
        return experiment["validate_appraisal_response"](
            {},
            json.dumps(
                {
                    "schema_version": "armi.model-response-artifact.v3",
                    "output_text": json.dumps({"candidate": candidate}),
                }
            ).encode(),
        )

    assert evaluate({"mind": [], "mood": None})["validation"] == "accepted"
    assessment = dict(
        object_ref="ctx:1",
        basis_refs=["ctx:1"],
        desired_outcome="understand",
        significance="important",
        discrepancy="substantial",
        understanding="unexplained",
        progress="stalled",
        opportunity="available",
        resolution="open",
        explanation="观察到尚不理解的现象",
    )
    result = evaluate({"mind": [assessment], "mood": None})
    assert result["validation"] == "accepted"
    assert result["mind"][0]["trajectory"][-1]["level"] > 0
    assert (
        evaluate({"mind": [assessment | {"curiosity": 2}], "mood": None})["validation"]
        == "rejected"
    )
    assert (
        evaluate({"mind": [assessment | {"object_ref": "ctx:2"}], "mood": None})[
            "validation"
        ]
        == "rejected"
    )
    assert (
        evaluate({"mind": [assessment, assessment], "mood": None})["validation"]
        == "rejected"
    )


@pytest.mark.parametrize("phase", ["anticipated", "realized"])
def test_appraisal_probe_preserves_loss_phase_in_owner_derivation(experiment, phase):
    command = {
        "schema_version": "armi.mood-appraisal.v3",
        "transition": "new",
        "event_phase": phase,
        "gist": "重要作品丢失",
        "appraisal": {
            "engagement": "not_applicable",
            "concerns": [
                {
                    "target": "self_goal",
                    "significance": "core",
                    "direction": "major_setback",
                }
            ],
            "expectedness": "expectation_broken",
            "outcome_certainty": "settled",
            "intrinsic_quality": "unpleasant",
            "self_involvement": "important",
            "coping": {
                "response_access": "none",
                "power_balance": "overmatched",
                "adjustment": "blocked",
            },
        },
    }
    result = experiment["validate_appraisal_response"](
        {},
        json.dumps(
            {
                "schema_version": "armi.model-response-artifact.v3",
                "output_text": json.dumps({"candidate": {"mind": [], "mood": command}}),
            }
        ).encode(),
    )
    assert result["validation"] == "accepted"
    assert result["mood_assessment"]["event_phase"] == phase
    families = {c["component"]["family"] for c in result["mood"]["components"]}
    assert ("sadness" in families) == (phase == "realized")


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


def test_trajectory_carries_owner_state_consumes_signals_and_closes(experiment):
    from datetime import timedelta

    host = experiment["MindTrajectory"]()
    start = host.now

    def step(assessment=None, expression=None):
        case = host.prepare()
        candidate = {
            "kind": "no_activity",
            "next_consideration_seconds": 21600,
            "expression": expression,
            "mind_appraisals": [] if assessment is None else [assessment],
        }
        response = json.dumps(
            {
                "schema_version": "armi.model-response-artifact.v3",
                "output_text": json.dumps({"candidate": candidate}),
            }
        ).encode()
        row = experiment["validate_response"](case, response)
        host.accept(row)
        assert row["validation"] == "accepted"
        return case, row

    assessment = dict(
        object_ref="ctx:5",
        basis_refs=["ctx:5"],
        desired_outcome="understand",
        significance="important",
        discrepancy="substantial",
        understanding="unexplained",
        progress="stalled",
        opportunity="available",
        resolution="open",
        explanation="不知道合成装置的规则",
    )
    _, first = step(assessment)
    assert host.now == start + timedelta(minutes=30)
    assert first["mind_version"] == 2
    case, second = step(expression="这个装置为何变色?")
    assert any(b.item_kind == "current_motivation" for b in case["bases"])
    assert second["motivation_projection"][0]["level"] > 0
    assert host.now == start + timedelta(minutes=35)
    assert (
        second["mind_version"] == 2
    )  # Silence/text never erases or invents a revision.
    _, third = step(
        assessment
        | {
            "object_ref": "ctx:7",
            "resolution": "satisfied",
            "discrepancy": "none",
            "understanding": "sufficient",
            "explanation": "反馈说明计时器每30分钟切换,回答了原问题",
        }
    )
    assert third["feedback_present"]
    assert third["motivation_projection"] == []
    assert experiment["mind_signals"](host.head.canonical_state) == ()
    assert host.now == start + timedelta(minutes=35, hours=6)


def test_trajectory_stops_instead_of_faking_activity_or_accepting_rejection(experiment):
    host = experiment["MindTrajectory"]()
    initial = host.head
    host.accept({"validation": "accepted", "candidate": {"kind": "start_activity"}})
    assert host.stop_reason == "requires_activity_or_effect_host"
    assert host.head == initial
    host = experiment["MindTrajectory"]()
    host.accept({"validation": "rejected"})
    assert host.stop_reason == "candidate_rejected"
    assert host.head == initial
