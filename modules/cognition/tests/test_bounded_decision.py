"""Only complete, grounded decisions can avoid a generative invocation."""

import json
from uuid import uuid7

import pytest
from armi_cognition._bounded_decision import (
    prepare_decision,
    reflection_is_requested,
    settle_decision,
)
from armi_cognition._model_contract import (
    CodexDelegationPayload,
    CognitionCandidate,
    parse_candidate,
)
from armi_kernel.application import ModelViolation


def optional_request(purpose, *, max_bytes=32768):
    items = [
        {
            "item_kind": kind,
            "trust": "runtime_authority",
            "content": json.dumps(content),
            "source": {"reference": str(uuid7()), "version": 1},
        }
        for kind, content in [
            ("self", {"identity": "electronic person", "subject_id": "do-not-send"}),
            ("current_maintenance_phase", {"purpose": purpose}),
            ("current_memory", {"summary": "remember a real experience"}),
            ("capability_catalog", {"capabilities": []}),
            (
                "codex_task_source",
                {
                    "objective": "review a document",
                    "task_manifest_digest": "sha256:" + "a" * 64,
                },
            ),
        ]
    ]
    return prepare_decision(
        json.dumps(
            {
                "compiled_context": {"purpose": purpose, "layers": [{"items": items}]},
                "included_context_refs": [
                    {"ref": f"ctx:{i}", "item_kind": item["item_kind"]}
                    for i, item in enumerate(items, 1)
                ],
                "candidate_base": {
                    "subject_version": 1,
                    "state_epoch": 1,
                    "bundle_activation_id": str(uuid7()),
                    "context_digest": "sha256:" + "b" * 64,
                },
            }
        ).encode(),
        model="jev-1.13.0",
        max_bytes=max_bytes,
    )


def request(purpose):
    prepared = optional_request(purpose)
    assert prepared is not None
    return prepared


def answer(prepared, decision, *, confidence=1.0, sufficiency="bounded"):
    questions = json.loads(prepared.wire)["questions"]
    selected = {"decision": decision, "sufficiency": sufficiency, "basis": "ctx:1"}
    return json.dumps(
        {
            "answers": {
                key: {
                    "type": "choice",
                    "choice": selected[key],
                    "confidence": confidence,
                    "probabilities": {
                        option: float(option == selected[key])
                        for option in question["criteria"]
                    },
                }
                for key, question in questions.items()
            }
        }
    ).encode()


@pytest.mark.parametrize(
    ("purpose", "choice", "contract"),
    [
        *[
            ("consider_sleep", choice, "armi.sleep-decision-candidate")
            for choice in ("sleep", "stay_awake", "defer", "need_information")
        ],
        *[
            ("maintain_subjective_memory", choice, "armi.maintenance-work-candidate")
            for choice in (
                "memory_unchanged",
                "consolidate@ctx:3",
                "fade@ctx:3",
                "forget@ctx:3",
            )
        ],
        ("perform_subject_self_check", "no_issue", "armi.maintenance-work-candidate"),
        *[
            (purpose, "no_change", "armi.owner-reflection-candidate")
            for purpose in ("reflect_self", "reflect_focus", "reflect_prompt")
        ],
        ("consider_visual_observation", "ignore", "armi.visual-observation-candidate"),
        *[
            ("consider_codex_task", choice, "armi.cognition-candidate")
            for choice in ("execute", "decline", "defer", "need_information")
        ],
    ],
)
def test_bounded_result_preserves_real_contract_without_invented_prose(
    purpose, choice, contract
):
    prepared = request(purpose)
    result, reason = settle_decision(
        prepared, answer(prepared, choice), confidence=0.95, forget_confidence=0.99
    )
    assert reason == "bounded_complete"
    candidate = parse_candidate(
        json.dumps(result).encode(),
        expected_version=contract,
        purpose=purpose,
        allowed_context_refs=frozenset(prepared.refs),
    )
    assert getattr(candidate, "decision_basis", None) is not None
    assert getattr(candidate, "summary", None) is None
    assert getattr(candidate, "reason", None) is None
    assert getattr(candidate, "understanding", None) is None
    if choice == "execute":
        assert isinstance(candidate, CognitionCandidate)
        action = candidate.action_choices[0].payload
        assert isinstance(action, CodexDelegationPayload)
        assert str(action.task_source_id) == prepared.items[-1]["source"]["reference"]
        assert action.task_manifest_digest == "sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("purpose", "choice"),
    [
        ("maintain_subjective_memory", "reinterpret@ctx:3"),
        ("perform_subject_self_check", "issue_found@activity_stalled@focus"),
        ("reflect_self", "update"),
        ("reflect_focus", "update"),
        ("reflect_prompt", "update"),
        ("consider_visual_observation", "experience"),
        ("consider_sleep", "generate"),
    ],
)
def test_content_and_uncertainty_always_enter_generation(purpose, choice):
    prepared = request(purpose)
    assert settle_decision(
        prepared, answer(prepared, choice), confidence=0.95, forget_confidence=0.99
    ) == (None, "needs_generation")


@pytest.mark.parametrize(
    ("choice", "certainty", "reason"),
    [
        ("fade@ctx:3", 0.94, "low_confidence"),
        ("fade@ctx:3", 0.95, "bounded_complete"),
        ("forget@ctx:3", 0.98, "low_confidence"),
        ("forget@ctx:3", 0.99, "bounded_complete"),
    ],
)
def test_forgetting_has_stronger_gate(choice, certainty, reason):
    prepared = request("maintain_subjective_memory")
    assert (
        settle_decision(
            prepared,
            answer(prepared, choice, confidence=certainty),
            confidence=0.95,
            forget_confidence=0.99,
        )[1]
        == reason
    )


def test_incomplete_context_cannot_become_no_change():
    prepared = request("reflect_self")
    assert (
        settle_decision(
            prepared,
            answer(prepared, "no_change", sufficiency="generate"),
            confidence=0.95,
            forget_confidence=0.99,
        )[0]
        is None
    )
    assert optional_request("reflect_self", max_bytes=1) is None
    assert b"do-not-send" not in prepared.wire
    assert optional_request("consider_creator_input") is None


def test_self_check_request_only_bypasses_the_matching_reflection():
    document = request("reflect_self").original
    phase = document["compiled_context"]["layers"][0]["items"][1]
    phase["content"] = json.dumps(
        {"reflection_request": ["self", "真实自检发现的冲突"]}
    )
    assert reflection_is_requested(document)
    document["compiled_context"]["purpose"] = "reflect_focus"
    assert not reflection_is_requested(document)


@pytest.mark.parametrize("question", ["decision", "sufficiency", "basis"])
def test_semantic_unknown_is_generation_not_technical_failure(question):
    prepared = request("consider_sleep")
    value = json.loads(answer(prepared, "stay_awake"))
    choice = value["answers"][question]
    choice["choice"] = "unknown"
    choice["probabilities"] = {
        key: float(key == "unknown") for key in choice["probabilities"]
    }
    assert settle_decision(
        prepared, json.dumps(value).encode(), confidence=0.95, forget_confidence=0.99
    ) == (None, "semantic_unknown")


@pytest.mark.parametrize("raw", [b"broken", b"{}", b"null", b'{"answers":{}}'])
def test_technical_failures_are_not_semantic_escalation(raw):
    with pytest.raises(ModelViolation, match="MODEL-JEV-DECISION-CONTRACT"):
        settle_decision(
            request("consider_sleep"), raw, confidence=0.95, forget_confidence=0.99
        )
