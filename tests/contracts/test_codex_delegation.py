from __future__ import annotations

from uuid import uuid7

import pytest
from armi_kernel.application import (
    CodexDelegationViolation,
    CreatorCodexTaskCommand,
)
from armi_kernel.contracts import IdempotencyKey, TraceId


def test_creator_codex_task_command_preserves_exact_objective() -> None:
    command = CreatorCodexTaskCommand(
        "default",
        "  保留换行\n并生成交付物。  ",
        IdempotencyKey("task-request-1"),
        TraceId("1" * 32),
    )
    assert command.objective == "  保留换行\n并生成交付物。  "


@pytest.mark.parametrize(
    "objective",
    ["", " \r\n ", "contains\x00nul", "x" * (16 * 1024 + 1)],
)
def test_creator_codex_task_command_rejects_invalid_objective(objective: str) -> None:
    with pytest.raises(CodexDelegationViolation, match="CODEX-TASK-REQUEST"):
        CreatorCodexTaskCommand(
            "default",
            objective,
            IdempotencyKey(f"task-{uuid7()}"),
            TraceId("2" * 32),
        )
