"""Interaction-owned silent failure diagnostics and voice turn cleanup."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from armi_attention.api import LifeViolation, OpportunityContextReadPort
from armi_evidence.api import (
    EvidenceId,
    EvidenceReadPort,
    EvidenceSnapshot,
    EvidenceViolation,
)
from armi_kernel.application import RuntimeFence
from armi_kernel.contracts import ContractViolation, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)


class NotificationSourceViolation(RuntimeError):
    """The authoritative origin cannot be used for delivery."""


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


class InteractionFailureNotifications:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        opportunities: OpportunityContextReadPort,
        evidence: EvidenceReadPort,
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
        # All technical failures stay silent in chat, including exhausted retries
        # and unknown delivery. See DESIGN.md: failure handling. Never enqueue a
        # notification here; failure facts remain owned by their original owners.
        if re.fullmatch(r"[A-Z][A-Z0-9_-]{0,127}", failure_code) is None:
            raise ValueError("invalid failure code")
        self._diagnostic(
            f"interaction.processing.failed code={failure_code}"
            f" opportunity_id={opportunity_id} interaction_id={interaction_id}"
            f" send_unknown={send_unknown}"
        )
        if self._voice_failure is None:
            return
        try:
            await self._finish_voice(opportunity_id, interaction_id)
        except (
            ContractViolation,
            RuntimeTransactionFailure,
            OSError,
            NotificationSourceViolation,
            LifeViolation,
            EvidenceViolation,
        ):
            self._diagnostic("interaction.failure_cleanup.failed")

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

    async def _finish_voice(
        self,
        opportunity_id: UUID | None,
        interaction_id: UUID | None,
    ) -> None:
        async with self._factory.unit_of_work(read_only=True) as uow:
            source = await self._locate(uow, opportunity_id, interaction_id)
        if (
            source is not None
            and source.modality == "live_voice"
            and self._voice_failure is not None
            and source.operation_id is not None
        ):
            await self._voice_failure(source.operation_id)
