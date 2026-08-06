from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

import pytest
from armi_kernel.application import (
    CreatorPromptDeactivateCommand,
    CreatorPromptRevisionCommand,
    CreatorPromptViolation,
    PromptKind,
)
from armi_kernel.contracts import TraceId
from armi_runtime.composition.creator_prompts import CreatorPromptService


def _service_without_io() -> CreatorPromptService:
    unavailable = cast(Any, object())
    return CreatorPromptService(
        creator_party_id=uuid7(),
        storage=unavailable,
        catalog=unavailable,
        repository=unavailable,
        unit_of_work_factory=unavailable,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt_kind",
    [PromptKind.PERSONALITY_ANCHOR, PromptKind.SUBJECT_GUIDANCE],
)
async def test_creator_prompt_service_rejects_cross_authority_writes_before_io(
    prompt_kind: PromptKind,
) -> None:
    service = _service_without_io()

    with pytest.raises(CreatorPromptViolation, match="SCOPE-PROMPT-NOT-WRITABLE"):
        await service.revise(
            CreatorPromptRevisionCommand(
                prompt_kind,
                None,
                "不能越权写入",
                TraceId("1" * 32),
            )
        )
    with pytest.raises(CreatorPromptViolation, match="SCOPE-PROMPT-NOT-WRITABLE"):
        await service.deactivate(
            CreatorPromptDeactivateCommand(
                prompt_kind,
                uuid7(),
                TraceId("2" * 32),
            )
        )
