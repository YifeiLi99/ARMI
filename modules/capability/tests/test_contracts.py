"""CON-CAPABILITY and DOM-POLICY contract checks."""

from datetime import UTC, datetime, timedelta
from typing import cast
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
    GrantStatus,
    PermissionGrant,
    PermissionGrantId,
)


def test_scope_cannot_be_wildcarded_or_expanded() -> None:
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-CODEX-SCOPE"):
        CodexDelegatedWorkScope(3601)
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-REQUEST"):
        CapabilityRequestDraft(
            "proposal:1",
            "group:1",
            (1,),
            CapabilityKind.CODEX_DELEGATED_WORK,
            cast(CapabilityOperation, "send"),
            CodexDelegatedWorkScope(60),
        )


def test_codex_grant_must_stay_within_one_hour() -> None:
    now = datetime.now(UTC)
    scope = CodexDelegatedWorkScope(60)
    with pytest.raises(CapabilityViolation, match="CON-CAPABILITY-GRANT"):
        PermissionGrant(
            PermissionGrantId(uuid7()),
            CapabilityRequestId(uuid7()),
            CapabilityKind.CODEX_DELEGATED_WORK,
            CapabilityOperation.EXECUTE,
            uuid7(),
            uuid7(),
            uuid7(),
            scope,
            now,
            now + timedelta(seconds=3601),
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
        uuid7(),
        uuid7(),
        "codex.delegated-work",
        "execute",
        uuid7(),
        uuid7(),
        uuid7(),
        "delegate_codex_work",
        "codex_delegation",
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
