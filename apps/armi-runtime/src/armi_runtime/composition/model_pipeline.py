"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CredentialLocator,
    CredentialPort,
    LockPlan,
    LockTarget,
    ModelAttemptId,
    ModelInvocationResult,
    ModelRequest,
    ModelResultStatus,
    ModelViolation,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.cognitive_model import (
    ModelEpisodeSnapshot,
    PostgreSQLCognitiveModelRepository,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .dialogue_candidate_contract import dialogue_model_output_schema
from .model_contract import (
    ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    ACTIVITY_ATTENTION_INSTRUCTIONS,
    ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
    ACTIVITY_INTERNAL_WORK_INSTRUCTIONS,
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    CREATOR_OUTREACH_INSTRUCTIONS,
    DIALOGUE_CANDIDATE_VERSION,
    DIALOGUE_INSTRUCTIONS,
    MAINTENANCE_WORK_CANDIDATE_VERSION,
    MEMORY_MAINTENANCE_INSTRUCTIONS,
    SLEEP_DECISION_CANDIDATE_VERSION,
    SLEEP_DECISION_INSTRUCTIONS,
    SUBJECT_SELF_CHECK_INSTRUCTIONS,
    WEB_DIALOGUE_CANDIDATE_VERSION,
    WEB_DIALOGUE_INSTRUCTIONS,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    parse_candidate,
)
from .other_human_dialogue_candidate_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
    parse_other_human_dialogue_candidate,
)
from .work_wakeup import CANDIDATE_VALIDATE, MODEL_INVOKE, WorkWakeupBus

_WORK_KIND = "cognition.model.invoke"
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class ModelPipeline:
    """Claim model work and preserve every physical provider attempt."""

    __slots__ = (
        "_adapters",
        "_catalog",
        "_diagnostic",
        "_dialogue_version",
        "_factory",
        "_lease_owner",
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
        credential_port: CredentialPort,
        credential_locator: CredentialLocator,
        web_search_active: bool = False,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        dialogue_version = (
            WEB_DIALOGUE_CANDIDATE_VERSION
            if web_search_active
            else DIALOGUE_CANDIDATE_VERSION
        )
        default_binding = load_active_binding(
            expected_dialogue_version=dialogue_version
        )
        dialogue_binding = load_purpose_binding(
            "consider_creator_input",
            expected_dialogue_version=dialogue_version,
        )
        life_query_result_binding = load_purpose_binding(
            "consider_life_query_result",
            expected_dialogue_version=dialogue_version,
        )
        outreach_binding = load_purpose_binding(
            "consider_creator_outreach",
            expected_dialogue_version=dialogue_version,
        )
        other_human_binding = load_purpose_binding(
            "consider_other_human_input",
            expected_dialogue_version=dialogue_version,
        )
        autonomous_binding = load_purpose_binding(
            "consider_autonomous_life",
            expected_dialogue_version=dialogue_version,
        )
        attention_binding = load_purpose_binding(
            "consider_activity_attention",
            expected_dialogue_version=dialogue_version,
        )
        internal_work_binding = load_purpose_binding(
            "consider_activity_internal_work",
            expected_dialogue_version=dialogue_version,
        )
        sleep_binding = load_purpose_binding(
            "consider_sleep",
            expected_dialogue_version=dialogue_version,
        )
        memory_maintenance_binding = load_purpose_binding(
            "maintain_subjective_memory",
            expected_dialogue_version=dialogue_version,
        )
        self_check_binding = load_purpose_binding(
            "perform_subject_self_check",
            expected_dialogue_version=dialogue_version,
        )
        self._dialogue_version = dialogue_version

        def parse_dialogue(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=dialogue_version,
            )

        def parse_autonomous(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
            )

        def parse_outreach(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=DIALOGUE_CANDIDATE_VERSION,
            )

        def parse_other_human(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_other_human_dialogue_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
            )

        def parse_attention(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=ACTIVITY_ATTENTION_CANDIDATE_VERSION,
            )

        def parse_internal_work(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
            )

        def parse_sleep(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=SLEEP_DECISION_CANDIDATE_VERSION,
            )

        def parse_maintenance_work(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=MAINTENANCE_WORK_CANDIDATE_VERSION,
            )

        self._factory = factory
        self._storage = storage
        self._adapters = {
            "__default__": VolcengineArkModelAdapter(
                binding=default_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    default_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_creator_input": VolcengineArkModelAdapter(
                binding=dialogue_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=dialogue_model_output_schema(
                    web_search=web_search_active
                ),
                candidate_parser=parse_dialogue,
                instructions=(
                    WEB_DIALOGUE_INSTRUCTIONS
                    if web_search_active
                    else DIALOGUE_INSTRUCTIONS
                ),
                schema_name=(
                    "armi_creator_dialogue_model_output_v1_web"
                    if web_search_active
                    else "armi_creator_dialogue_model_output_v1"
                ),
            ),
            "consider_life_query_result": VolcengineArkModelAdapter(
                binding=life_query_result_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=dialogue_model_output_schema(
                    web_search=web_search_active
                ),
                candidate_parser=parse_dialogue,
                instructions=(
                    WEB_DIALOGUE_INSTRUCTIONS
                    if web_search_active
                    else DIALOGUE_INSTRUCTIONS
                ),
                schema_name=(
                    "armi_creator_dialogue_model_output_v1_web"
                    if web_search_active
                    else "armi_creator_dialogue_model_output_v1"
                ),
            ),
            "consider_creator_outreach": VolcengineArkModelAdapter(
                binding=outreach_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(DIALOGUE_CANDIDATE_VERSION),
                candidate_parser=parse_outreach,
                instructions=CREATOR_OUTREACH_INSTRUCTIONS,
                schema_name="armi_creator_outreach_candidate_v1",
            ),
            "consider_other_human_input": VolcengineArkModelAdapter(
                binding=other_human_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
                ),
                candidate_parser=parse_other_human,
                instructions=OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
                schema_name="armi_other_human_dialogue_candidate_v1",
            ),
            "consider_autonomous_life": VolcengineArkModelAdapter(
                binding=autonomous_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    autonomous_binding.response_contract_version
                ),
                candidate_parser=parse_autonomous,
                instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
                schema_name="armi_autonomous_activity_candidate_v1",
            ),
            "consider_activity_attention": VolcengineArkModelAdapter(
                binding=attention_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    attention_binding.response_contract_version
                ),
                candidate_parser=parse_attention,
                instructions=ACTIVITY_ATTENTION_INSTRUCTIONS,
                schema_name="armi_activity_attention_candidate_v2",
            ),
            "consider_activity_internal_work": VolcengineArkModelAdapter(
                binding=internal_work_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    internal_work_binding.response_contract_version
                ),
                candidate_parser=parse_internal_work,
                instructions=ACTIVITY_INTERNAL_WORK_INSTRUCTIONS,
                schema_name="armi_activity_internal_work_candidate_v1",
            ),
            "consider_sleep": VolcengineArkModelAdapter(
                binding=sleep_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    sleep_binding.response_contract_version
                ),
                candidate_parser=parse_sleep,
                instructions=SLEEP_DECISION_INSTRUCTIONS,
                schema_name="armi_sleep_decision_candidate_v1",
            ),
            "maintain_subjective_memory": VolcengineArkModelAdapter(
                binding=memory_maintenance_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    memory_maintenance_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=MEMORY_MAINTENANCE_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "perform_subject_self_check": VolcengineArkModelAdapter(
                binding=self_check_binding,
                credential_port=credential_port,
                locator=credential_locator,
                candidate_schema=candidate_schema(
                    self_check_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=SUBJECT_SELF_CHECK_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
        }
        self._catalog = ArtifactCatalogRepository()
        self._repository = PostgreSQLCognitiveModelRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise ModelViolation("MODEL-DATABASE") from None
        except ArtifactViolation:
            raise ModelViolation("MODEL-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def invoke_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise ModelViolation("MODEL-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            adapter = self._adapter_for(snapshot.purpose)
            context_bytes = await self._read_context(snapshot)
            request_bytes = build_request_bytes(
                binding=adapter.binding,
                compiled_context=context_bytes,
                context_digest=snapshot.context_digest,
                base_subject_version=snapshot.base_subject_version,
                base_state_epoch=snapshot.base_state_epoch,
                bundle_activation_id=snapshot.bundle_activation_id,
                included_context_refs=snapshot.included_context_refs,
            )
            input_tokens = await adapter.tokenize(request_bytes)
            request = checked_model_request(
                binding=adapter.binding,
                request_bytes=request_bytes,
                context_digest=snapshot.context_digest,
                input_tokens=input_tokens,
            )
            published_request = await self._publish(
                request.canonical_bytes,
                logical_kind="model.request",
                snapshot=snapshot,
            )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                request_registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    published_request,
                )
                if request_registration.inserted:
                    await unit_of_work.audit.append(
                        _artifact_audit(
                            unit_of_work,
                            request_registration.ref,
                            snapshot,
                        )
                    )
                attempt_id = await self._repository.prepare_attempt(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    binding=adapter.binding,
                    request_artifact=request_registration.ref,
                )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                await self._repository.mark_dispatched(
                    unit_of_work,
                    lease=lease,
                    attempt_id=attempt_id,
                    episode_id=snapshot.episode_id,
                )
            result, lease = await self._invoke_with_renewal(adapter, request, lease)
            if result.status is ModelResultStatus.SUCCEEDED:
                assert result.response_bytes is not None
                published_response = await self._publish(
                    result.response_bytes,
                    logical_kind="model.response",
                    snapshot=snapshot,
                )
                async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                    response_registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published_response,
                    )
                    if response_registration.inserted:
                        await unit_of_work.audit.append(
                            _artifact_audit(
                                unit_of_work,
                                response_registration.ref,
                                snapshot,
                            )
                        )
                    await self._repository.settle_success(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        attempt_id=attempt_id,
                        response_artifact=response_registration.ref,
                        result=result,
                    )
                self._wakeups.notify(CANDIDATE_VALIDATE)
            else:
                await self._settle_failure(
                    lease=lease,
                    snapshot=snapshot,
                    attempt_id=attempt_id,
                    result=result,
                    retryable=None,
                )
            return True
        except ModelViolation as error:
            if error.code == "MODEL-WORK-STALE":
                self._diagnostic("model.work.stale")
                return True
            attempt = locals().get("attempt_id")
            current_snapshot = locals().get("snapshot")
            if isinstance(attempt, ModelAttemptId) and isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    attempt_id=attempt,
                    result=_error_result(error),
                    retryable=error.retryable,
                )
                return True
            await self._settle_before_attempt(lease, locals().get("snapshot"), error)
            return True
        except ArtifactViolation:
            error = ModelViolation("MODEL-ARTIFACT", retryable=True)
            attempt = locals().get("attempt_id")
            current_snapshot = locals().get("snapshot")
            if isinstance(attempt, ModelAttemptId) and isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    attempt_id=attempt,
                    result=_error_result(error),
                    retryable=True,
                )
            else:
                await self._settle_before_attempt(
                    lease,
                    current_snapshot,
                    error,
                )
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("model.worker.transient_failure")
            return True

    async def run_worker(self) -> None:
        observed = self._wakeups.version(MODEL_INVOKE)
        while not self._stop.is_set():
            try:
                worked = await self.invoke_once()
            except ModelViolation:
                if not self._stop.is_set():
                    self._diagnostic("model.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                MODEL_INVOKE,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def _snapshot(self, lease: WorkLease) -> ModelEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except DatabaseTransactionError:
            raise ModelViolation("MODEL-DATABASE") from None

    async def _read_context(self, snapshot: ModelEpisodeSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.compiled_context)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise ModelViolation("MODEL-CONTEXT") from None
        if not value:
            raise ModelViolation("MODEL-CONTEXT")
        return value

    async def _publish(
        self,
        value: bytes,
        *,
        logical_kind: str,
        snapshot: ModelEpisodeSnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                "application/json",
                logical_kind,
                "model.adapter",
                snapshot.trace_id,
                ArtifactPrivacyScope.RESTRICTED,
            ),
        )
        return await self._storage.publish(staged)

    async def _invoke_with_renewal(
        self,
        adapter: VolcengineArkModelAdapter,
        request: ModelRequest,
        lease: WorkLease,
    ) -> tuple[ModelInvocationResult, WorkLease]:
        task = asyncio.create_task(
            adapter.invoke(request),
            name=f"model-attempt-{lease.attempt_id}",
        )
        current_lease = lease
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_RENEW_SECONDS)
                if done:
                    return await task, current_lease
                try:
                    current_lease = await self._work.renew(
                        current_lease,
                        lease_seconds=_LEASE_SECONDS,
                    )
                except WorkViolation:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise ModelViolation("MODEL-WORK-STALE") from None
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    def _adapter_for(self, purpose: str) -> VolcengineArkModelAdapter:
        adapter = self._adapters.get(purpose, self._adapters["__default__"])
        if (
            purpose in {"consider_creator_input", "consider_life_query_result"}
            and adapter.binding.response_contract_version != self._dialogue_version
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_creator_outreach"
            and adapter.binding.response_contract_version != DIALOGUE_CANDIDATE_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_other_human_input"
            and adapter.binding.response_contract_version
            != OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        return adapter

    async def _settle_failure(
        self,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
        retryable: bool | None,
    ) -> None:
        if retryable is None:
            retryable = result.status in {
                ModelResultStatus.TIMED_OUT,
                ModelResultStatus.OUTCOME_UNKNOWN,
                ModelResultStatus.REJECTED,
            }
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            await self._repository.settle_failure(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                attempt_id=attempt_id,
                result=result,
                retryable=retryable,
            )

    async def _settle_before_attempt(
        self,
        lease: WorkLease,
        snapshot: object,
        error: ModelViolation,
    ) -> None:
        safe_code = error.code.lower().replace("-", "_")
        self._diagnostic(f"model.preparation.failed.{safe_code}")
        if not isinstance(snapshot, ModelEpisodeSnapshot):
            self._diagnostic("model.preparation.deferred")
            return
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                if error.retryable:
                    now = await (
                        await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
                            "SELECT statement_timestamp()"
                        )
                    ).fetchone()
                    if now is None:
                        raise ModelViolation("MODEL-DATABASE")
                    await unit_of_work.work.release(
                        lease,
                        not_before=Instant(now[0] + timedelta(seconds=1)),
                        error_code=error.code,
                    )
                else:
                    await self._repository.fail_before_attempt(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        code=error.code,
                    )
        except DatabaseTransactionError, ModelViolation, WorkViolation:
            self._diagnostic("model.preparation.settlement_deferred")


def _artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: ModelEpisodeSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.model"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


def _error_result(error: ModelViolation) -> ModelInvocationResult:
    status = (
        ModelResultStatus.OUTCOME_UNKNOWN
        if error.outcome_unknown
        else ModelResultStatus.TIMED_OUT
        if error.code == "MODEL-REQUEST-TIMEOUT"
        else ModelResultStatus.PROVIDER_FAILED
    )
    return ModelInvocationResult(
        status,
        None,
        None,
        None,
        None,
        error.code,
    )


def build_model_pipeline(
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
    credential_port: CredentialPort,
    credential_locator: CredentialLocator,
    web_search_active: bool = False,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
) -> ModelPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise ModelViolation("MODEL-LOCK")

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
    return ModelPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        credential_port=credential_port,
        credential_locator=credential_locator,
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = ("ModelPipeline", "build_model_pipeline")
