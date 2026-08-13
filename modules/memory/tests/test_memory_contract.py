from uuid import uuid7

import pytest
from armi_kernel.application import CandidateFactClass
from armi_memory._application import MemoryApplication
from armi_memory.api import (
    CandidateMemoryRevisionDraft,
    MemoryAccessibility,
    MemoryFormationRequest,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemoryRevisionRequest,
    MemorySourceKind,
    MemoryViolation,
)


def test_formation_round_trip_uses_canonical_memory_owner_payload() -> None:
    cognition = MemoryApplication()
    draft = cognition.bind_formation(
        MemoryFormationRequest(
            "proposal:2",
            "group:1",
            (1,),
            CandidateFactClass.EXTERNAL_CLAIM,
            "proposal:1",
            MemorySourceKind.REPORTED,
            "创造者说今天会下雨。",
        )
    )

    assert draft.owner == "memory"
    decoded = cognition.decode(draft.canonical_payload)
    assert decoded.summary == "创造者说今天会下雨。"
    assert decoded.source_kind is MemorySourceKind.REPORTED


def test_reinterpretation_round_trip_preserves_relation_and_head() -> None:
    cognition = MemoryApplication()
    memory_id = uuid7()
    related_id = uuid7()
    draft = cognition.bind_revision(
        MemoryRevisionRequest(
            "proposal:3",
            "group:1",
            (2,),
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            memory_id,
            uuid7(),
            4,
            MemoryRevisionKind.REINTERPRETED,
            MemoryAccessibility.AVAILABLE,
            MemorySourceKind.EXPERIENCED,
            "现在我对那件事有了新的理解。",
            None,
            related_id,
            MemoryRelationKind.REINTERPRETS,
        )
    )

    decoded = cognition.decode(draft.canonical_payload)
    assert isinstance(decoded, CandidateMemoryRevisionDraft)
    assert decoded.memory_id == memory_id
    assert decoded.expected_head_version == 4
    assert decoded.related_memory_id == related_id
    assert decoded.relation_kind is MemoryRelationKind.REINTERPRETS


def test_forget_requires_forgotten_accessibility() -> None:
    with pytest.raises(MemoryViolation):
        MemoryApplication().bind_revision(
            MemoryRevisionRequest(
                "proposal:2",
                "group:1",
                (1,),
                CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                uuid7(),
                uuid7(),
                1,
                MemoryRevisionKind.FORGOTTEN,
                MemoryAccessibility.AVAILABLE,
                MemorySourceKind.EXPERIENCED,
                "任意摘要",
                None,
            )
        )
