"""CON-RESPONSE and DOM-NO-ACTION contract checks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_expression._postgresql import PostgreSQLExpressionOwner
from armi_expression._recovery import ExpressionRecoveryParticipant
from armi_expression.api import (
    CreatorReplyDraft,
    DeclaredResponseEffectDraft,
    ExpressionCommitContext,
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
    ResponseViolation,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import RecoveryScope


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


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ("text", "voice", "qq"))
async def test_creator_reply_registers_effect_in_subject_transaction(
    channel: str,
) -> None:
    subject, scene, creator = uuid7(), uuid7(), uuid7()
    context = ExpressionCommitContext(
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
        subject,
        uuid7(),
        scene,
        creator,
        None,
        "consider_creator_input",
        TraceId(uuid7().hex),
    )
    reply = CreatorReplyDraft(
        "proposal:1", "group:1", (1,), subject, scene, creator, b"reply"
    )
    transaction = AsyncMock()
    unit = SimpleNamespace(
        transaction=transaction, environment_id=uuid7(), audit=AsyncMock()
    )
    registration = AsyncMock()
    registration.register_declared_response.return_value = uuid7()
    route = AsyncMock()
    route.effect_route.return_value = SimpleNamespace(
        destination_kind="external_private" if channel == "qq" else "creator_inbox",
        destination_party_id=creator,
        destination_binding_id=uuid7() if channel == "qq" else None,
    )
    voice = AsyncMock()
    voice.turn_for_opportunity.return_value = uuid7() if channel == "voice" else None
    owner = PostgreSQLExpressionOwner(
        AsyncMock(),
        AsyncMock(),
        registration,
        route,
        AsyncMock(),
        voice,
    )
    artifact = SimpleNamespace(
        artifact_id=SimpleNamespace(value=uuid7()),
        content_digest=Digest.from_bytes(b"reply"),
    )
    await owner._finish_creator_response(
        cast(Any, unit),
        context=context,
        commit_id=uuid7(),
        reply=reply,
        response_artifact=cast(Any, artifact),
        action_id=uuid7(),
        revision_id=uuid7(),
    )
    registration.register_declared_response.assert_awaited_once()
    call = registration.register_declared_response.await_args
    assert call is not None and call.args[0] is transaction
    draft = call.args[1]
    assert draft.effect_kind == "creator_response"
    assert (
        draft.destination_kind
        == {
            "text": "creator_inbox",
            "voice": "live_voice_audio",
            "qq": "external_private",
        }[channel]
    )
    assert draft.live_voice_turn_id == voice.turn_for_opportunity.return_value
    assert draft.authorization_basis == (
        "runtime_builtin" if channel == "text" else "runtime_configuration"
    )


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


@pytest.mark.asyncio
async def test_recovery_does_not_treat_missing_registration_work_as_corruption() -> (
    None
):
    intent_id = uuid7()
    result = AsyncMock()
    result.fetchall.return_value = ((intent_id,),)
    transaction = AsyncMock()
    transaction.execute.return_value = result
    scope = RecoveryScope(uuid7(), uuid7(), uuid7(), uuid7(), uuid7(), 1)

    contribution = await ExpressionRecoveryParticipant().recover(transaction, scope, ())

    assert contribution.findings == ()
    assert contribution.metrics == ()
    transaction.execute.assert_not_awaited()
