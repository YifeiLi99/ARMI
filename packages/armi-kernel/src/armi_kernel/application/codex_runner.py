"""Technology-neutral contracts for one isolated Codex execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_CODE = re.compile(r"^CODEX-[A-Z0-9-]+$", re.ASCII)
_VALIDATOR = re.compile(r"^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$", re.ASCII)
_MAX_TEXT_BYTES = 16 * 1024
_MAX_FACTS = 32
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)


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
    source_bundle_digest: Digest
    source_tree_digest: Digest
    objective: str
    facts: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    validator_id: str
    deadline_seconds: int
    output_contract: str = "armi.codex-run-result.v1"
    workspace_limit_bytes: int = 2 * 1024 * 1024 * 1024
    diff_limit_bytes: int = 20 * 1024 * 1024
    modified_file_limit: int = 500
    output_limit_bytes: int = 100 * 1024 * 1024
    model_id: CodexModel = CodexModel.SOL
    reasoning_effort: CodexReasoningEffort = CodexReasoningEffort.MEDIUM
    web_search: bool = False
    schema_version: str = "armi.codex-task-manifest.v1"

    def __post_init__(self) -> None:
        if (
            type(self.execution_id) is not CodexExecutionId
            or type(self.source_bundle_digest) is not Digest
            or type(self.source_tree_digest) is not Digest
            or self.schema_version != "armi.codex-task-manifest.v1"
            or self.output_contract != "armi.codex-run-result.v1"
            or type(self.deadline_seconds) is not int
            or not 60 <= self.deadline_seconds <= 1800
            or self.workspace_limit_bytes != 2 * 1024 * 1024 * 1024
            or self.diff_limit_bytes != 20 * 1024 * 1024
            or self.modified_file_limit != 500
            or self.output_limit_bytes != 100 * 1024 * 1024
            or type(self.model_id) is not CodexModel
            or type(self.reasoning_effort) is not CodexReasoningEffort
            or type(self.web_search) is not bool
            or _VALIDATOR.fullmatch(self.validator_id) is None
        ):
            raise CodexRunnerViolation("CODEX-TASK-MANIFEST")
        _uuid7(self.task_id, "CODEX-TASK-MANIFEST")
        _uuid7(self.effect_id, "CODEX-TASK-MANIFEST")
        _bounded_text(self.objective, "CODEX-TASK-MANIFEST")
        if (
            type(self.facts) is not tuple
            or not 1 <= len(self.facts) <= _MAX_FACTS
            or any(_invalid_text(value) for value in self.facts)
            or type(self.allowed_paths) is not tuple
            or len(set(value.casefold() for value in self.allowed_paths))
            != len(self.allowed_paths)
            or type(self.forbidden_paths) is not tuple
            or len(set(value.casefold() for value in self.forbidden_paths))
            != len(self.forbidden_paths)
        ):
            raise CodexRunnerViolation("CODEX-TASK-MANIFEST")
        for value in (*self.allowed_paths, *self.forbidden_paths):
            _relative_path(value)


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    execution_id: CodexExecutionId
    status: CodexRunStatus
    model_id: str
    sdk_version: str
    source_tree_digest: Digest
    final_tree_digest: Digest | None
    patch_digest: Digest | None
    usage: CodexUsage | None
    modified_file_count: int
    validation_passed: bool
    error_code: str | None = None
    schema_version: str = "armi.codex-run-result.v1"

    def __post_init__(self) -> None:
        if (
            type(self.execution_id) is not CodexExecutionId
            or type(self.status) is not CodexRunStatus
            or self.model_id not in {model.value for model in CodexModel}
            or type(self.sdk_version) is not str
            or not self.sdk_version
            or len(self.sdk_version) > 64
            or type(self.source_tree_digest) is not Digest
            or type(self.modified_file_count) is not int
            or not 0 <= self.modified_file_count <= 500
            or type(self.validation_passed) is not bool
            or self.schema_version != "armi.codex-run-result.v1"
        ):
            raise CodexRunnerViolation("CODEX-RUN-RESULT")
        success = self.status is CodexRunStatus.SUCCEEDED
        if success != (
            type(self.final_tree_digest) is Digest
            and type(self.patch_digest) is Digest
            and type(self.usage) is CodexUsage
            and self.validation_passed
            and self.error_code is None
        ):
            raise CodexRunnerViolation("CODEX-RUN-RESULT")
        if not success and (
            self.error_code is None or _CODE.fullmatch(self.error_code) is None
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


def _relative_path(value: object) -> None:
    if (
        type(value) is not str
        or not value
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or character in '<>"|?*' for character in value)
    ):
        raise CodexRunnerViolation("CODEX-TASK-PATH")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CodexRunnerViolation("CODEX-TASK-PATH")
    for part in path.parts:
        stem = part.rstrip(" .").split(".", 1)[0].casefold()
        if (
            part.rstrip(" .") != part
            or stem in _WINDOWS_RESERVED
            or part.casefold() == ".codex"
        ):
            raise CodexRunnerViolation("CODEX-TASK-PATH")


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
