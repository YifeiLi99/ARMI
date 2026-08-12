from __future__ import annotations

from uuid import uuid7

import pytest
from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    OpportunityId,
    OtherHumanInputAcceptance,
    OtherHumanInputCommand,
    OtherHumanInputViolation,
    OtherHumanInteractionId,
    OtherHumanPartyKey,
    OtherHumanPartyView,
    RegisterOtherHumanPartyCommand,
    SceneKey,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId


def test_other_human_role_is_structurally_distinct_from_creator() -> None:
    trace = TraceId("1" * 32)
    party = OtherHumanPartyView(uuid7(), OtherHumanPartyKey("friend-1"), "朋友")
    assert party.identity_assurance == "caller_declared"
    with pytest.raises(OtherHumanInputViolation, match="CON-OTHER-HUMAN-ROLE"):
        RegisterOtherHumanPartyCommand(
            OtherHumanPartyKey("friend-1"),
            "朋友",
            "creator",  # type: ignore[arg-type]
            trace,
        )


def test_other_human_input_binds_party_scene_and_idempotency() -> None:
    command = OtherHumanInputCommand(
        OtherHumanPartyKey("friend-1"),
        SceneKey("default"),
        "你好",
        IdempotencyKey("message-1"),
        TraceId("1" * 32),
    )
    acceptance = OtherHumanInputAcceptance(
        uuid7(),
        uuid7(),
        OtherHumanInteractionId(uuid7()),
        EvidenceId(uuid7()),
        OpportunityId(uuid7()),
        Digest.from_bytes(b"request"),
        Digest.from_bytes(command.message_bytes),
        True,
    )
    assert command.message_bytes == "你好".encode()
    assert acceptance.newly_accepted is True


@pytest.mark.parametrize("message", ["", "   ", "\x00"])
def test_other_human_input_rejects_invalid_message(message: str) -> None:
    with pytest.raises(OtherHumanInputViolation):
        OtherHumanInputCommand(
            OtherHumanPartyKey("friend-1"),
            SceneKey("default"),
            message,
            IdempotencyKey("message-1"),
            TraceId("2" * 32),
        )
