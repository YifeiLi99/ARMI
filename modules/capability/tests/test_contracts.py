"""CON-CAPABILITY and DOM-POLICY contract checks."""

from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_capability.api import (
    CapabilityAuthorizationOutcome,
    CapabilityConsumptionRequest,
    CapabilityConsumptionResult,
    CapabilityDecisionId,
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequestDraft,
    CapabilityRequestId,
    CapabilityViolation,
    CodexDelegatedWorkScope,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorSceneReplyScope,
    GrantStatus,
    PermissionGrant,
    PermissionGrantId,
)


def test_scope_cannot_be_wildcarded_or_expanded() -> None:
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-REPLY-SCOPE"):
        CreatorSceneReplyScope(uuid7(), uuid7(), uuid7(), 59, 1, 1)
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-CODEX-SCOPE"):
        CodexDelegatedWorkScope(3601)
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-REQUEST"):
        CapabilityRequestDraft(
            "proposal:1",
            "group:1",
            (1,),
            CapabilityKind.CODEX_DELEGATED_WORK,
            CapabilityOperation.SEND,
            CodexDelegatedWorkScope(60),
        )


def test_grant_identity_must_match_creator_scope() -> None:
    now = datetime.now(UTC)
    scope = CreatorSceneReplyScope(uuid7(), uuid7(), uuid7(), 60, 1, 64)
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-GRANT"):
        PermissionGrant(
            PermissionGrantId(uuid7()),
            CapabilityRequestId(uuid7()),
            CapabilityKind.CREATOR_SCENE_REPLY,
            CapabilityOperation.SEND,
            uuid7(),
            scope.scene_id,
            scope.creator_party_id,
            scope,
            now,
            now + timedelta(seconds=60),
            0,
            GrantStatus.ACTIVE,
        )


def test_limit_requires_an_explicit_narrowing_field() -> None:
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-DECISION"):
        CreatorGrantCommand(
            CapabilityDecisionId(uuid7()),
            CapabilityRequestId(uuid7()),
            1,
            CreatorGrantDecision.LIMIT,
        )
    command = CreatorGrantCommand(
        CapabilityDecisionId(uuid7()),
        CapabilityRequestId(uuid7()),
        1,
        CreatorGrantDecision.LIMIT,
        max_uses=1,
    )
    assert command.max_uses == 1


def test_effect_consumption_contract_keeps_authorization_owner_explicit() -> None:
    request = CapabilityConsumptionRequest(
        "creator.scene.reply",
        "send",
        uuid7(),
        uuid7(),
        uuid7(),
        "respond_to_creator",
        "creator_response",
        64,
    )
    result = CapabilityConsumptionResult(
        CapabilityAuthorizationOutcome.ALLOWED,
        "POLICY-GRANT-ALLOWED",
        uuid7(),
        datetime.now(UTC),
    )
    assert request.payload_bytes == 64
    assert result.grant_id is not None
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-CONSUMPTION"):
        CapabilityConsumptionResult(
            CapabilityAuthorizationOutcome.DENIED,
            "POLICY-GRANT-NOT-CURRENT",
            uuid7(),
            datetime.now(UTC),
        )
