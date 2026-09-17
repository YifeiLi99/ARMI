import json

import jsonschema
import pytest
from armi_cognition._context_schema import bind_context_schema
from armi_cognition._model_contract import candidate_schema


def test_concern_and_emotional_episode_references_cannot_be_interchanged():
    schema = bind_context_schema(
        candidate_schema("armi.creator-cognitive-act-candidate.v6"),
        (
            {"ref": "ctx:1", "item_kind": "current_evidence"},
            {"ref": "ctx:2", "item_kind": "current_concern"},
            {"ref": "ctx:3", "item_kind": "active_affective_episode"},
        ),
    )
    close = {
        "operation": "resolve",
        "concern_ref": "ctx:2",
        "conclusion": "The new evidence explains it",
        "basis_refs": ["ctx:1"],
    }
    value = {"decision": {"kind": "no_change"}, "concern_changes": [close]}
    jsonschema.validate(value, schema)
    close["concern_ref"] = "ctx:3"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, schema)
    episode = schema["$defs"]["ExistingAppraisal"]["properties"]["episode_ref"]
    assert episode == {"type": "string", "enum": ["ctx:3"]}


def test_no_previous_episode_or_concern_removes_only_unavailable_choices():
    schema = bind_context_schema(
        candidate_schema("armi.creator-cognitive-act-candidate.v6"),
        ({"ref": "ctx:1", "item_kind": "current_evidence"},),
    )
    text = json.dumps(schema)
    for name in (
        "ExistingAppraisal",
        "UpdateConcern",
        "CloseConcern",
        "ActivityReview",
    ):
        assert name not in text
    assert "CreateConcern" in text
    assert "NewAppraisal" in text
    assert "CreatorInputReview" in text
    assert "TimedReview" in text


def test_context_binding_does_not_mutate_the_shared_contract():
    source = candidate_schema("armi.creator-cognitive-act-candidate.v6")
    before = json.dumps(source, sort_keys=True)
    bind_context_schema(source, ())
    assert json.dumps(source, sort_keys=True) == before
