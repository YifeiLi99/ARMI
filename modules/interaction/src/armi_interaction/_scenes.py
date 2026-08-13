"""Fenced Creator scene lifecycle service."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
)
from armi_kernel.contracts import Purpose, SubjectId, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._scene_contract import (
    CreatorSceneCollection,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    SceneQueryViolation,
)
from ._scenes_postgresql import CreatorSceneRepository


class CreatorSceneService(CreatorScenePort):
    __slots__ = ("_creator_party_id", "_factory", "_repository")

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        repository: CreatorSceneRepository,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._factory = factory
        self._repository = repository

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list(self) -> CreatorSceneCollection:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._repository.list(
                    unit_of_work,
                    creator_party_id=self._creator_party_id,
                )
        except SceneQueryViolation:
            raise
        except RuntimeTransactionFailure:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE") from None

    async def create(self, command: CreatorSceneCreateCommand) -> CreatorSceneView:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                subject_id = await self._repository.subject_id(
                    unit_of_work,
                    creator_party_id=self._creator_party_id,
                )
                created = await self._repository.create(
                    unit_of_work,
                    scene_id=uuid7(),
                    subject_id=subject_id,
                    creator_party_id=self._creator_party_id,
                    scene_key=command.scene_key,
                )
                await unit_of_work.audit.append(
                    _audit(
                        operation="creator.scene.created",
                        view=created,
                        creator_party_id=self._creator_party_id,
                        subject_id=subject_id,
                        trace_id=command.trace_id,
                    )
                )
                return created
        except SceneQueryViolation:
            raise
        except RuntimeTransactionFailure as error:
            code = (
                "SCENE-KEY-CONFLICT"
                if error.code == "DB-TX-UNIQUE"
                else "SCENE-UPDATE-FAILED"
            )
            raise SceneQueryViolation(code) from None
        except AuditViolation:
            raise SceneQueryViolation("SCENE-UPDATE-FAILED") from None

    async def set_status(
        self,
        command: CreatorSceneStatusCommand,
    ) -> CreatorSceneView:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                subject_id, changed, applied = await self._repository.set_status(
                    unit_of_work,
                    creator_party_id=self._creator_party_id,
                    scene_key=command.scene_key,
                    target_status=command.target_status,
                )
                if applied:
                    await unit_of_work.audit.append(
                        _audit(
                            operation=f"creator.scene.{command.target_status.value}",
                            view=changed,
                            creator_party_id=self._creator_party_id,
                            subject_id=subject_id,
                            trace_id=command.trace_id,
                        )
                    )
                return changed
        except SceneQueryViolation:
            raise
        except RuntimeTransactionFailure, AuditViolation:
            raise SceneQueryViolation("SCENE-UPDATE-FAILED") from None


def _audit(
    *,
    operation: str,
    view: CreatorSceneView,
    creator_party_id: UUID,
    subject_id: UUID,
    trace_id: TraceId,
) -> AuditDraft:
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("creator", creator_party_id),
        purpose=Purpose("creator.scene"),
        operation=operation,
        target=AuditReference("scene", view.scene_id),
        result_status=AuditResultStatus.APPLIED,
        trace_id=trace_id,
        sensitivity=AuditSensitivity.PRIVATE,
        subject_id=SubjectId(subject_id),
    )


__all__ = ("CreatorSceneService",)
