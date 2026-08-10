"""CON-RESPONSE and DOM-NO-ACTION contract checks."""

from __future__ import annotations

from uuid import uuid7

import pytest
from armi_kernel.application import (
    ActionIntentId,
    CreatorReplyDraft,
    CreatorResponseOperationId,
    FormalNoActionDraft,
    FormalNoActionId,
    FormalNoActionKind,
    FormalNoActionReason,
    ResponseAdmissionResult,
    ResponseAdmissionStatus,
    ResponseViolation,
)


def test_creator_reply_preserves_exact_utf8_and_scope() -> None:
    content = " 我会认真回应。\n".encode()
    reply = CreatorReplyDraft(
        "proposal:1",
        "group:1",
        (2, 4, 5),
        uuid7(),
        uuid7(),
        uuid7(),
        content,
    )
    assert reply.content_bytes == content
    assert reply.capability_kind == "creator.scene.reply"
    assert reply.operation == "send"


@pytest.mark.parametrize("content", [b"", b" \r\n\t", b"a\x00b", b"\xff"])
def test_creator_reply_rejects_invalid_content(content: bytes) -> None:
    with pytest.raises(ResponseViolation, match="CON-RESPONSE-REPLY"):
        CreatorReplyDraft(
            "proposal:1",
            "group:1",
            (1,),
            uuid7(),
            uuid7(),
            uuid7(),
            content,
        )


def test_formal_no_action_reason_is_not_interchangeable() -> None:
    declined = FormalNoActionDraft(
        "proposal:1",
        "group:1",
        (2,),
        FormalNoActionKind.DECLINE,
        FormalNoActionReason.SUBJECTIVE_REFUSAL,
    )
    assert declined.kind is FormalNoActionKind.DECLINE
    with pytest.raises(ResponseViolation, match="CON-RESPONSE-NO-ACTION"):
        FormalNoActionDraft(
            "proposal:1",
            "group:1",
            (2,),
            FormalNoActionKind.NO_ACTION,
            FormalNoActionReason.SUBJECTIVE_REFUSAL,
        )


def test_admission_result_distinguishes_acceptance_and_no_action() -> None:
    accepted = ResponseAdmissionResult(
        CreatorResponseOperationId(uuid7()),
        ResponseAdmissionStatus.ACCEPTED,
        action_intent_id=ActionIntentId(uuid7()),
        grant_ref=uuid7(),
    )
    assert accepted.status is ResponseAdmissionStatus.ACCEPTED
    no_action = ResponseAdmissionResult(
        CreatorResponseOperationId(uuid7()),
        ResponseAdmissionStatus.NO_ACTION,
        no_action_id=FormalNoActionId(uuid7()),
    )
    assert no_action.status is ResponseAdmissionStatus.NO_ACTION
