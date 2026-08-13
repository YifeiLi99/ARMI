"""Prompt-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)

from .api import PromptReadPort, PromptViolation


class PromptRecoveryParticipant:
    __slots__ = ("_read",)
    owner_identity = RecoveryOwnerIdentity("prompt")
    work_scopes: tuple[tuple[str, str], ...] = ()

    def __init__(self, read: PromptReadPort) -> None:
        self._read = read

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del work
        try:
            state = await self._read.recovery_state(
                transaction, subject_id=scope.subject_id
            )
        except PromptViolation:
            return RecoveryContribution(
                self.owner_identity,
                findings=(
                    RecoveryFindingContribution(
                        "prompt", RecoveryFindingDecision.BLOCKED, "REC-PROMPT-INVALID"
                    ),
                ),
            )
        valid = state.document_count == 3 and state.fixed_revision_count == 1
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if valid
            else (
                RecoveryFindingContribution(
                    "prompt", RecoveryFindingDecision.BLOCKED, "REC-PROMPT-INVALID"
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "prompt.current_document_count", state.document_count
                ),
            ),
            critical_artifact_ids=(state.fixed_artifact_id,) if valid else (),
        )
