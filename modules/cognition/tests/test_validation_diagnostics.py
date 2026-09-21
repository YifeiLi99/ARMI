"""Invalid returns keep their facts and expose bounded, structural diagnostics."""

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition._candidate_application import model_response_candidate
from armi_cognition._candidate_postgresql import (
    PostgreSQLCandidateValidationRepository,
    accepted_candidates,
)
from armi_cognition._model_contract import parse_candidate
from armi_cognition._validation_diagnostics import contract_rejection
from armi_kernel.application import (
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateViolation,
    ModelViolation,
)


@pytest.mark.asyncio
async def test_rejection_finishes_episode_without_persisting_validation_or_audit():
    episode_id = uuid7()
    snapshot = SimpleNamespace(episode_id=episode_id, opportunity_id=uuid7())
    result = contract_rejection(CandidateViolation("CANDIDATE-CONTRACT"))
    connection = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(fetchone=AsyncMock(return_value=(episode_id,)))
        )
    )
    unit = SimpleNamespace(
        transaction=connection,
        runtime_fence=object(),
        work=SimpleNamespace(validate_lease=AsyncMock(), complete=AsyncMock()),
        audit=SimpleNamespace(append=AsyncMock()),
    )
    repository = object.__new__(PostgreSQLCandidateValidationRepository)
    transitions = SimpleNamespace(
        resolve_cognition_failure=AsyncMock(return_value=True)
    )
    repository._opportunity_transitions = cast(Any, transitions)
    await repository.settle(
        cast(Any, unit),
        lease=cast(Any, SimpleNamespace(token=1)),
        snapshot=cast(Any, snapshot),
        result=result,
        validator_identity="test",
        change_set_artifact=None,
    )
    statements = [call.args[0] for call in connection.execute.await_args_list]
    assert len(statements) == 1 and "UPDATE armi.cognitive_episodes" in statements[0]
    assert connection.execute.call_args.args[1][:3] == (
        "candidate_rejected",
        None,
        "CANDIDATE-CONTRACT",
    )
    unit.audit.append.assert_not_awaited()
    assert unit.work.complete.call_args.args[1].reference == episode_id


def test_accepted_proposals_keep_ordered_context_basis_without_storage():
    first, second = uuid7(), uuid7()
    changes = SimpleNamespace(
        experiences=(
            CandidateExperienceDraft(
                "proposal:1",
                "group:1",
                (2, 1),
                CandidateFactClass.EXTERNAL_CLAIM,
                "对方说下雨了。",
                None,
                "private",
            ),
        ),
        owner_drafts=(),
        exact_life_queries=(),
        action_choices=(),
        web_research_requests=(),
        visual_observation_requests=(),
        codex_delegations=(),
        rejections=(),
    )
    result = cast(Any, SimpleNamespace(change_set=changes))
    candidates = accepted_candidates(
        result, cast(Any, SimpleNamespace(basis_item_ids=((1, first), (2, second))))
    )
    assert len(candidates) == 1
    assert candidates[0].basis_context_ids == (second, first)
    assert candidates[0].owner_identity == "experience"
    assert candidates[0].fact_class is CandidateFactClass.EXTERNAL_CLAIM
    with pytest.raises(CandidateViolation, match="CANDIDATE-BASIS-MISSING"):
        accepted_candidates(
            result, cast(Any, SimpleNamespace(basis_item_ids=((1, first),)))
        )


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
