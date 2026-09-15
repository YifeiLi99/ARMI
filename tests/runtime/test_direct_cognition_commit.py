"""Validation facts and Subject Commit share the final transaction."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_kernel.application import CandidateFactClass, SubjectCommitViolation
from armi_memory.api import MemoryFormationRequest, MemorySourceKind
from armi_runtime.composition.candidate_validation_tool import (
    bootstrap_memory_cognition,
)
from armi_runtime.composition.subject_commit_pipeline import SubjectCommitPipeline


class _Submission(SubjectCommitPipeline):
    @staticmethod
    def _bind_accepted_owner_payloads(snapshot, change_set):
        return snapshot


def test_commit_reuses_owner_object_without_decoding_its_archive():
    memory = bootstrap_memory_cognition()
    draft = memory.bind_formation(
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
    changes = cast(Any, SimpleNamespace(owner_drafts=(draft,)))
    result = SubjectCommitPipeline.collect_owner_drafts(changes)
    assert result.memory[0] is draft.candidate
    with pytest.raises(SubjectCommitViolation, match="SUBJECT-CANDIDATE-OWNER"):
        SubjectCommitPipeline.collect_owner_drafts(
            cast(Any, SimpleNamespace(owner_drafts=(replace(draft, owner="mood"),)))
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_validation_and_application_commit_or_rollback_together(fail) -> None:
    committed: list[str] = []
    units: list[object] = []

    @asynccontextmanager
    async def transaction():
        pending: list[str] = []
        unit = SimpleNamespace(pending=pending)
        units.append(unit)
        yield unit
        committed.extend(pending)

    async def record(unit, lease):
        assert unit is units[0]
        unit.pending.append("validation")

    async def settle(unit, **_kwargs):
        assert unit is units[0]
        assert unit.pending == ["validation"]
        unit.pending.extend(
            ["subject", "intent", "effect", "application", "work_completed"]
        )
        if fail:
            raise SubjectCommitViolation("SUBJECT-INJECTED")
        return object()

    submission = object.__new__(_Submission)
    submission._factory = cast(Any, SimpleNamespace(unit_of_work=transaction))
    submission._repository = cast(
        Any, SimpleNamespace(snapshot=AsyncMock(return_value=object()), settle=settle)
    )
    submission._fault_injector = lambda _event: None
    submission._wake_downstream = lambda: None
    submission._notify = AsyncMock()
    submission._notify_voice = AsyncMock()
    changes = SimpleNamespace(
        owner_drafts=(),
        action_choices=(),
        web_research_requests=(),
        exact_life_queries=(),
        visual_observation_requests=(),
    )
    candidate = SimpleNamespace(
        episode_id=uuid7(), result=SimpleNamespace(change_set=changes), record=record
    )
    if fail:
        with pytest.raises(SubjectCommitViolation, match="SUBJECT-INJECTED"):
            await submission.submit(cast(Any, object()), cast(Any, candidate))
        assert committed == []
    else:
        await submission.submit(cast(Any, object()), cast(Any, candidate))
        assert committed == [
            "validation",
            "subject",
            "intent",
            "effect",
            "application",
            "work_completed",
        ]
    assert len(units) == 1
