from __future__ import annotations

from uuid import uuid7

import pytest
import rfc8785
from armi_codex.api import (
    CodexDelegationViolation,
    CreatorCodexTaskCommand,
)
from armi_codex.bootstrap import bootstrap_codex_timeline_projection
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId


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


def test_creator_timeline_projection_reads_only_the_verified_objective() -> None:
    manifest = rfc8785.dumps(
        {
            "schema_version": "armi.codex-task-source.v2",
            "objective": "  保留原始目标\n并生成交付物。  ",
            "facts": ["one fact"],
            "allowed_paths": [],
            "forbidden_paths": [".armi-task-id"],
            "validator_id": "codex.output-artifact.v1",
            "deadline_seconds": 900,
            "source_tree_digest": Digest.from_bytes(b"tree").value,
            "model_id": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "web_search": False,
        }
    )
    artifact = ArtifactRef(
        ArtifactId(uuid7()),
        Digest.from_bytes(manifest),
        len(manifest),
        "application/json",
        "codex.task-source-manifest",
        ArtifactPrivacyScope.PRIVATE,
        ArtifactIntegrityStatus.VERIFIED,
    )

    assert (
        bootstrap_codex_timeline_projection().objective(
            artifact=artifact,
            content=manifest,
        )
        == "  保留原始目标\n并生成交付物。  "
    )

    with pytest.raises(ValueError, match="artifact is invalid"):
        bootstrap_codex_timeline_projection().objective(
            artifact=ArtifactRef(
                artifact.artifact_id,
                artifact.content_digest,
                artifact.byte_size,
                artifact.media_type,
                "codex.final-result",
                artifact.privacy_scope,
                artifact.integrity_status,
            ),
            content=manifest,
        )
