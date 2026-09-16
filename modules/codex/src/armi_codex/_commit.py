"""Validate Codex-owned sources and delegate Expression-owned intent writes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort
from armi_expression.api import DelegatedActionIntentDraft, ExpressionCommitPort
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPort,
    ArtifactPrivacyScope,
    ArtifactPublication,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._delegation_contract import CodexDelegationDraft, CodexDelegationViolation
from .api import CodexCommitContext, CodexPreparedTask, CodexTaskSourceReadPort


async def _content(value: bytes) -> AsyncIterator[bytes]:
    yield value


class PostgreSQLCodexCommit:
    __slots__ = ("_available", "_catalog", "_expression", "_sources")

    def __init__(
        self,
        sources: CodexTaskSourceReadPort,
        expression: ExpressionCommitPort,
        catalog: ArtifactCatalogPort,
        available: Callable[[], bool],
    ) -> None:
        self._sources = sources
        self._catalog = catalog
        self._available = available
        self._expression = expression

    async def prepare_tasks(
        self,
        *,
        delegations: tuple[CodexDelegationDraft, ...],
        storage: ArtifactPort,
        trace_id: TraceId,
    ) -> tuple[CodexPreparedTask, ...]:
        prepared: list[CodexPreparedTask] = []
        for draft in delegations:
            if draft.new_task is None:
                continue
            if not self._available():
                raise CodexDelegationViolation("CODEX-UNAVAILABLE")
            publications: list[ArtifactPublication] = []
            for value, media, kind in (
                (
                    draft.new_task.bundle_bytes,
                    "application/zip",
                    "codex.task-source-bundle",
                ),
                (
                    draft.new_task.manifest_bytes,
                    "application/json",
                    "codex.task-source-manifest",
                ),
            ):
                publications.append(
                    await storage.publish(
                        await storage.stage(
                            _content(value),
                            ArtifactPolicy(
                                media,
                                kind,
                                "subject.codex-task",
                                trace_id,
                                ArtifactPrivacyScope.PRIVATE,
                            ),
                        )
                    )
                )
            prepared.append(
                CodexPreparedTask(
                    draft.task_source_id.value, publications[0], publications[1]
                )
            )
        return tuple(prepared)

    async def commit_delegations(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CodexCommitContext,
        commit_id: UUID,
        delegations: tuple[CodexDelegationDraft, ...],
        prepared_tasks: tuple[CodexPreparedTask, ...] = (),
    ) -> None:
        if type(commit_id) is not UUID or commit_id.version != 7:
            raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-ID")
        if not delegations:
            return
        if not self._available():
            raise CodexDelegationViolation("CODEX-UNAVAILABLE")
        if len(delegations) != 1:
            raise CodexDelegationViolation("CODEX-DELEGATION-COUNT")
        draft = delegations[0]
        if draft.new_task is not None:
            if (
                len(prepared_tasks) != 1
                or prepared_tasks[0].task_source_id != draft.task_source_id.value
            ):
                raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")
            prepared = prepared_tasks[0]
            bundle_registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), prepared.bundle
            )
            manifest_registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), prepared.manifest
            )
            if (
                manifest_registration.ref.content_digest != draft.task_manifest_digest
                or bundle_registration.ref.content_digest
                != Digest.from_bytes(draft.new_task.bundle_bytes)
            ):
                raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")
            await unit_of_work.transaction.execute(
                """INSERT INTO armi.codex_task_sources (
                    codex_task_source_id,subject_id,source_bundle_artifact_id,source_bundle_digest,
                    source_tree_digest,task_manifest_artifact_id,task_manifest_digest,validator_id,
                    deadline_seconds,trace_id,origin_subject_commit_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,900,%s,%s)""",
                (
                    draft.task_source_id.value,
                    context.subject_id,
                    bundle_registration.ref.artifact_id.value,
                    bundle_registration.ref.content_digest.value,
                    draft.new_task.source_tree_digest.value,
                    manifest_registration.ref.artifact_id.value,
                    draft.task_manifest_digest.value,
                    draft.validator_id,
                    context.trace_id.value,
                    commit_id,
                ),
            )
        source = await self._sources.task_source(
            unit_of_work.transaction,
            task_source_id=draft.task_source_id.value,
        )
        if (
            source.subject_id != context.subject_id
            or source.task_manifest_digest != draft.task_manifest_digest
            or source.validator_id != draft.validator_id
        ):
            raise CodexDelegationViolation("CODEX-DELEGATION-VALIDATION")
        if context.scene_id is None or context.creator_party_id is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-CONTEXT")
        manifest = await self._catalog.retained_ref_in(
            unit_of_work.transaction, ArtifactId(source.task_manifest_artifact_id)
        )
        if manifest is None or manifest.content_digest != source.task_manifest_digest:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")
        await self._expression.commit_delegation(
            unit_of_work,
            commit_id=commit_id,
            draft=DelegatedActionIntentDraft(
                operation_ref=uuid7()
                if draft.new_task is not None
                else context.root_opportunity_id,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                creator_party_id=context.creator_party_id,
                root_opportunity_id=context.root_opportunity_id,
                validation_id=context.validation_id,
                proposal_ref=draft.proposal_ref,
                task_source_id=draft.task_source_id.value,
                task_manifest_digest=draft.task_manifest_digest,
                validator_id=draft.validator_id,
                task_manifest_artifact_id=source.task_manifest_artifact_id,
                task_manifest_bytes=manifest.byte_size,
                trace_id=context.trace_id,
            ),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("subject.commit"),
                "codex.delegation.intent.recorded",
                AuditReference("codex_task_source", draft.task_source_id.value),
                AuditResultStatus.ACCEPTED,
                context.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(context.subject_id),
                request=AuditReference("cognitive_episode", context.episode_id),
            )
        )


__all__ = ("PostgreSQLCodexCommit",)
