"""Runtime owner diagnostics use the shared process log."""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from typing import Any

from armi_artifact_store.api import ArtifactDeletionDiagnostic
from armi_cognition.api import CandidateValidationDiagnostic
from armi_context.api import EmbeddingAttemptDiagnostic, EmbeddingFailureDiagnostic
from armi_live_voice.api import VoiceProviderDiagnostic
from armi_runtime_foundation import DiagnosticLog, DiagnosticSinkStatus


class StructuredDiagnosticLog(DiagnosticLog):
    def emit(
        self,
        record: str | logging.LogRecord,
        *,
        level: int | None = None,
        result_code: str | None = None,
        duration_ms: int | None = None,
        reason_codes: tuple[str, ...] = (),
        metrics: dict[str, int] | None = None,
        details: dict[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        if isinstance(record, logging.LogRecord):
            super().emit(record)
            return
        original = error or sys.exception()
        # Stable names are query keys; technical codes belong in their own field.
        for prefix in (
            "model.worker.transient_failure",
            "model.tokenization.retry",
            "model.preparation.failed",
            "codex.task.database_failed",
            "subject_commit.worker.transient_failure",
        ):
            if record.startswith(prefix + "."):
                result_code = result_code or record[len(prefix) + 1 :].upper()
                record = prefix
                break
        if level is None:
            if any(
                word in record
                for word in (
                    "transient_failure",
                    "retry",
                    "deferred",
                    "stale",
                    "slow_consumer",
                    ".gap",
                    "unavailable",
                )
            ):
                level = logging.WARNING
            elif original is not None or any(
                word in record
                for word in (
                    ".failed",
                    ".failure",
                    "outcome_unknown",
                    "format_rejected",
                    "parser_failure",
                )
            ):
                level = logging.ERROR
            else:
                level = logging.INFO
        self.write(
            record,
            level=level,
            error=original,
            result_code=result_code,
            duration_ms=duration_ms,
            reason_codes=reason_codes,
            metrics=metrics,
            details=details or {},
        )

    def artifact_deletion(self, attempt: ArtifactDeletionDiagnostic) -> None:
        self.emit(
            "artifact.deletion.attempt",
            details=asdict(attempt),
            level=logging.INFO
            if attempt.result_status == "completed"
            else logging.WARNING,
        )

    def candidate_validation(self, result: CandidateValidationDiagnostic) -> None:
        self.emit(
            "cognition.candidate.validated",
            details={
                "episode_id": result.episode_id,
                "model_attempt_id": result.model_attempt_id,
                "status": result.status,
                "error_code": result.error_code,
            },
            level=logging.INFO if result.status == "accepted" else logging.ERROR,
        )
        for item in result.diagnostics:
            self.emit(
                "cognition.candidate.diagnostic",
                level=logging.ERROR,
                details={
                    "episode_id": result.episode_id,
                    "stage": item.stage,
                    "code": item.code,
                    "path": list(item.field_path),
                    "owner": item.owner,
                },
            )

    def voice_provider(self, event: VoiceProviderDiagnostic) -> None:
        self.emit("live_voice.provider." + event.event, details=asdict(event))

    def embedding_attempt(self, attempt: EmbeddingAttemptDiagnostic) -> None:
        self.emit("context.embedding.attempt", details=asdict(attempt))

    def embedding_failure(self, failure: EmbeddingFailureDiagnostic) -> None:
        self.emit(
            "context.embedding.failure", level=logging.WARNING, details=asdict(failure)
        )


__all__ = ("DiagnosticSinkStatus", "StructuredDiagnosticLog")
