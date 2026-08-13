from __future__ import annotations

from typing import cast
from uuid import uuid7

import pytest
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceSourceKind,
    EvidenceViolation,
    ExperienceEvidenceLink,
)
from armi_evidence.bootstrap import bootstrap_evidence
from armi_runtime_foundation import PostgreSQLTransactionAccess


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, values: tuple[object, ...]) -> None:
        self.calls.append((sql, values))


class _Unit:
    def __init__(self) -> None:
        self.transaction = _Connection()


def _creator_draft() -> EvidenceDraft:
    return EvidenceDraft(
        evidence_id=EvidenceId(uuid7()),
        subject_id=uuid7(),
        scene_id=uuid7(),
        context_party_id=uuid7(),
        artifact_id=uuid7(),
        source_kind=EvidenceSourceKind.CREATOR_INPUT,
        privacy_scope=EvidencePrivacyScope.CREATOR_VISIBLE,
        interaction_id=uuid7(),
    )


def test_evidence_source_identity_is_owned_by_contract() -> None:
    with pytest.raises(EvidenceViolation, match="EVIDENCE-SOURCE-SHAPE"):
        EvidenceDraft(
            evidence_id=EvidenceId(uuid7()),
            subject_id=uuid7(),
            scene_id=uuid7(),
            context_party_id=uuid7(),
            artifact_id=uuid7(),
            source_kind=EvidenceSourceKind.WEB_SEARCH,
            privacy_scope=EvidencePrivacyScope.PRIVATE,
            web_observation_request_id=uuid7(),
        )


@pytest.mark.asyncio
async def test_writer_uses_caller_transaction_for_acceptance_and_link() -> None:
    unit = _Unit()
    module = bootstrap_evidence()
    draft = _creator_draft()
    transaction = cast(PostgreSQLTransactionAccess, unit)
    assert await module.write.accept(transaction, draft) == draft.evidence_id
    await module.write.link_experience(
        transaction,
        ExperienceEvidenceLink(uuid7(), draft.evidence_id, uuid7(), 1),
    )
    assert "INSERT INTO armi.external_evidence" in unit.transaction.calls[0][0]
    assert "INSERT INTO armi.experience_evidence_links" in unit.transaction.calls[1][0]
