"""Interaction-owned, once-per-input technical failure notices."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import LifeViolation, OpportunityContextReadPort
from armi_evidence.api import (
    EvidenceId,
    EvidenceReadPort,
    EvidenceSnapshot,
    EvidenceViolation,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RuntimeFence,
)
from armi_kernel.contracts import ContractViolation, Purpose, SubjectId, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)

from .api import (
    InteractionArtifactCatalogPort,
    InteractionEffectRoute,
    InteractionEffectRoutePort,
    OtherHumanInputViolation,
    SystemNotificationEffectDraft,
    SystemNotificationEffectPort,
)


class NotificationSourceViolation(RuntimeError):
    """The authoritative origin cannot be used for delivery."""


def failure_notification_text(*, send_unknown: bool) -> str:
    if send_unknown:
        return "ARMI 系统提示：本轮消息的发送结果暂时无法确认；消息可能已送达，系统不会重复发送。"
    return "ARMI 系统提示：本轮处理遇到技术错误，未能正常完成。"


@dataclass(frozen=True, slots=True)
class _Source:
    interaction_id: UUID
    operation_id: UUID | None
    subject_id: UUID
    scene_id: UUID
    party_id: UUID
    binding_id: UUID | None
    purpose: str
    modality: str
    trace_id: TraceId
    runtime_fence: RuntimeFence


async def _chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class InteractionFailureNotifications:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        opportunities: OpportunityContextReadPort,
        evidence: EvidenceReadPort,
        routes: InteractionEffectRoutePort,
        catalog: InteractionArtifactCatalogPort,
        storage: ContentAddressedArtifactStore,
        effects: SystemNotificationEffectPort,
        diagnostic: Callable[[str], None],
        voice_failure: Callable[[UUID], Awaitable[None]] | None = None,
        derived_origin: Callable[
            [PostgreSQLTransaction, EvidenceSnapshot], Awaitable[UUID | None]
        ]
        | None = None,
    ) -> None:
        self._factory = factory
        self._opportunities = opportunities
        self._evidence = evidence
        self._routes = routes
        self._catalog = catalog
        self._storage = storage
        self._effects = effects
        self._diagnostic = diagnostic
        self._voice_failure = voice_failure
        self._derived_origin = derived_origin

    async def notify_failure(
        self, *, opportunity_id: UUID, failure_code: str, send_unknown: bool = False
    ) -> None:
        await self._notify_checked(opportunity_id, None, failure_code, send_unknown)

    async def notify_input_failure(
        self, *, interaction_id: UUID, failure_code: str
    ) -> None:
        await self._notify_checked(None, interaction_id, failure_code, False)

    async def _notify_checked(
        self,
        opportunity_id: UUID | None,
        interaction_id: UUID | None,
        failure_code: str,
        send_unknown: bool,
    ) -> None:
        # This entry is called only for settled technical failures. Notice failure
        # is reported to management and never submitted to this entry recursively.
        if re.fullmatch(r"[A-Z][A-Z0-9_-]{0,127}", failure_code) is None:
            raise ValueError("invalid failure code")
        try:
            await self._notify(
                opportunity_id, interaction_id, failure_code, send_unknown
            )
        except (
            ContractViolation,
            ArtifactViolation,
            RuntimeTransactionFailure,
            OSError,
            NotificationSourceViolation,
            LifeViolation,
            EvidenceViolation,
        ):
            self._diagnostic("interaction.system_notification.failed")

    async def _source(
        self, uow: PostgreSQLRuntimeUnitOfWork, opportunity_id: UUID
    ) -> _Source | None:
        opportunity = await self._opportunities.context_snapshot(
            uow.transaction,
            opportunity_id=opportunity_id,
        )
        root = opportunity
        visited: set[UUID] = set()
        while True:
            if root.opportunity_id in visited:
                raise NotificationSourceViolation(
                    "INTERACTION-NOTIFICATION-ORIGIN-CYCLE"
                )
            visited.add(root.opportunity_id)
            if (root.subject_id, root.scene_id, root.context_party_id) != (
                opportunity.subject_id,
                opportunity.scene_id,
                opportunity.context_party_id,
            ):
                raise NotificationSourceViolation("INTERACTION-NOTIFICATION-SOURCE")
            if root.root_opportunity_id != root.opportunity_id:
                root = await self._opportunities.context_snapshot(
                    uow.transaction, opportunity_id=root.root_opportunity_id
                )
                continue
            if root.evidence_id is None:
                return None
            evidence = await self._evidence.snapshot(
                uow.transaction, evidence_id=EvidenceId(root.evidence_id)
            )
            if evidence.interaction_id is not None:
                break
            if self._derived_origin is None:
                return None
            origin = await self._derived_origin(uow.transaction, evidence)
            if origin is None:
                return None
            root = await self._opportunities.context_snapshot(
                uow.transaction, opportunity_id=origin
            )
        source = await self._input_source(
            uow, evidence.interaction_id, root.opportunity_id
        )
        if source is not None and (
            source.subject_id,
            source.scene_id,
            source.party_id,
        ) != (root.subject_id, root.scene_id, root.context_party_id):
            raise NotificationSourceViolation("INTERACTION-NOTIFICATION-SOURCE")
        return source

    async def _input_source(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        interaction_id: UUID,
        operation_id: UUID | None,
    ) -> _Source | None:
        row = await (
            await uow.transaction.execute(
                """SELECT subject_id,scene_id,source_party_id,external_binding_id,
                      purpose,modality,trace_id
               FROM armi.party_input_interactions
               WHERE interaction_id=%s AND data_rights_hidden_at IS NULL""",
                (interaction_id,),
            )
        ).fetchone()
        if row is None or uow.runtime_fence is None:
            return None
        return _Source(
            interaction_id,
            operation_id,
            row[0],
            row[1],
            row[2],
            row[3],
            str(row[4]),
            str(row[5]),
            TraceId(str(row[6])),
            uow.runtime_fence,
        )

    async def _route(
        self, uow: PostgreSQLRuntimeUnitOfWork, source: _Source
    ) -> InteractionEffectRoute | None:
        # Voice needs the current session's state/output owner, never a text
        # channel fallback. A management receipt still records the failure.
        if source.modality == "live_voice":
            return None
        intended = (
            None
            if source.binding_id is not None
            else (
                "creator_inbox"
                if source.purpose != "other_human_message"
                else "other_human_inbox"
            )
        )
        try:
            route = await self._routes.effect_route(
                uow.transaction,
                scene_id=source.scene_id,
                context_party_id=source.party_id,
                intended_destination_kind=intended,
            )
        except OtherHumanInputViolation:
            return None
        if route.destination_binding_id != source.binding_id:
            return None
        return route

    async def _locate(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        opportunity_id: UUID | None,
        interaction_id: UUID | None,
    ) -> _Source | None:
        if opportunity_id is not None:
            return await self._source(uow, opportunity_id)
        assert interaction_id is not None
        return await self._input_source(uow, interaction_id, None)

    async def _notify(
        self,
        opportunity_id: UUID | None,
        interaction_id: UUID | None,
        code: str,
        unknown: bool,
    ) -> None:
        async with self._factory.unit_of_work() as uow:
            source = await self._locate(uow, opportunity_id, interaction_id)
            if source is None:
                return
            existing = await (
                await uow.transaction.execute(
                    "SELECT notification_id FROM armi.system_notifications WHERE interaction_id=%s",
                    (source.interaction_id,),
                )
            ).fetchone()
            if existing is not None:
                return
        payload = failure_notification_text(send_unknown=unknown).encode("utf-8")
        publication = await self._storage.publish(
            await self._storage.stage(
                _chunk(payload),
                ArtifactPolicy(
                    "text/plain",
                    "interaction.system_notification",
                    "interaction.system",
                    source.trace_id,
                    ArtifactPrivacyScope.CREATOR_VISIBLE,
                ),
            )
        )
        async with self._factory.unit_of_work() as uow:
            # No notice can move from the failed round into a different Runtime,
            # receiver, or data-rights state during artifact preparation.
            current = await self._locate(uow, opportunity_id, interaction_id)
            if current != source:
                return
            route = await self._route(uow, source)
            registration = await self._catalog.register(
                uow, ArtifactId(uuid7()), publication
            )
            notification_id = uuid7()
            inserted = await (
                await uow.transaction.execute(
                    """INSERT INTO armi.system_notifications (
                    notification_id,interaction_id,operation_id,subject_id,scene_id,
                    destination_party_id,category,failure_code,send_unknown,payload_artifact_id,
                    delivery_status,trace_id)
                   VALUES (%s,%s,%s,%s,%s,%s,'technical_failure',%s,%s,%s,%s,%s)
                   ON CONFLICT (interaction_id) DO NOTHING RETURNING notification_id""",
                    (
                        notification_id,
                        source.interaction_id,
                        source.operation_id,
                        source.subject_id,
                        source.scene_id,
                        source.party_id,
                        code,
                        unknown,
                        registration.ref.artifact_id.value,
                        "unavailable" if route is None else "registered",
                        source.trace_id.value,
                    ),
                )
            ).fetchone()
            if inserted is None:
                return
            if registration.inserted:
                await uow.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", uow.environment_id),
                        Purpose("interaction.system_notification"),
                        "artifact.catalog.registered",
                        AuditReference("artifact", registration.ref.artifact_id.value),
                        AuditResultStatus.APPLIED,
                        source.trace_id,
                        AuditSensitivity.RESTRICTED,
                        subject_id=SubjectId(source.subject_id),
                        request=AuditReference("system_notification", notification_id),
                    )
                )
            if route is not None:
                await self._effects.register_system_notification(
                    uow.transaction,
                    SystemNotificationEffectDraft(
                        notification_id,
                        source.subject_id,
                        route,
                        registration.ref,
                        source.trace_id,
                    ),
                )
        if (
            source.modality == "live_voice"
            and self._voice_failure is not None
            and source.operation_id is not None
        ):
            await self._voice_failure(source.operation_id)
