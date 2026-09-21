"""Verify Mood experiment isolation, grading and contract mapping."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import experiment_jev_mood as experiment


def choices():
    value = {key: "unknown" for key in experiment.FIELDS}
    value.update(
        event_phase="ongoing",
        transition="new",
        self_standard="not_applicable",
        norm_compatibility="not_applicable",
        self_goal_significance="direct",
        relationship_significance="absent",
        social_order_significance="absent",
        self_goal_direction="unchanged",
        intrinsic_quality="neutral",
        expectedness="expected",
        outcome_certainty="open",
        self_involvement="limited",
        engagement="not_applicable",
        demand_urgency="none",
        demand_effort="none",
        coping_response_access="indirect",
        coping_power_balance="balanced",
        coping_adjustment="easy",
    )
    return value


def case():
    return {
        "id": "quiet",
        "scene": "quiet",
        "existing_episode": False,
        "expected": {"engagement": ["not_applicable", "satisfying"]},
        "required_emotions": [],
        "forbidden_emotions": ["boredom"],
    }


def test_neutral_scene_uses_real_policy_without_inventing_boredom():
    value = experiment.derive(choices(), case())
    assert value["status"] == "derived"
    assert value["derived"]["core"]["intensity"] == 0
    assert experiment.grade(choices(), case(), value)["emotion"]["passed"]
    changed = choices() | {"engagement": "understimulated"}
    actual = experiment.grade(changed, case(), experiment.derive(changed, case()))
    assert actual["emotion"]["forbidden_present"] == ["boredom"]
    assert not actual["semantic"]["all_passed"]


def test_prior_event_required_and_no_fake_previous_affect():
    value = choices() | {"transition": "reappraise_unchanged"}
    with pytest.raises(experiment.ProbeError, match="EXISTING-EPISODE-MISSING"):
        experiment.derive(value, case())
    derived = experiment.derive(value, case() | {"existing_episode": True})
    assert derived["status"] == "existing_semantics_only"
    assert derived["derived"] is None
    assert derived["command"]["change_from_previous"] == "unchanged"


def test_self_standard_preserves_action_scope_and_unknowns():
    value = experiment.derive(choices() | {"self_standard": "violation_action"}, case())
    assert value["command"]["appraisal"]["standards"]["self_evaluation"] == {
        "compatibility": "violation",
        "scope": "action",
    }
    assert value["command"]["appraisal"]["causality"]["intentionality"] == "unknown"


def test_skip_does_not_hide_required_emotion_failure():
    value = choices() | {"transition": "skip"}
    scene = case() | {"required_emotions": ["sadness"]}
    grade = experiment.grade(value, scene, experiment.derive(value, scene))
    assert grade["emotion"]["missing"] == ["sadness"]


def test_gold_is_not_in_request_and_order_is_reproducible():
    scene = case() | {"expected": {"sentinel_not_for_model": ["secret_gold"]}}
    request = experiment.request_body(scene, 0, 1)
    assert "secret_gold" not in json.dumps(request)
    assert request == experiment.request_body(scene, 0, 1)
    other = experiment.request_body(scene, 1, 1)
    assert request["state"] == other["state"]
    assert set(request["questions"]) == set(other["questions"])
    assert any(
        list(request["questions"][key]["criteria"])
        != list(other["questions"][key]["criteria"])
        for key in request["questions"]
    )


def test_preview_never_reads_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(
        experiment, "load_key", lambda *_: pytest.fail("credential read")
    )
    config = {"repetitions": 1, "seed": 1, "cases": [case()], "intensity_pairs": []}
    result = asyncio.run(experiment.run(config, tmp_path / "out", None, live=False))
    assert result == {"mode": "preview", "planned_calls": 2}


def test_invalid_enumeration_is_not_repaired():
    value = choices() | {"expectedness": "slightly_unexpected"}
    raw = {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
        ]
    }
    with pytest.raises(experiment.ProbeError, match="INVALID-CHOICE"):
        experiment.parse_choices(raw, "deepseek")


def test_rounded_probabilities_are_not_normalized_or_rejected():
    answers = {}
    for key, (_, options) in experiment.FIELDS.items():
        options = options.split()
        probabilities = dict.fromkeys(options, 0.0)
        probabilities[options[0]] = 0.98
        probabilities[options[1]] = 0.01
        answers[key] = {
            "type": "choice",
            "choice": options[0],
            "confidence": 0.9,
            "probabilities": probabilities,
        }
    raw = {"model": "jev-1.13.0", "answers": answers}
    value, _ = experiment.parse_choices(raw, "jev")
    assert len(value) == len(experiment.FIELDS)
    assert sum(answers["event_phase"]["probabilities"].values()) == 0.99
    answers["event_phase"]["probabilities"] = dict.fromkeys(
        answers["event_phase"]["probabilities"], 0.9
    )
    with pytest.raises(experiment.ProbeError, match="INVALID-JEV-PROBABILITY-SUM"):
        experiment.parse_choices(raw, "jev")


def test_regrade_uses_frozen_labels_without_reading_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(
        experiment, "load_key", lambda *_: pytest.fail("credential read")
    )
    source = tmp_path / "original"
    source.mkdir()
    config = {"repetitions": 1, "seed": 1, "cases": [case()], "intensity_pairs": []}
    experiment.save(source / "config.json", config)
    response = {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(choices())}}
        ]
    }
    experiment.save(
        source / "quiet-0-deepseek.json",
        {
            "case": "quiet",
            "rep": 0,
            "provider": "deepseek",
            "status": "failed",
            "error": "OLD-PARSER-ERROR",
            "response": response,
            "latency_ms": 100,
        },
    )
    output = tmp_path / "reviewed"
    result = experiment.regrade(source, output)
    assert result["summary"]["deepseek"]["all_critical_checks_passed"] == 1
    row = json.loads((output / "quiet-0-deepseek.json").read_text(encoding="utf-8"))
    assert row["response"] == response
    assert row["original_error"] == "OLD-PARSER-ERROR"
    assert json.loads((output / "config.json").read_text(encoding="utf-8")) == config
