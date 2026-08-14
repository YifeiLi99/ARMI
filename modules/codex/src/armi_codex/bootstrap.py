"""Composition entry points for the active Codex delegation module."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_attention.api import OpportunityAdmissionPort
from armi_data_rights.api import DataRightsParticipant
from armi_effect.api import EffectCodexLifecyclePort
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_expression.api import ExpressionCommitPort, ExpressionIntentReadPort
from armi_interaction.api import CreatorInputTransactionPort, InteractionIdentityPort
from armi_kernel.application import (
    CreatorProjectionNotifier,
    CredentialLocator,
    CredentialPort,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLCodexAdmin
from ._application import CodexEffectPipeline, CodexTaskSourceGateway
from ._codec import decode_result, decode_task, encode_result, encode_task
from ._commit import PostgreSQLCodexCommit
from ._custody_codec import encode_custodied_result
from ._data_rights import PostgreSQLCodexDataRightsParticipant
from ._read_postgresql import PostgreSQLCodexReadOwner
from ._recovery import CodexRecoveryParticipant
from ._runner import (
    IsolatedCodexRunner,
    owner_only,
    runner_config,
    sanitize_platform_home,
    validate_platform_home,
    write_platform_state,
)
from ._timeline_projection import CodexTaskTimelineProjection
from ._windows_job import WindowsJob
from ._workspace import snapshot_tree
from .api import (
    CodexAdminPort,
    CodexArtifactReadPort,
    CodexArtifactStorePort,
    CodexCommitPort,
    CodexContextReadPort,
    CodexExecutionReadPort,
    CodexRuntimePort,
    CodexTaskSourceReadPort,
)


def bootstrap_codex_admin() -> CodexAdminPort:
    return PostgreSQLCodexAdmin()


compose_codex_task_source_gateway = CodexTaskSourceGateway


Diagnostic = Callable[[str], None]


def bootstrap_codex_commit(
    sources: CodexTaskSourceReadPort,
    expression: ExpressionCommitPort,
) -> CodexCommitPort:
    return PostgreSQLCodexCommit(sources, expression)


@dataclass(frozen=True, slots=True)
class CodexReadPorts:
    task_sources: CodexTaskSourceReadPort
    executions: CodexExecutionReadPort
    artifacts: CodexArtifactReadPort
    context: CodexContextReadPort


def bootstrap_codex_read_ports() -> CodexReadPorts:
    owner = PostgreSQLCodexReadOwner()
    return CodexReadPorts(owner, owner, owner, owner)


def bootstrap_codex_timeline_projection() -> CodexTaskTimelineProjection:
    return CodexTaskTimelineProjection()


def bootstrap_codex(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: CodexArtifactStorePort,
    catalog: ArtifactCatalogPort,
    environment_root: Path,
    run_root: Path,
    creator_party_id: UUID,
    creator_input: CreatorInputTransactionPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    identity: InteractionIdentityPort,
    opportunity: OpportunityAdmissionPort,
    effect: EffectCodexLifecyclePort,
    expression: ExpressionIntentReadPort,
    sources: CodexTaskSourceReadPort,
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
        evidence_read=evidence_read,
        identity=identity,
        opportunity=opportunity,
        effect=effect,
        expression=expression,
        sources=sources,
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
decode_runner_result = decode_result
encode_runner_task = encode_task
RunnerWindowsJob = WindowsJob
snapshot_runner_workspace = snapshot_tree


def bootstrap_codex_data_rights() -> DataRightsParticipant:
    return PostgreSQLCodexDataRightsParticipant()


def bootstrap_codex_recovery() -> RecoveryParticipant:
    return CodexRecoveryParticipant()


__all__ = (
    "CodexReadPorts",
    "RunnerWindowsJob",
    "bootstrap_codex",
    "bootstrap_codex_admin",
    "bootstrap_codex_commit",
    "bootstrap_codex_data_rights",
    "bootstrap_codex_read_ports",
    "bootstrap_codex_recovery",
    "bootstrap_codex_runner",
    "bootstrap_codex_timeline_projection",
    "compose_codex_task_source_gateway",
    "decode_runner_result",
    "decode_runner_task",
    "encode_custodied_runner_result",
    "encode_runner_result",
    "encode_runner_task",
    "owner_only",
    "runner_config",
    "sanitize_platform_home",
    "snapshot_runner_workspace",
    "validate_platform_home",
    "write_platform_state",
)
