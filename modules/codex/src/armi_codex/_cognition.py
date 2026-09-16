"""Bind a subject-authored task without a Creator input or extra cognition."""

from uuid import uuid7

from armi_kernel.contracts import Digest

from ._delegation_contract import (
    CodexDelegationDraft,
    CodexDelegationViolation,
    CodexNewTaskContent,
    CodexTaskSourceId,
)
from ._runner_contract import CodexModel, CodexReasoningEffort
from ._task_content import task_bundle, task_manifest


def bind_autonomous_codex_task(
    *,
    objective: str,
    model_id: str,
    reasoning_effort: str,
    web_search: bool,
    proposal_ref: str,
    atomic_group_ref: str,
    basis_ordinals: tuple[int, ...],
) -> CodexDelegationDraft:
    if (
        not objective.strip()
        or "\x00" in objective
        or len(objective.encode("utf-8")) > 16 * 1024
    ):
        raise CodexDelegationViolation("CODEX-TASK-REQUEST")
    source_id = CodexTaskSourceId(uuid7())
    bundle, tree = task_bundle(source_id)
    manifest = task_manifest(
        source_id,
        objective,
        tree,
        CodexModel(model_id),
        CodexReasoningEffort(reasoning_effort),
        web_search,
    )
    return CodexDelegationDraft(
        proposal_ref,
        atomic_group_ref,
        basis_ordinals,
        source_id,
        Digest.from_bytes(manifest),
        "codex.output-artifact.v1",
        new_task=CodexNewTaskContent(bundle, manifest, tree),
    )
