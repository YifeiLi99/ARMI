"""Composition entry points for the active Codex delegation module."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from armi_effect.api import EffectDispatchBoundaryPort
from armi_evidence.api import EvidenceWritePort
from armi_interaction.api import CreatorInputTransactionPort
from armi_kernel.application import (
    CreatorProjectionNotifier,
    CredentialLocator,
    CredentialPort,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import CodexEffectPipeline
from ._codec import decode_task, encode_result
from ._commit import PostgreSQLCodexCommit
from ._custody_codec import encode_custodied_result
from ._runner import IsolatedCodexRunner
from .api import (
    CodexArtifactCatalogPort,
    CodexArtifactStorePort,
    CodexCommitPort,
    CodexRuntimePort,
)

Diagnostic = Callable[[str], None]


def bootstrap_codex_commit() -> CodexCommitPort:
    return PostgreSQLCodexCommit()


def bootstrap_codex(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: CodexArtifactStorePort,
    catalog: CodexArtifactCatalogPort,
    environment_root: Path,
    run_root: Path,
    creator_party_id: UUID,
    creator_input: CreatorInputTransactionPort,
    evidence: EvidenceWritePort,
    dispatch_boundary: EffectDispatchBoundaryPort,
    runner_entry_module: str,
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Diagnostic | None = None,
) -> CodexRuntimePort:
    if not runner_entry_module or "\x00" in runner_entry_module:
        raise ValueError("runner_entry_module must be a Python module name")
    return CodexEffectPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        environment_root=environment_root,
        run_root=run_root,
        creator_party_id=creator_party_id,
        creator_input=creator_input,
        evidence=evidence,
        dispatch_boundary=dispatch_boundary,
        runner_entry_module=runner_entry_module,
        notifier=notifier,
        diagnostic=diagnostic,
    )


def bootstrap_codex_runner(
    *,
    run_root: Path,
    credential_port: CredentialPort,
    auth_locator: CredentialLocator,
) -> IsolatedCodexRunner:
    return IsolatedCodexRunner(
        run_root=run_root,
        credential_port=credential_port,
        auth_locator=auth_locator,
    )


decode_runner_task = decode_task
encode_runner_result = encode_result
encode_custodied_runner_result = encode_custodied_result

__all__ = (
    "bootstrap_codex",
    "bootstrap_codex_commit",
    "bootstrap_codex_runner",
    "decode_runner_task",
    "encode_custodied_runner_result",
    "encode_runner_result",
)
