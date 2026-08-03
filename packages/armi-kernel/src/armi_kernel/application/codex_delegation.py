"""Technology-neutral contracts for Codex delegation custody and acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId

from .artifacts import ArtifactId
from .creator_input import CreatorInputAcceptance
from .effects import EffectId

_CODE = re.compile(
    r"^(?:CON-)?CODEX-(?:TASK|DELEGATION|VERIFICATION|RESULT)-[A-Z0-9-]+$"
)
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$")
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$")
_SCENE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_VALIDATOR = re.compile(r"^codex\.[a-z0-9.-]{1,96}\.v[1-9][0-9]*$")


class CodexVerificationStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class CodexCleanupStatus(StrEnum):
    CLEAN = "clean"
    FAILED = "failed"


class CodexResultEvidenceKind(StrEnum):
    VERIFIED_COMPLETION = "verified_completion"
    EXECUTION_FAILURE = "execution_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class CodexDelegationViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("Codex delegation violation code is invalid")
        self.code = code
        super().__init__("Codex delegation operation failed")

    def __str__(self) -> str:
        return f"{self.code}: Codex delegation operation failed"


@dataclass(frozen=True, slots=True)
class CodexTaskSourceId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CODEX-TASK-SOURCE-ID")


@dataclass(frozen=True, slots=True)
class CodexVerificationId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CODEX-VERIFICATION-ID")


@dataclass(frozen=True, slots=True)
class CodexResultSourceId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CODEX-RESULT-SOURCE-ID")


@dataclass(frozen=True, slots=True)
class CodexTaskSourceDraft:
    task_source_id: CodexTaskSourceId
    subject_id: SubjectId
    source_bundle_artifact_id: ArtifactId
    source_bundle_digest: Digest
    source_tree_digest: Digest
    manifest_artifact_id: ArtifactId
    manifest_digest: Digest
    validator_id: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    deadline_seconds: int
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.task_source_id) is not CodexTaskSourceId
            or type(self.subject_id) is not SubjectId
            or type(self.source_bundle_artifact_id) is not ArtifactId
            or type(self.source_bundle_digest) is not Digest
            or type(self.source_tree_digest) is not Digest
            or type(self.manifest_artifact_id) is not ArtifactId
            or type(self.manifest_digest) is not Digest
            or type(self.trace_id) is not TraceId
            or type(self.validator_id) is not str
            or _VALIDATOR.fullmatch(self.validator_id) is None
            or type(self.deadline_seconds) is not int
            or not 60 <= self.deadline_seconds <= 1800
        ):
            raise CodexDelegationViolation("CODEX-TASK-SOURCE")
        _paths(self.allowed_paths, required=True)
        _paths(self.forbidden_paths, required=False)


@dataclass(frozen=True, slots=True)
class CreatorCodexTaskCommand:
    scene_key: str
    objective: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.scene_key) is not str
            or _SCENE.fullmatch(self.scene_key) is None
            or type(self.objective) is not str
            or "\x00" in self.objective
            or not self.objective.strip()
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
        ):
            raise CodexDelegationViolation("CODEX-TASK-REQUEST")
        try:
            encoded = self.objective.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise CodexDelegationViolation("CODEX-TASK-REQUEST") from None
        if len(encoded) > 16 * 1024:
            raise CodexDelegationViolation("CODEX-TASK-REQUEST-SIZE")


@runtime_checkable
class CreatorCodexTaskAdmissionPort(Protocol):
    async def accept(self, command: CreatorCodexTaskCommand) -> CreatorInputAcceptance:
        """Accept one Creator-authored task into the isolated Codex cognition path."""
        ...


@dataclass(frozen=True, slots=True)
class CodexDelegationDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    task_source_id: CodexTaskSourceId
    task_manifest_digest: Digest
    validator_id: str
    purpose: str = "delegate_codex_work"
    capability_kind: str = "codex.delegated-work"
    operation: str = "execute"

    def __post_init__(self) -> None:
        if (
            type(self.proposal_ref) is not str
            or _REF.fullmatch(self.proposal_ref) is None
            or type(self.atomic_group_ref) is not str
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.basis_ordinals) is not tuple
            or not 1 <= len(self.basis_ordinals) <= 8
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or any(
                type(value) is not int or not 1 <= value <= 999
                for value in self.basis_ordinals
            )
            or type(self.task_source_id) is not CodexTaskSourceId
            or type(self.task_manifest_digest) is not Digest
            or type(self.validator_id) is not str
            or _VALIDATOR.fullmatch(self.validator_id) is None
            or self.purpose != "delegate_codex_work"
            or self.capability_kind != "codex.delegated-work"
            or self.operation != "execute"
        ):
            raise CodexDelegationViolation("CODEX-DELEGATION-DRAFT")


@dataclass(frozen=True, slots=True)
class CodexVerificationResult:
    verification_id: CodexVerificationId
    effect_id: EffectId
    status: CodexVerificationStatus
    cleanup_status: CodexCleanupStatus
    source_tree_digest: Digest
    final_tree_digest: Digest | None
    patch_digest: Digest | None
    transcript_artifact_id: ArtifactId | None
    final_result_artifact_id: ArtifactId | None
    patch_artifact_id: ArtifactId | None
    result_bundle_artifact_id: ArtifactId | None
    diagnostics_artifact_id: ArtifactId | None
    validation_report_artifact_id: ArtifactId | None
    validation_digest: Digest
    changed_paths: tuple[str, ...]
    completed_at: Instant
    execution_error_code: str | None = None
    cleanup_error_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.verification_id) is not CodexVerificationId
            or type(self.effect_id) is not EffectId
            or type(self.status) is not CodexVerificationStatus
            or type(self.cleanup_status) is not CodexCleanupStatus
            or type(self.source_tree_digest) is not Digest
            or type(self.validation_digest) is not Digest
            or type(self.completed_at) is not Instant
        ):
            raise CodexDelegationViolation("CODEX-VERIFICATION-RESULT")
        _paths(self.changed_paths, required=False)
        succeeded = self.status is CodexVerificationStatus.VERIFIED
        if succeeded != (
            self.cleanup_status is CodexCleanupStatus.CLEAN
            and self.final_tree_digest is not None
            and self.patch_digest is not None
            and self.final_result_artifact_id is not None
            and self.patch_artifact_id is not None
            and self.result_bundle_artifact_id is not None
            and self.validation_report_artifact_id is not None
            and self.execution_error_code is None
            and self.cleanup_error_code is None
        ):
            raise CodexDelegationViolation("CODEX-VERIFICATION-RESULT")


@dataclass(frozen=True, slots=True)
class CodexResultEvidence:
    result_source_id: CodexResultSourceId
    verification_id: CodexVerificationId
    effect_id: EffectId
    evidence_id: UUID
    opportunity_id: UUID
    kind: CodexResultEvidenceKind
    evidence_artifact_id: ArtifactId
    evidence_digest: Digest

    def __post_init__(self) -> None:
        if (
            type(self.result_source_id) is not CodexResultSourceId
            or type(self.verification_id) is not CodexVerificationId
            or type(self.effect_id) is not EffectId
            or type(self.kind) is not CodexResultEvidenceKind
            or type(self.evidence_artifact_id) is not ArtifactId
            or type(self.evidence_digest) is not Digest
        ):
            raise CodexDelegationViolation("CODEX-RESULT-EVIDENCE")
        _uuid7(self.evidence_id, "CODEX-RESULT-EVIDENCE")
        _uuid7(self.opportunity_id, "CODEX-RESULT-EVIDENCE")


@runtime_checkable
class CodexTaskSourceAdmissionPort(Protocol):
    async def admit(self, draft: CodexTaskSourceDraft) -> CodexTaskSourceId: ...


@runtime_checkable
class CodexDelegationPort(Protocol):
    async def dispatch_once(self) -> bool: ...


def _paths(values: object, *, required: bool) -> None:
    if type(values) is not tuple:
        raise CodexDelegationViolation("CODEX-TASK-PATHS")
    path_values = cast(tuple[object, ...], values)
    if (required and not path_values) or len(path_values) > 500:
        raise CodexDelegationViolation("CODEX-TASK-PATHS")
    folded: set[str] = set()
    for value in path_values:
        if (
            type(value) is not str
            or not value
            or value.startswith(("/", "\\"))
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or value.casefold() in folded
        ):
            raise CodexDelegationViolation("CODEX-TASK-PATHS")
        folded.add(value.casefold())


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CodexDelegationViolation(code)


__all__ = (
    "CodexCleanupStatus",
    "CodexDelegationDraft",
    "CodexDelegationPort",
    "CodexDelegationViolation",
    "CodexResultEvidence",
    "CodexResultEvidenceKind",
    "CodexResultSourceId",
    "CodexTaskSourceAdmissionPort",
    "CodexTaskSourceDraft",
    "CodexTaskSourceId",
    "CodexVerificationId",
    "CodexVerificationResult",
    "CodexVerificationStatus",
    "CreatorCodexTaskAdmissionPort",
    "CreatorCodexTaskCommand",
)
