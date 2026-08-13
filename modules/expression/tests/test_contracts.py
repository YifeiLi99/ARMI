"""CON-RESPONSE and DOM-NO-ACTION contract checks."""

from __future__ import annotations

from uuid import uuid7

import pytest
from armi_expression.api import (
    ActionIntentId,
    CreatorReplyDraft,
    CreatorResponseOperationId,
    DeclaredResponseEffectDraft,
    FormalNoActionDraft,
    FormalNoActionId,
    FormalNoActionKind,
    FormalNoActionReason,
    ResponseAdmissionResult,
    ResponseAdmissionStatus,
    ResponseViolation,
)
from armi_kernel.contracts import Digest, TraceId


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


def test_declared_response_effect_draft_freezes_the_cross_owner_contract() -> None:
    ids = tuple(uuid7() for _ in range(9))
    draft = DeclaredResponseEffectDraft(
        action_intent_revision_id=ids[0],
        action_intent_id=ids[1],
        operation_ref=ids[2],
        subject_id=ids[3],
        scene_id=ids[4],
        context_party_id=ids[5],
        payload_artifact_id=ids[6],
        payload_digest=Digest.from_bytes(b"hello"),
        payload_bytes=5,
        effect_kind="external_private_delivery",
        capability_kind="external.private.message.send",
        audience_scope="other_human",
        authorization_basis="runtime_configuration",
        destination_kind="external_private",
        destination_party_id=ids[7],
        destination_binding_id=ids[8],
        trace_id=TraceId(uuid7().hex),
        max_attempts=1,
    )
    assert draft.destination_binding_id == ids[8]
