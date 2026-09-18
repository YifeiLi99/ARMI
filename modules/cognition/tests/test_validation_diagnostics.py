"""Invalid returns keep their facts and expose bounded, structural diagnostics."""

import json

import pytest
from armi_cognition._candidate_application import model_response_candidate
from armi_cognition._model_contract import parse_candidate
from armi_cognition._validation_diagnostics import contract_rejection
from armi_kernel.application import CandidateViolation, ModelViolation


def test_invalid_json_is_distinguished_from_wrong_field_type():
    raw = json.dumps(
        {"schema_version": "armi.model-response-artifact.v3", "output_text": "{broken"}
    ).encode()
    with pytest.raises(CandidateViolation) as caught:
        model_response_candidate(raw)
    result = contract_rejection(caught.value)
    assert result.diagnostics[0].stage == "parse"
    assert result.diagnostics[0].code == "CANDIDATE-JSON"

    with pytest.raises(ModelViolation) as caught_model:
        parse_candidate(
            {"decision": {"kind": "reply", "content": 42}},
            allowed_context_refs=frozenset(),
            expected_version="armi.creator-cognitive-act-candidate.v7",
        )
    result = contract_rejection(caught_model.value)
    assert result.diagnostics[0].stage == "structure"
    assert result.diagnostics[0].field_path == ("decision", "reply", "content")
    assert result.diagnostics[0].code == "string_type"
    assert "42" not in repr(result.diagnostics)


def test_saved_response_has_only_one_candidate_body():
    value = {"decision": {"kind": "no_action"}}
    raw = json.dumps(
        {
            "schema_version": "armi.model-response-artifact.v3",
            "output_text": json.dumps({"candidate": value}),
        }
    ).encode()
    assert model_response_candidate(raw) == value
