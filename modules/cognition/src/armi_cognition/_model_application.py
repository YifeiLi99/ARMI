"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid7

from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
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
    DurableWorkPort,
    ModelAttemptId,
    ModelInvocationResult,
    ModelRequest,
    ModelResultStatus,
    ModelViolation,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._dialogue_contract import dialogue_model_output_schema
from ._model_contract import (
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
    parse_dialogue_candidate_with_independent_expression,
)
from ._model_postgresql import (
    ModelEpisodeSnapshot,
    PostgreSQLCognitiveModelRepository,
)
from ._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
    parse_other_human_dialogue_candidate,
)
from .api import (
    CognitionArtifactCatalogPort,
    CognitionModelAdapterFactory,
    CognitionModelPort,
    CognitionWakeupPort,
)

_WORK_KIND = "cognition.model.invoke"
MODEL_INVOKE = _WORK_KIND
CANDIDATE_VALIDATE = "cognition.candidate.validate"
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class _Pulse:
    version: int
    event: asyncio.Event


class _LocalWakeups:
    def __init__(self) -> None:
        self._pulses: dict[str, _Pulse] = {}

    def version(self, channel: str) -> int:
        return self._pulse(channel).version

    def notify(self, channel: str) -> None:
        current = self._pulse(channel)
        current.event.set()
        self._pulses[channel] = _Pulse(current.version + 1, asyncio.Event())

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: asyncio.Event,
        timeout_seconds: float,
    ) -> int:
        current = self._pulse(channel)
        if current.version != after_version or stop.is_set():
            return current.version
        with suppress(TimeoutError):
            await asyncio.wait_for(current.event.wait(), timeout=timeout_seconds)
        return self._pulse(channel).version

    def _pulse(self, channel: str) -> _Pulse:
        return self._pulses.setdefault(channel, _Pulse(0, asyncio.Event()))


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
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: CognitionArtifactCatalogPort,
        work: DurableWorkPort,
        adapter_factory: CognitionModelAdapterFactory,
        binding_path: Path,
        web_search_active: bool = False,
        wakeups: CognitionWakeupPort | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        dialogue_version = (
            WEB_DIALOGUE_CANDIDATE_VERSION
            if web_search_active
            else DIALOGUE_CANDIDATE_VERSION
        )
        load_active_binding(
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        dialogue_binding = load_purpose_binding(
            "consider_creator_input",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        life_query_result_binding = load_purpose_binding(
            "consider_life_query_result",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        outreach_binding = load_purpose_binding(
            "consider_creator_outreach",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        other_human_binding = load_purpose_binding(
            "consider_other_human_input",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        autonomous_binding = load_purpose_binding(
            "consider_autonomous_life",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        attention_binding = load_purpose_binding(
            "consider_activity_attention",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        internal_work_binding = load_purpose_binding(
            "consider_activity_internal_work",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        sleep_binding = load_purpose_binding(
            "consider_sleep",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        memory_maintenance_binding = load_purpose_binding(
            "maintain_subjective_memory",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        self_check_binding = load_purpose_binding(
            "perform_subject_self_check",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        web_evidence_binding = load_purpose_binding(
            "consider_web_evidence",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        codex_task_binding = load_purpose_binding(
            "consider_codex_task",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        codex_result_binding = load_purpose_binding(
            "consider_codex_result",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        self._dialogue_version = dialogue_version

        def parse_dialogue(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_dialogue_candidate_with_independent_expression(
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
            "consider_web_evidence": adapter_factory(
                binding=web_evidence_binding,
                candidate_schema=candidate_schema(
                    web_evidence_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_codex_task": adapter_factory(
                binding=codex_task_binding,
                candidate_schema=candidate_schema(
                    codex_task_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_codex_result": adapter_factory(
                binding=codex_result_binding,
                candidate_schema=candidate_schema(
                    codex_result_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_creator_input": adapter_factory(
                binding=dialogue_binding,
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
            "consider_life_query_result": adapter_factory(
                binding=life_query_result_binding,
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
            "consider_creator_outreach": adapter_factory(
                binding=outreach_binding,
                candidate_schema=candidate_schema(DIALOGUE_CANDIDATE_VERSION),
                candidate_parser=parse_outreach,
                instructions=CREATOR_OUTREACH_INSTRUCTIONS,
                schema_name="armi_creator_outreach_candidate_v1",
            ),
            "consider_other_human_input": adapter_factory(
                binding=other_human_binding,
                candidate_schema=candidate_schema(
                    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
                ),
                candidate_parser=parse_other_human,
                instructions=OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
                schema_name="armi_other_human_dialogue_candidate_v1",
            ),
            "consider_autonomous_life": adapter_factory(
                binding=autonomous_binding,
                candidate_schema=candidate_schema(
                    autonomous_binding.response_contract_version
                ),
                candidate_parser=parse_autonomous,
                instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
                schema_name="armi_autonomous_activity_candidate_v1",
            ),
            "consider_activity_attention": adapter_factory(
                binding=attention_binding,
                candidate_schema=candidate_schema(
                    attention_binding.response_contract_version
                ),
                candidate_parser=parse_attention,
                instructions=ACTIVITY_ATTENTION_INSTRUCTIONS,
                schema_name="armi_activity_attention_candidate_v2",
            ),
            "consider_activity_internal_work": adapter_factory(
                binding=internal_work_binding,
                candidate_schema=candidate_schema(
                    internal_work_binding.response_contract_version
                ),
                candidate_parser=parse_internal_work,
                instructions=ACTIVITY_INTERNAL_WORK_INSTRUCTIONS,
                schema_name="armi_activity_internal_work_candidate_v1",
            ),
            "consider_sleep": adapter_factory(
                binding=sleep_binding,
                candidate_schema=candidate_schema(
                    sleep_binding.response_contract_version
                ),
                candidate_parser=parse_sleep,
                instructions=SLEEP_DECISION_INSTRUCTIONS,
                schema_name="armi_sleep_decision_candidate_v1",
            ),
            "maintain_subjective_memory": adapter_factory(
                binding=memory_maintenance_binding,
                candidate_schema=candidate_schema(
                    memory_maintenance_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=MEMORY_MAINTENANCE_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "perform_subject_self_check": adapter_factory(
                binding=self_check_binding,
                candidate_schema=candidate_schema(
                    self_check_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=SUBJECT_SELF_CHECK_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
        }
        self._catalog = catalog
        self._repository = PostgreSQLCognitiveModelRepository()
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or _LocalWakeups()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise ModelViolation("MODEL-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()

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
        lease = cast(WorkLease, records[0].lease)
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
                budget_exclusions=snapshot.budget_exclusions,
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
            async with self._factory.unit_of_work() as unit_of_work:
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
                if attempt_id is None:
                    self._diagnostic("model.outcome_unknown")
                    return True
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.mark_dispatched(
                    unit_of_work,
                    lease=lease,
                    attempt_id=attempt_id,
                    episode_id=snapshot.episode_id,
                )
            result, lease = await self._invoke_with_renewal(adapter, request, lease)
            if result.status is ModelResultStatus.SUCCEEDED:
                published_response = await self._publish(
                    cast(bytes, result.response_bytes),
                    logical_kind="model.response",
                    snapshot=snapshot,
                )
                async with self._factory.unit_of_work() as unit_of_work:
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
                )
                return True
            await self._settle_before_attempt(lease, locals().get("snapshot"), error)
            return True
        except ArtifactViolation:
            error = ModelViolation("MODEL-ARTIFACT")
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
                )
            else:
                await self._settle_before_attempt(
                    lease,
                    current_snapshot,
                    error,
                )
            return True
        except RuntimeTransactionFailure as error:
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
            return True
        except WorkViolation as error:
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
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
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except RuntimeTransactionFailure:
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
        adapter: CognitionModelPort,
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

    def _adapter_for(self, purpose: str) -> CognitionModelPort:
        try:
            adapter = self._adapters[purpose]
        except KeyError:
            raise ModelViolation("MODEL-BINDING") from None
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
    ) -> None:
        async with self._factory.unit_of_work() as unit_of_work:
            await self._repository.settle_failure(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                attempt_id=attempt_id,
                result=result,
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
            async with self._factory.unit_of_work() as unit_of_work:
                if error.retryable:
                    now = await (
                        await unit_of_work.transaction.execute(
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
        except RuntimeTransactionFailure, ModelViolation, WorkViolation:
            self._diagnostic("model.preparation.settlement_deferred")


def _artifact_audit(
    unit_of_work: PostgreSQLRuntimeUnitOfWork,
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


__all__ = ("ModelPipeline",)
