"""Autonomous trace projection must not invent an accepted human message."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition.api import CognitionOperationSnapshot
from armi_interaction.api import OpportunityId
from armi_runtime.application.creator_projection import operation_wire
from armi_runtime.application.operation_assembler import (
    RuntimeCreatorOperationAssembler,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("settled", [False, True])
async def test_autonomous_operation_has_real_origin_without_creator_acceptance(
    settled: bool,
) -> None:
    root = uuid7()

    @asynccontextmanager
    async def transaction(**_kwargs):
        yield SimpleNamespace(transaction=object())

    opportunity = AsyncMock()
    opportunity.operation_snapshot.return_value = SimpleNamespace(
        purpose="consider_autonomous_life",
        evidence_id=None,
        scene_id=None,
        root_opportunity_id=root,
        current_opportunity_id=root,
        disposition="resolved" if settled else "open",
        reconsideration_no=0,
    )
    cognition = AsyncMock()
    cognition.operation_snapshot.return_value = CognitionOperationSnapshot(
        "completed" if settled else None,
        None,
        "no_change" if settled else None,
        None,
    )
    interaction, evidence, expression = AsyncMock(), AsyncMock(), AsyncMock()
    expression.operation_snapshot.return_value = None
    assembler = RuntimeCreatorOperationAssembler(
        factory=cast(Any, SimpleNamespace(unit_of_work=transaction)),
        creator_party_id=uuid7(),
        opportunity=opportunity,
        cognition=cognition,
        interaction=interaction,
        evidence=evidence,
        expression=expression,
        effect=AsyncMock(),
        codex=AsyncMock(),
        codex_executions=AsyncMock(),
    )
    operation = await assembler.get(OpportunityId(root))
    assert operation.acceptance is None
    assert operation.autonomous_opportunity_id == OpportunityId(root)
    wire = operation_wire(operation)
    assert cast(dict, wire["details"])["operation_ref"] == str(root)
    assert wire["status"] != "accepted"
    interaction.operation_acceptance.assert_not_awaited()
    evidence.snapshot.assert_not_awaited()
