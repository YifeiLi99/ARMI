"""Nested delegated results retain the original human or autonomous source."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_runtime.application.opportunity_origin import RuntimeOpportunityOrigin
from armi_runtime_foundation import RuntimeTransactionFailure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose", ["consider_creator_input", "consider_autonomous_life"]
)
async def test_nested_codex_results_resolve_original_owner_facts(purpose):
    original, first_result, second_result, child = (uuid7() for _ in range(4))
    opportunities, evidence, codex, effects, expression = (
        AsyncMock() for _ in range(5)
    )
    opportunities.origin_snapshot.side_effect = [
        (second_result, None, "consider_web_evidence"),
        (second_result, uuid7(), "consider_codex_result"),
        (first_result, uuid7(), "consider_codex_result"),
        (original, None, purpose),
    ]
    evidence.snapshot.return_value = SimpleNamespace(codex_verification_id=uuid7())
    effects.by_effect_id.return_value = SimpleNamespace(action_intent_id=uuid7())
    expression.intent_snapshot.side_effect = [
        SimpleNamespace(root_opportunity_id=first_result),
        SimpleNamespace(root_opportunity_id=original),
    ]
    reader = RuntimeOpportunityOrigin(
        opportunities=opportunities,
        evidence=evidence,
        codex=codex,
        effects=effects,
        expression=expression,
    )
    assert await reader.resolve(AsyncMock(), child) == (original, purpose)
    assert evidence.snapshot.await_count == 2
    assert [
        call.kwargs["opportunity_id"]
        for call in opportunities.origin_snapshot.await_args_list
    ] == [
        child,
        second_result,
        first_result,
        original,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["missing_evidence", "cycle"])
async def test_broken_lineage_is_rejected_without_guessing_origin(broken):
    original, other = uuid7(), uuid7()
    opportunities = AsyncMock()
    opportunities.origin_snapshot.side_effect = (
        [(original, None, "consider_codex_result")]
        if broken == "missing_evidence"
        else [
            (other, None, "consider_autonomous_life"),
            (original, None, "consider_autonomous_life"),
        ]
    )
    reader = RuntimeOpportunityOrigin(
        opportunities=opportunities,
        evidence=AsyncMock(),
        codex=AsyncMock(),
        effects=AsyncMock(),
        expression=AsyncMock(),
    )
    with pytest.raises(RuntimeTransactionFailure, match="LIFE-AUTONOMY-CALL-ORIGIN"):
        await reader.resolve(AsyncMock(), original)
