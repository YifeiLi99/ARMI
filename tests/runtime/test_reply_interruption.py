from uuid import uuid7

import pytest
from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    OpportunityId,
)
from armi_kernel.contracts import Digest
from armi_runtime.application.creator_contract import OperationOutcomeResponse
from armi_runtime.application.creator_projection import operation_wire
from pydantic import TypeAdapter


@pytest.mark.parametrize(
    "phase",
    (
        CreatorOperationPhase.FAILED,
        CreatorOperationPhase.EFFECT_CANCELLED,
        CreatorOperationPhase.EFFECT_UNKNOWN,
    ),
)
def test_interrupted_conversation_returns_terminal_without_recovery_action(
    phase: CreatorOperationPhase,
) -> None:
    acceptance = CreatorInputAcceptance(
        CreatorInteractionId(uuid7()),
        EvidenceId(uuid7()),
        OpportunityId(uuid7()),
        Digest.from_bytes(b"request"),
        Digest.from_bytes(b"input"),
        False,
    )
    before_effect = phase is CreatorOperationPhase.FAILED
    operation = CreatorOperation(
        acceptance,
        phase,
        failure_code="COGNITION-RUNTIME-INTERRUPTED"
        if before_effect
        else "ACTION-RUNTIME-INTERRUPTED",
        effect_ref=None if before_effect else uuid7(),
        operation_kind="cognition" if before_effect else "creator_response",
    )
    wire = operation_wire(operation)
    TypeAdapter(OperationOutcomeResponse).validate_python(wire)
    assert wire["status"] == "failed"
    assert "waiting_for" not in wire
    assert "recovery_action" not in wire
    details = wire["details"]
    assert isinstance(details, dict)
    assert "policy_decision_ref" not in details
    assert "capability_request_ref" not in details
    assert "permission_grant_ref" not in details
