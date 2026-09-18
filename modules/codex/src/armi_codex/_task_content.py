"""Persist only the objective and execution options of a delegation."""

import json

from ._delegation_contract import CodexTaskSourceId
from ._runner_contract import CodexModel, CodexReasoningEffort


def task_manifest(
    task_source_id: CodexTaskSourceId,
    objective: str,
    model_id: CodexModel,
    reasoning_effort: CodexReasoningEffort,
    web_search: bool,
) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": "armi.codex-task-source.v3",
                "task_source_id": str(task_source_id.value),
                "objective": objective,
                "deadline_seconds": 900,
                "model_id": model_id.value,
                "reasoning_effort": reasoning_effort.value,
                "web_search": web_search,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
