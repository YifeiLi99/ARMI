"""Capability module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_kernel.application import CreatorProjectionNotifier
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._postgresql import PostgreSQLCreatorGrantPolicy
from ._recovery import CapabilityRecoveryParticipant
from .api import (
    CapabilityCommitPort,
    CapabilityEffectCancellationPort,
    CapabilityGrantConsumptionPort,
    CapabilityPolicyPort,
    CapabilityReadPort,
    CreatorGrantCommand,
    CreatorGrantResult,
)


@dataclass(frozen=True, slots=True)
class CapabilityModule:
    policy: CapabilityPolicyPort
    read: CapabilityReadPort
    commit: CapabilityCommitPort
    consumption: CapabilityGrantConsumptionPort
    _owner: PostgreSQLCreatorGrantPolicy

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()

    def stop(self) -> None:
        self._owner.stop()

    async def run_expiry_reconciler(self) -> None:
        await self._owner.run_expiry_reconciler()

    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        return await self._owner.list_requests(
            creator_party_id=creator_party_id,
            limit=limit,
            cursor=cursor,
        )

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult:
        return await self._owner.decide(command)

    async def expire_once(self, *, limit: int = 100) -> int:
        return await self._owner.expire_once(limit=limit)


def bootstrap_capability(
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    environment_id: UUID,
    cursor_key: bytes,
    effect_cancellation: CapabilityEffectCancellationPort,
    notifier: CreatorProjectionNotifier | None = None,
) -> CapabilityModule:
    owner = PostgreSQLCreatorGrantPolicy(
        factory,
        environment_id=environment_id,
        cursor_key=cursor_key,
        effect_cancellation=effect_cancellation,
        notifier=notifier,
    )
    return CapabilityModule(owner, owner, owner, owner, owner)


def bootstrap_capability_recovery() -> RecoveryParticipant:
    return CapabilityRecoveryParticipant()


__all__ = (
    "CapabilityModule",
    "bootstrap_capability",
    "bootstrap_capability_recovery",
)
