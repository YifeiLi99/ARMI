from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from armi_artifact_store.api import ArtifactDeletionDiagnostic
from armi_cognition.api import CandidateDiagnostic, CandidateValidationDiagnostic
from armi_context.api import EmbeddingFailureDiagnostic
from armi_live_voice.api import VoiceProviderDiagnostic
from armi_runtime.application.creator_contract import RuntimeState
from armi_runtime.composition.diagnostics import StructuredDiagnosticLog
from armi_runtime.composition.lifecycle import LifecycleController

_ENVIRONMENT = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
_REASON = "RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE"


class _WriteFailure(io.StringIO):
    def write(self, value: str) -> int:
        raise OSError("private path and failure details")


class DiagnosticTests(unittest.TestCase):
    def test_voice_provider_result_reaches_rotating_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostic = StructuredDiagnosticLog(
                data_root=root, environment_id=_ENVIRONMENT, instance_id="instance"
            )
            diagnostic.voice_provider(
                VoiceProviderDiagnostic(
                    "settled",
                    "call",
                    "turn",
                    None,
                    "asr",
                    "provider",
                    "resource",
                    None,
                    "unknown",
                    "VOICE-ASR-CANCELLED",
                )
            )
            diagnostic.close()
            record = json.loads(
                next((root / "logs").glob("*.jsonl")).read_text(encoding="utf-8")
            )
            self.assertEqual(record["event"], "live_voice.provider.settled")
            self.assertEqual(record["details"]["error_code"], "VOICE-ASR-CANCELLED")
            self.assertEqual(record["details"]["turn_id"], "turn")

    def test_candidate_rejection_details_reach_rotating_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostic = StructuredDiagnosticLog(
                data_root=root, environment_id=_ENVIRONMENT, instance_id="instance"
            )
            diagnostic.candidate_validation(
                CandidateValidationDiagnostic(
                    "episode",
                    "attempt",
                    "rejected",
                    "CANDIDATE-CONTRACT",
                    (
                        CandidateDiagnostic(
                            "structure",
                            "string_type",
                            ("decision", "content"),
                            "cognition",
                        ),
                    ),
                )
            )
            diagnostic.close()
            records = [
                json.loads(line)
                for line in next((root / "logs").glob("*.jsonl"))
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(records[0]["details"]["model_attempt_id"], "attempt")
            self.assertEqual(records[1]["event"], "cognition.candidate.diagnostic")
            self.assertEqual(records[1]["details"]["code"], "string_type")
            self.assertEqual(
                json.loads(records[1]["details"]["path"]), ["decision", "content"]
            )

    def test_deletion_attempt_reaches_rotating_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostic = StructuredDiagnosticLog(
                data_root=root, environment_id=_ENVIRONMENT, instance_id="instance"
            )
            diagnostic.artifact_deletion(
                ArtifactDeletionDiagnostic(
                    "deletion", "attempt", 2, "retryable", "ART-IO"
                )
            )
            diagnostic.close()
            record = json.loads(
                next((root / "logs").glob("*.jsonl")).read_text(encoding="utf-8")
            )
            self.assertEqual(record["event"], "artifact.deletion.attempt")
            self.assertEqual(record["details"]["error_code"], "ART-IO")
            self.assertEqual(record["details"]["attempt_no"], 2)

    def test_embedding_failure_details_reach_rotating_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostic = StructuredDiagnosticLog(
                data_root=root, environment_id=_ENVIRONMENT, instance_id="instance"
            )
            diagnostic.embedding_failure(
                EmbeddingFailureDiagnostic(
                    work_id="work",
                    source_kind="subjective_memory",
                    source_ref="memory",
                    source_version=2,
                    error_code="MODEL-UNAVAILABLE",
                    disposition="degraded",
                    retry_at=None,
                )
            )
            diagnostic.close()
            record = json.loads(
                next((root / "logs").glob("*.jsonl")).read_text(encoding="utf-8")
            )
            self.assertEqual(record["event"], "context.embedding.failure")
            self.assertEqual(record["details"]["source_ref"], "memory")
            self.assertEqual(record["details"]["error_code"], "MODEL-UNAVAILABLE")

    def test_recovery_counts_are_written_to_diagnostic_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            diagnostic = StructuredDiagnosticLog(
                data_root=root,
                environment_id=_ENVIRONMENT,
                instance_id="instance",
            )
            counts = {"live_voice.ended_session_count": 2}
            diagnostic.emit(
                "runtime.recovery.safe", result_code="REC_SAFE", metrics=counts
            )
            diagnostic.close()
            records = [
                json.loads(line)
                for path in (root / "logs").rglob("*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["event"], "runtime.recovery.safe")
            self.assertEqual(records[0]["metrics"], counts)

    def test_initial_file_failure_uses_stderr_without_path_or_error(self) -> None:
        fallback = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "open", side_effect=OSError("private detail")):
                diagnostic = StructuredDiagnosticLog(
                    data_root=Path(temporary),
                    environment_id=_ENVIRONMENT,
                    instance_id="instance",
                    fallback=fallback,
                )
            self.assertEqual(diagnostic.status.mode, "stderr")
            self.assertEqual(diagnostic.status.reason_code, _REASON)
            diagnostic.emit("runtime.lifecycle.starting")
            diagnostic.close()
        output = fallback.getvalue()
        self.assertIn("runtime.lifecycle.starting", output)
        self.assertNotIn(temporary, output)
        self.assertNotIn("private detail", output)

    def test_runtime_write_failure_notifies_lifecycle_and_falls_back(self) -> None:
        fallback = io.StringIO()
        lifecycle = LifecycleController(environment_id=_ENVIRONMENT)
        lifecycle.start()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "open", return_value=_WriteFailure()):
                diagnostic = StructuredDiagnosticLog(
                    data_root=Path(temporary),
                    environment_id=_ENVIRONMENT,
                    instance_id="instance",
                    fallback=fallback,
                    on_degraded=lifecycle.add_degradation,
                )
            diagnostic.emit("runtime.lifecycle.starting")
            snapshot = lifecycle.complete_startup(())
            diagnostic.close()
        self.assertEqual(snapshot.runtime_state, RuntimeState.DEGRADED)
        self.assertEqual(snapshot.reason_codes, (_REASON,))
        self.assertEqual(diagnostic.status.mode, "stderr")
        self.assertIn("runtime.lifecycle.starting", fallback.getvalue())

    def test_core_blockers_keep_runtime_blocked_when_log_degrades(self) -> None:
        lifecycle = LifecycleController(environment_id=_ENVIRONMENT)
        lifecycle.start()
        lifecycle.add_degradation(_REASON)
        snapshot = lifecycle.complete_startup(("RUNTIME_RECOVERY_NOT_IMPLEMENTED",))
        self.assertEqual(snapshot.runtime_state, RuntimeState.BLOCKED)
        self.assertIn(_REASON, snapshot.reason_codes)

    def test_size_rotation_and_age_retention_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs"
            logs.mkdir()
            expired = logs / "runtime-expired.jsonl"
            expired.write_text("old\n", encoding="utf-8", newline="\n")
            os.utime(expired, (1, 1))
            diagnostic = StructuredDiagnosticLog(
                data_root=root,
                environment_id=_ENVIRONMENT,
                instance_id="rotation",
                rotation_max_bytes=64,
                retention_seconds=1,
            )
            diagnostic.emit("runtime.lifecycle.starting")
            diagnostic.emit("runtime.lifecycle.ready")
            status = diagnostic.status
            diagnostic.close()

        self.assertEqual(status.mode, "file")
        self.assertGreaterEqual(status.rotations, 1)
        self.assertEqual(status.retention_deleted, 1)
        self.assertFalse(expired.exists())


if __name__ == "__main__":
    unittest.main()
