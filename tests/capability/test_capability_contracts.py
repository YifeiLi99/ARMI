"""CON-CAPABILITY and DOM-POLICY contract checks."""

from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_kernel.application import (
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
    GrantMatcher,
    GrantStatus,
    PermissionGrant,
    PermissionGrantId,
)


def test_reply_scope_and_grant_match_exact_boundaries() -> None:
    subject_id, scene_id, creator_id = uuid7(), uuid7(), uuid7()
    scope = CreatorSceneReplyScope(subject_id, scene_id, creator_id, 60, 2, 64)
    request_id = CapabilityRequestId(uuid7())
    now = datetime.now(UTC)
    grant = PermissionGrant(
        PermissionGrantId(uuid7()),
        request_id,
        CapabilityKind.CREATOR_SCENE_REPLY,
        CapabilityOperation.SEND,
        subject_id,
        scene_id,
        creator_id,
        scope,
        now,
        now + timedelta(seconds=60),
        0,
        GrantStatus.ACTIVE,
    )
    assert GrantMatcher.permits(
        grant,
        now=now,
        subject_id=subject_id,
        scene_id=scene_id,
        creator_party_id=creator_id,
        purpose="respond_to_creator",
        payload_bytes=64,
    )
    assert not GrantMatcher.permits(
        grant,
        now=now,
        subject_id=subject_id,
        scene_id=uuid7(),
        creator_party_id=creator_id,
        purpose="respond_to_creator",
        payload_bytes=64,
    )
    assert not GrantMatcher.permits(
        grant,
        now=now + timedelta(seconds=60),
        subject_id=subject_id,
        scene_id=scene_id,
        creator_party_id=creator_id,
        purpose="respond_to_creator",
        payload_bytes=64,
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


def test_codex_grant_is_single_use_ephemeral_and_networkless() -> None:
    now = datetime.now(UTC)
    subject_id, scene_id, creator_id = uuid7(), uuid7(), uuid7()
    grant = PermissionGrant(
        PermissionGrantId(uuid7()),
        CapabilityRequestId(uuid7()),
        CapabilityKind.CODEX_DELEGATED_WORK,
        CapabilityOperation.EXECUTE,
        subject_id,
        scene_id,
        creator_id,
        CodexDelegatedWorkScope(600),
        now,
        now + timedelta(seconds=600),
        0,
        GrantStatus.ACTIVE,
    )
    assert GrantMatcher.permits_codex(
        grant,
        now=now,
        subject_id=subject_id,
        scene_id=scene_id,
        creator_party_id=creator_id,
        purpose="delegate_codex_work",
    )
    consumed = PermissionGrant(
        grant.grant_id,
        grant.request_id,
        grant.capability,
        grant.operation,
        grant.subject_id,
        grant.scene_id,
        grant.creator_party_id,
        grant.scope,
        grant.valid_from,
        grant.valid_until,
        1,
        grant.status,
    )
    assert not GrantMatcher.permits_codex(
        consumed,
        now=now,
        subject_id=subject_id,
        scene_id=scene_id,
        creator_party_id=creator_id,
        purpose="delegate_codex_work",
    )
    assert not GrantMatcher.permits_codex(
        grant,
        now=now,
        subject_id=uuid7(),
        scene_id=scene_id,
        creator_party_id=creator_id,
        purpose="delegate_codex_work",
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
