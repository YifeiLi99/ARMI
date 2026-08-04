"""Production T-05 registration and T-06 Creator response dispatch pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ActionAdapterPort,
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    EffectAdapterReceipt,
    EffectArtifactContent,
    EffectArtifactKind,
    EffectId,
    EffectRegistrationResult,
    EffectView,
    EffectViolation,
    LockPlan,
    LockTarget,
    RuntimeFence,
    SceneKey,
    WorkViolation,
)

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.creator_response_inbox import (
    PostgreSQLCreatorResponseInbox,
)
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.effect_dispatch import (
    EffectDispatchSnapshot,
    PostgreSQLEffectDispatchRepository,
)
from armi_runtime.adapters.persistence.effect_ledger import (
    EffectRegistrationSnapshot,
    PostgreSQLEffectLedgerRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import EFFECT_REGISTER, WorkWakeupBus

Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


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
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        notifier: CreatorProjectionNotifier | None = None,
        adapter: ActionAdapterPort | None = None,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._repository = PostgreSQLEffectLedgerRepository()
        self._dispatcher = PostgreSQLEffectDispatchRepository()
        self._adapter = adapter or PostgreSQLCreatorResponseInbox(factory)
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
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
        lease = records[0].lease
        assert lease is not None
        try:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                snapshot = await self._repository.snapshot(uow, lease)
            integrity_ok = (
                await self._read_payload(
                    snapshot.artifact_id,
                    snapshot.payload_digest.value,
                    snapshot.payload_bytes,
                )
                is not None
            )
            async with self._factory.unit_of_work(LockPlan()) as uow:
                result = await self._repository.settle(
                    uow, lease=lease, snapshot=snapshot, integrity_ok=integrity_ok
                )
                self._fault_injector("effect_after_register_before_settlement")
            await self._notify_registration(snapshot, result)
            return True
        except EffectViolation as error:
            if error.code != "EFFECT-WORK-STALE":
                self._diagnostic("effect.registration.failed")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("effect.registration.transient_failure")
            return True

    async def get_effect(
        self, effect_id: EffectId, *, creator_party_id: UUID
    ) -> EffectView:
        async with self._factory.unit_of_work(LockPlan(), read_only=True) as uow:
            view = await self._repository.get_effect(uow, effect_id, creator_party_id)
            if view.effect_kind == "codex_delegation" and view.status.value in {
                "completed",
                "failed",
                "unknown",
            }:
                manifest_reference = await self._repository.codex_manifest_reference(
                    uow,
                    effect_id,
                )
            else:
                manifest_reference = None
            payload_reference = (
                await self._repository.payload_reference(uow, effect_id)
                if view.status.value == "completed"
                and view.effect_kind == "creator_response"
                else None
            )
        if manifest_reference is not None:
            artifact_id, digest, size = manifest_reference
            value = await self._read_payload(artifact_id, digest.value, size)
            if value is None:
                raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
            try:
                document = json.loads(value)
                model_id = document["model_id"]
            except KeyError, TypeError, ValueError, json.JSONDecodeError:
                raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE") from None
            if model_id not in {
                "gpt-5.6-sol",
                "gpt-5.6-terra",
                "gpt-5.6-luna",
            }:
                raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
            return replace(view, model_id=model_id)
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
        async with self._factory.unit_of_work(LockPlan(), read_only=True) as uow:
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
            async with self._factory.unit_of_work(LockPlan()) as uow:
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
                async with self._factory.unit_of_work(LockPlan()) as uow:
                    await self._dispatcher.settle_integrity_failure(uow, snapshot)
                await self._notify_dispatch(snapshot, include_scene=False)
                return True
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._dispatcher.mark_dispatching(uow, snapshot)
            await self._notify_dispatch(snapshot, include_scene=False)
            try:
                receipt = await self._dispatch_with_heartbeat(snapshot, payload)
            except EffectViolation as error:
                if error.code == "EFFECT-RECEIVER-CONFLICT":
                    async with self._factory.unit_of_work(LockPlan()) as uow:
                        await self._dispatcher.settle_integrity_failure(uow, snapshot)
                    await self._notify_dispatch(snapshot, include_scene=False)
                    return True
                return await self._reconcile(snapshot)
            self._fault_injector("adapter_after_dispatch_before_settlement")
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._dispatcher.settle_receipt(uow, snapshot, receipt)
            await self._notify_dispatch(snapshot, include_scene=True)
            return True
        except DatabaseTransactionError, EffectViolation:
            self._diagnostic("effect.dispatch.transient_failure")
            return True

    async def recover_once(self) -> bool:
        try:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                snapshot = await self._dispatcher.expired(uow)
            if snapshot is not None:
                await self._reconcile(snapshot)
                return True
            async with self._factory.unit_of_work(LockPlan()) as uow:
                unknown = await self._dispatcher.unknown(uow)
            if unknown is None:
                return False
            try:
                receipt = await self._adapter.observe(unknown.request)
            except DatabaseTransactionError, EffectViolation:
                self._diagnostic("effect.unknown_verification.unavailable")
                return False
            async with self._factory.unit_of_work(LockPlan()) as uow:
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
        except DatabaseTransactionError, EffectViolation:
            if self._stop.is_set():
                return False
            self._diagnostic("effect.recovery.failed")
            return True

    async def _reconcile(self, snapshot: EffectDispatchSnapshot) -> bool:
        try:
            receipt = await self._adapter.observe(snapshot.request)
        except DatabaseTransactionError, EffectViolation:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._dispatcher.settle_unknown(uow, snapshot)
            await self._notify_dispatch(snapshot, include_scene=False)
            return True
        if receipt is not None:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._dispatcher.settle_receipt(uow, snapshot, receipt)
            await self._notify_dispatch(snapshot, include_scene=True)
            return True
        async with self._factory.unit_of_work(LockPlan()) as uow:
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
                async with self._factory.unit_of_work(LockPlan()) as uow:
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
                    "creator-effect.v1",
                )
            )
        await self._notify(invalidations)

    async def _notify_dispatch(
        self, snapshot: EffectDispatchSnapshot, *, include_scene: bool
    ) -> None:
        try:
            async with self._factory.unit_of_work(
                LockPlan(), read_only=True
            ) as unit_of_work:
                view = await self._repository.get_effect(
                    unit_of_work,
                    snapshot.request.effect_id,
                    creator_party_id=snapshot.request.creator_party_id,
                )
        except DatabaseTransactionError, EffectViolation:
            self._diagnostic("effect.notification.lookup_failed")
            return
        invalidations = [
            (
                CreatorEventResourceKind.EFFECT,
                str(snapshot.request.effect_id.value),
                "creator-effect.v1",
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
                    SceneKey(snapshot.scene_key).value,
                    "scene-timeline.v3",
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
                1,
            )
            stream = await self._storage.open_verified(reference)
            try:
                value = await stream.read()
            finally:
                await stream.close()
            if len(value) != size or Digest.from_bytes(value).value != digest:
                return None
            return value
        except Exception:
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


def build_effect_registration_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None = None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
) -> EffectRegistrationPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise EffectViolation("EFFECT-LOCK")

    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=reject_dynamic_lock,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return EffectRegistrationPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


__all__ = ("EffectRegistrationPipeline", "build_effect_registration_pipeline")
