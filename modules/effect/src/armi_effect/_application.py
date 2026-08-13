"""Production T-05 registration and T-06 Creator response dispatch pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid7

from armi_capability.api import CapabilityGrantConsumptionPort
from armi_kernel.application import (
    ArtifactViolation,
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    DurableWorkPort,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import ContractViolation
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._dispatch import (
    EffectDispatchSnapshot,
    PostgreSQLEffectDispatchRepository,
)
from ._inbox import PostgreSQLLocalInbox
from ._ledger import (
    EffectRegistrationSnapshot,
    PostgreSQLEffectLedgerRepository,
)
from ._router import RoutedActionAdapter
from .api import (
    ActionAdapterPort,
    EffectAdapterReceipt,
    EffectArtifactContent,
    EffectArtifactKind,
    EffectArtifactStorePort,
    EffectId,
    EffectRegistrationResult,
    EffectView,
    EffectViolation,
    EffectWakeupPort,
)

Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]
EFFECT_REGISTER = "effect.register"


def _ignore_diagnostic(event: str) -> None:
    del event


class EffectRegistrationPipeline:
    __slots__ = (
        "_adapter",
        "_diagnostic",
        "_dispatcher",
        "_factory",
        "_fault_injector",
        "_lease_owner",
        "_notifier",
        "_repository",
        "_stop",
        "_storage",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: EffectArtifactStorePort,
        work: DurableWorkPort,
        capability_consumption: CapabilityGrantConsumptionPort,
        notifier: CreatorProjectionNotifier | None = None,
        adapter: ActionAdapterPort | None = None,
        external_message_adapter: ActionAdapterPort | None = None,
        wakeups: EffectWakeupPort,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._repository = PostgreSQLEffectLedgerRepository(capability_consumption)
        self._dispatcher = PostgreSQLEffectDispatchRepository()
        if adapter is not None and external_message_adapter is not None:
            raise ValueError("whole-effect and external-message adapters are exclusive")
        if adapter is not None:
            self._adapter = adapter
        else:
            local_inbox = PostgreSQLLocalInbox(factory)
            routes: dict[str, ActionAdapterPort] = {
                "creator_inbox": local_inbox,
                "other_human_inbox": local_inbox,
            }
            if external_message_adapter is not None:
                routes["external_group"] = external_message_adapter
                routes["external_private"] = external_message_adapter
            self._adapter = RoutedActionAdapter(routes)
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups
        self._diagnostic: Diagnostic = diagnostic or _ignore_diagnostic
        self._notifier = notifier
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def open(self) -> None:
        await self._factory.open()
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def register_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind="effect.register",
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            raise EffectViolation("EFFECT-DATABASE") from None
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        try:
            async with self._factory.unit_of_work() as uow:
                snapshot = await self._repository.snapshot(uow, lease)
            integrity_ok = (
                await self._read_payload(
                    snapshot.artifact_id,
                    snapshot.payload_digest.value,
                    snapshot.payload_bytes,
                )
                is not None
            )
            async with self._factory.unit_of_work() as uow:
                result = await self._repository.settle(
                    uow, lease=lease, snapshot=snapshot, integrity_ok=integrity_ok
                )
                self._fault_injector("effect_after_register_before_settlement")
            await self._notify_registration(snapshot, result)
            return True
        except EffectViolation as error:
            if error.code == "EFFECT-WORK-STALE":
                await self._settle_registration_work(lease)
            else:
                await self._fail_registration_work(lease, error.code)
            return True
        except RuntimeTransactionFailure, WorkViolation:
            self._diagnostic("effect.registration.transient_failure")
            return True

    async def _settle_registration_work(self, lease: WorkLease) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.settle_current_work(unit_of_work, lease)
        except RuntimeTransactionFailure, EffectViolation, WorkViolation:
            self._diagnostic("effect.registration.settlement_deferred")

    async def _fail_registration_work(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail_current_work(
                    unit_of_work,
                    lease,
                    code=code,
                )
        except RuntimeTransactionFailure, EffectViolation, WorkViolation:
            self._diagnostic("effect.registration.settlement_deferred")

    async def get_effect(
        self, effect_id: EffectId, *, creator_party_id: UUID
    ) -> EffectView:
        async with self._factory.unit_of_work(read_only=True) as uow:
            view = await self._repository.get_effect(uow, effect_id, creator_party_id)
            payload_reference = (
                await self._repository.payload_reference(uow, effect_id)
                if view.status.value == "completed"
                and view.effect_kind == "creator_response"
                else None
            )
        if payload_reference is None:
            return view
        artifact_id, digest, size = payload_reference
        value = await self._read_payload(artifact_id, digest.value, size)
        if value is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE") from None
        return replace(view, response_text=text)

    async def read_artifact(
        self,
        effect_id: EffectId,
        *,
        creator_party_id: UUID,
        kind: EffectArtifactKind,
    ) -> EffectArtifactContent:
        async with self._factory.unit_of_work(read_only=True) as uow:
            (
                artifact_id,
                digest,
                size,
                media_type,
            ) = await self._repository.codex_artifact_reference(
                uow, effect_id, creator_party_id, kind.value
            )
        value = await self._read_payload(artifact_id, digest.value, size)
        if value is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        if media_type not in {"application/json", "text/plain"}:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return EffectArtifactContent(kind, media_type, value)

    async def dispatch_once(self) -> bool:
        try:
            async with self._factory.unit_of_work() as uow:
                snapshot = await self._dispatcher.claim(
                    uow, claim_owner=self._lease_owner
                )
            if snapshot is None:
                return False
            payload = await self._read_payload(
                snapshot.artifact_id,
                snapshot.request.payload_digest.value,
                snapshot.request.payload_bytes,
            )
            if payload is None:
                async with self._factory.unit_of_work() as uow:
                    await self._dispatcher.settle_integrity_failure(uow, snapshot)
                await self._notify_dispatch(snapshot, include_scene=False)
                return True
            async with self._factory.unit_of_work() as uow:
                dispatching = await self._dispatcher.mark_dispatching(uow, snapshot)
            if not dispatching:
                await self._notify_dispatch(snapshot, include_scene=False)
                return True
            await self._notify_dispatch(snapshot, include_scene=False)
            try:
                receipt = await self._dispatch_with_heartbeat(snapshot, payload)
            except EffectViolation as error:
                if error.code == "EFFECT-RECEIVER-CONFLICT":
                    async with self._factory.unit_of_work() as uow:
                        await self._dispatcher.settle_integrity_failure(uow, snapshot)
                    await self._notify_dispatch(snapshot, include_scene=False)
                    return True
                if error.code in {
                    "EFFECT-RECEIVER-NOT-DELIVERED",
                    "EFFECT-ADAPTER-UNAVAILABLE",
                }:
                    async with self._factory.unit_of_work() as uow:
                        await self._dispatcher.settle_rejection(uow, snapshot)
                    await self._notify_dispatch(snapshot, include_scene=False)
                    return True
                if error.code == "EFFECT-RESULT-UNKNOWN":
                    async with self._factory.unit_of_work() as uow:
                        await self._dispatcher.settle_unknown(uow, snapshot)
                    await self._notify_dispatch(snapshot, include_scene=False)
                    return True
                return await self._reconcile(snapshot)
            self._fault_injector("adapter_after_dispatch_before_settlement")
            async with self._factory.unit_of_work() as uow:
                await self._dispatcher.settle_receipt(uow, snapshot, receipt)
            await self._notify_dispatch(snapshot, include_scene=True)
            return True
        except RuntimeTransactionFailure, EffectViolation:
            self._diagnostic("effect.dispatch.transient_failure")
            return True

    async def recover_once(self) -> bool:
        try:
            async with self._factory.unit_of_work() as uow:
                snapshot = await self._dispatcher.expired(uow)
            if snapshot is not None:
                await self._reconcile(snapshot)
                return True
            async with self._factory.unit_of_work() as uow:
                unknown = await self._dispatcher.unknown(uow)
            if unknown is None:
                return False
            try:
                receipt = await self._adapter.observe(unknown.request)
            except RuntimeTransactionFailure, EffectViolation:
                self._diagnostic("effect.unknown_verification.unavailable")
                return False
            async with self._factory.unit_of_work() as uow:
                if receipt is None:
                    await self._dispatcher.resolve_unknown_absent(uow, unknown)
                else:
                    await self._dispatcher.resolve_unknown_receipt(
                        uow, unknown, receipt
                    )
            if receipt is not None:
                await self._notify_dispatch(unknown, include_scene=True)
            else:
                await self._notify_dispatch(unknown, include_scene=False)
            return True
        except RuntimeTransactionFailure, EffectViolation:
            if self._stop.is_set():
                return False
            self._diagnostic("effect.recovery.failed")
            return True

    async def _reconcile(self, snapshot: EffectDispatchSnapshot) -> bool:
        try:
            receipt = await self._adapter.observe(snapshot.request)
        except RuntimeTransactionFailure, EffectViolation:
            async with self._factory.unit_of_work() as uow:
                await self._dispatcher.settle_unknown(uow, snapshot)
            await self._notify_dispatch(snapshot, include_scene=False)
            return True
        if receipt is not None:
            async with self._factory.unit_of_work() as uow:
                await self._dispatcher.settle_receipt(uow, snapshot, receipt)
            await self._notify_dispatch(snapshot, include_scene=True)
            return True
        async with self._factory.unit_of_work() as uow:
            await self._dispatcher.settle_absent(uow, snapshot)
        await self._notify_dispatch(snapshot, include_scene=False)
        return True

    async def _dispatch_with_heartbeat(
        self, snapshot: EffectDispatchSnapshot, payload: bytes
    ) -> EffectAdapterReceipt:
        task = asyncio.create_task(self._adapter.dispatch(snapshot.request, payload))
        try:
            while True:
                done, _ = await asyncio.wait((task,), timeout=20)
                if task in done:
                    return task.result()
                async with self._factory.unit_of_work() as uow:
                    await self._dispatcher.renew_claim(uow, snapshot)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _notify_registration(
        self,
        snapshot: EffectRegistrationSnapshot,
        result: EffectRegistrationResult | None,
    ) -> None:
        invalidations = [
            (
                CreatorEventResourceKind.OPERATION,
                str(snapshot.root_operation_id),
                "creator-operation.v1",
            )
        ]
        if result is not None:
            invalidations.append(
                (
                    CreatorEventResourceKind.EFFECT,
                    str(result.effect_id.value),
                    "creator-effect.v3",
                )
            )
        await self._notify(invalidations)

    async def _notify_dispatch(
        self, snapshot: EffectDispatchSnapshot, *, include_scene: bool
    ) -> None:
        if snapshot.request.destination_kind != "creator_inbox":
            return
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                view = await self._repository.get_effect(
                    unit_of_work,
                    snapshot.request.effect_id,
                    creator_party_id=snapshot.request.destination_party_id,
                )
        except RuntimeTransactionFailure, EffectViolation:
            self._diagnostic("effect.notification.lookup_failed")
            return
        invalidations = [
            (
                CreatorEventResourceKind.EFFECT,
                str(snapshot.request.effect_id.value),
                "creator-effect.v3",
            ),
            (
                CreatorEventResourceKind.OPERATION,
                str(view.root_operation_ref),
                "creator-operation.v1",
            ),
        ]
        if include_scene:
            invalidations.insert(
                0,
                (
                    CreatorEventResourceKind.SCENE_TIMELINE,
                    snapshot.scene_key,
                    "scene-timeline.v5",
                ),
            )
        await self._notify(invalidations)

    async def _notify(
        self,
        invalidations: list[tuple[CreatorEventResourceKind, str, str]],
    ) -> None:
        if self._notifier is None:
            return
        from armi_kernel.contracts import Instant

        now = Instant(datetime.now(UTC))
        for resource_kind, resource_ref, projection_version in invalidations:
            try:
                await self._notifier.notify(
                    CreatorProjectionInvalidation(
                        resource_kind,
                        resource_ref,
                        now,
                        projection_version,
                    )
                )
            except Exception:
                self._diagnostic("effect.projection_notification.failed")

    async def _read_payload(
        self, artifact_id: UUID, digest: str, size: int
    ) -> bytes | None:
        try:
            from armi_kernel.application import (
                ArtifactId,
                ArtifactIntegrityStatus,
                ArtifactPrivacyScope,
                ArtifactRef,
            )
            from armi_kernel.contracts import Digest

            reference = ArtifactRef(
                ArtifactId(artifact_id),
                Digest(digest),
                size,
                "text/plain",
                "creator.reply.text",
                ArtifactPrivacyScope.CREATOR_VISIBLE,
                ArtifactIntegrityStatus.VERIFIED,
            )
            stream = await self._storage.open_verified(reference)
            try:
                value = await stream.read()
            finally:
                await stream.close()
            if len(value) != size:
                return None
            return value
        except ArtifactViolation, ContractViolation, OSError:
            return None

    async def run(self) -> None:
        observed = self._wakeups.version(EFFECT_REGISTER)
        while not self._stop.is_set():
            if await self.recover_once():
                await asyncio.sleep(0)
                continue
            if self._stop.is_set():
                break
            if await self.register_once():
                await asyncio.sleep(0)
                continue
            if self._stop.is_set():
                break
            if await self.dispatch_once():
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                EFFECT_REGISTER,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )


__all__ = ("EffectRegistrationPipeline",)
