"""Technology-neutral contracts for one isolated Codex execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

_CODE = re.compile(r"^CODEX-[A-Z0-9-]+$", re.ASCII)
_MAX_TEXT_BYTES = 16 * 1024


class CodexRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class CodexModel(StrEnum):
    SOL = "gpt-5.6-sol"
    TERRA = "gpt-5.6-terra"
    LUNA = "gpt-5.6-luna"


class CodexReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class CodexRunnerViolation(RuntimeError):
    """Expose a stable failure code without task, path, output or auth content."""

    __slots__ = ("cleanup_error_code", "code", "outcome_unknown")

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("Codex runner violation code is invalid")
        if type(outcome_unknown) is not bool:
            raise ValueError("Codex runner outcome flag is invalid")
        self.code = code
        self.outcome_unknown = outcome_unknown
        self.cleanup_error_code: str | None = None
        super().__init__("Codex runner operation failed")

    def record_cleanup_failure(self, code: str) -> None:
        """Keep cleanup failure secondary to the original execution result."""

        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("Codex runner cleanup violation code is invalid")
        if self.cleanup_error_code is None:
            self.cleanup_error_code = code

    def __str__(self) -> str:
        return f"{self.code}: Codex runner operation failed"


@dataclass(frozen=True, slots=True)
class CodexExecutionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CODEX-EXECUTION-ID")


@dataclass(frozen=True, slots=True)
class CodexUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int or value < 0
                for value in (
                    self.input_tokens,
                    self.cached_input_tokens,
                    self.output_tokens,
                )
            )
            or self.cached_input_tokens > self.input_tokens
        ):
            raise CodexRunnerViolation("CODEX-USAGE")


@dataclass(frozen=True, slots=True)
class CodexTaskManifest:
    execution_id: CodexExecutionId
    task_id: UUID
    effect_id: UUID
    objective: str
    deadline_seconds: int
    model_id: CodexModel = CodexModel.LUNA
    reasoning_effort: CodexReasoningEffort = CodexReasoningEffort.MEDIUM
    web_search: bool = False
    schema_kind: str = "armi.codex-task-manifest"

    def __post_init__(self) -> None:
        if (
            type(self.execution_id) is not CodexExecutionId
            or self.schema_kind != "armi.codex-task-manifest"
            or type(self.deadline_seconds) is not int
            or not 60 <= self.deadline_seconds <= 1800
            or type(self.model_id) is not CodexModel
            or type(self.reasoning_effort) is not CodexReasoningEffort
            or type(self.web_search) is not bool
            or self.model_id is not CodexModel.LUNA
            or self.reasoning_effort is not CodexReasoningEffort.MEDIUM
        ):
            raise CodexRunnerViolation("CODEX-TASK-MANIFEST")
        _uuid7(self.task_id, "CODEX-TASK-MANIFEST")
        _uuid7(self.effect_id, "CODEX-TASK-MANIFEST")
        _bounded_text(self.objective, "CODEX-TASK-MANIFEST")


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    execution_id: CodexExecutionId
    status: CodexRunStatus
    model_id: str
    sdk_version: str
    final_response: str
    usage: CodexUsage | None
    error_code: str | None = None
    cleanup_error_code: str | None = None
    schema_kind: str = "armi.codex-run-result"

    def __post_init__(self) -> None:
        if (
            type(self.execution_id) is not CodexExecutionId
            or type(self.status) is not CodexRunStatus
            or self.model_id not in {model.value for model in CodexModel}
            or type(self.sdk_version) is not str
            or not self.sdk_version
            or type(self.final_response) is not str
            or self.schema_kind != "armi.codex-run-result"
        ):
            raise CodexRunnerViolation("CODEX-RUN-RESULT")
        if self.status is CodexRunStatus.SUCCEEDED:
            if not self.final_response.strip() or self.error_code is not None:
                raise CodexRunnerViolation("CODEX-RUN-RESULT")
        elif self.error_code is None or _CODE.fullmatch(self.error_code) is None:
            raise CodexRunnerViolation("CODEX-RUN-RESULT")
        if (
            self.cleanup_error_code is not None
            and _CODE.fullmatch(self.cleanup_error_code) is None
        ):
            raise CodexRunnerViolation("CODEX-RUN-RESULT")


@runtime_checkable
class CodexRunnerPort(Protocol):
    async def run(self, task: CodexTaskManifest) -> CodexRunResult: ...


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CodexRunnerViolation(code)


def _invalid_text(value: object) -> bool:
    if type(value) is not str or not value.strip() or "\x00" in value:
        return True
    try:
        return len(value.encode("utf-8")) > _MAX_TEXT_BYTES
    except UnicodeEncodeError:
        return True


def _bounded_text(value: object, code: str) -> None:
    if _invalid_text(value):
        raise CodexRunnerViolation(code)


__all__ = (
    "CodexExecutionId",
    "CodexModel",
    "CodexReasoningEffort",
    "CodexRunResult",
    "CodexRunStatus",
    "CodexRunnerPort",
    "CodexRunnerViolation",
    "CodexTaskManifest",
    "CodexUsage",
)
