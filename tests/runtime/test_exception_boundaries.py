from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    CreatorInputCommand,
    CreatorInputViolation,
    StagedArtifact,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId
from armi_runtime.adapters.persistence.creator_input import CreatorInputContext
from armi_runtime.adapters.transaction_errors import (
    CommitState,
    DatabaseFailureKind,
    DatabaseTransactionError,
)
from armi_runtime.composition.creator_input import EvidenceAcceptanceTransaction


class _StagingStorage:
    def __init__(self) -> None:
        self.discarded: list[StagedArtifact] = []
        self.publish_called = False

    async def stage(self, _chunks: object, policy: ArtifactPolicy) -> StagedArtifact:
        return StagedArtifact(
            ArtifactId(uuid7()),
            Digest.from_bytes(b"message"),
            len(b"message"),
            policy,
        )

    async def discard(self, staged: StagedArtifact) -> None:
        self.discarded.append(staged)

    async def publish(self, _staged: StagedArtifact) -> None:
        self.publish_called = True
        raise AssertionError("publish must not run after an unavailable lookup")


@pytest.mark.asyncio
async def test_creator_input_lookup_failure_discards_stage_without_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creator_party_id = uuid7()
    context = CreatorInputContext(uuid7(), uuid7(), creator_party_id)
    storage = _StagingStorage()

    async def read_context(
        _self: EvidenceAcceptanceTransaction, _scene_key: str
    ) -> CreatorInputContext:
        return context

    async def fail_lookup(
        _self: EvidenceAcceptanceTransaction,
        _command: CreatorInputCommand,
        _context: CreatorInputContext,
        _request_digest: Digest,
    ) -> None:
        raise DatabaseTransactionError(
            "DB-TX-POOL-TIMEOUT",
            DatabaseFailureKind.DEPENDENCY,
            False,
            CommitState.NOT_STARTED,
        )

    monkeypatch.setattr(EvidenceAcceptanceTransaction, "_read_context", read_context)
    monkeypatch.setattr(EvidenceAcceptanceTransaction, "_read_existing", fail_lookup)
    transaction = EvidenceAcceptanceTransaction(
        creator_party_id=creator_party_id,
        storage=cast(Any, storage),
        catalog=cast(Any, object()),
        repository=cast(Any, object()),
        unit_of_work_factory=cast(Any, SimpleNamespace(environment_id=uuid7())),
        subject_state=cast(Any, object()),
        notifier=None,
    )

    with pytest.raises(CreatorInputViolation) as raised:
        await transaction.accept(
            CreatorInputCommand(
                scene_key="default",
                message="message",
                idempotency_key=IdempotencyKey("exception-boundary-1"),
                trace_id=TraceId("1" * 32),
            )
        )

    assert raised.value.code == "DB-INPUT-UNAVAILABLE"
    assert len(storage.discarded) == 1
    assert not storage.publish_called
