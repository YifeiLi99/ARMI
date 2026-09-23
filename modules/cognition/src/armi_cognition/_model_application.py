"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_attention.api import OpportunityCognitionSelectionPort
from armi_context.api import ContextCognitionReadPort
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
    CandidateViolation,
    DurableWorkPort,
    ExecutionCustodyMode,
    ExecutionCustodyPort,
    ExecutionCustodyRequest,
    ExecutionCustodyScope,
    ExecutionCustodyScopeKind,
    ExecutionCustodyViolation,
    ModelAttemptId,
    ModelBinding,
    ModelInvocationResult,
    ModelResultStatus,
    ModelViolation,
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    SubjectCommitViolation,
    WorkLease,
    WorkRecord,
    WorkType,
    WorkViolation,
    diagnostic_scope,
    ordered_custody_requests,
    provider_meter_scope,
    record_diagnostic,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._autonomous_activity_contract import autonomous_schema_for_context
from ._autonomy_decision import should_consider_autonomy
from ._candidate_application import model_response_candidate
from ._context_schema import bind_context_schema
from ._creator_cognitive_act_contract import (
    CODEX_RESULT_ACT_INSTRUCTIONS,
    CREATOR_COGNITIVE_ACT_INSTRUCTIONS,
    CREATOR_COGNITIVE_ACT_VERSION,
    CREATOR_VOICE_ACT_INSTRUCTIONS,
    LIFE_RESULT_ACT_INSTRUCTIONS,
    creator_cognitive_act_schema,
    creator_voice_act_schema,
)
from ._model_contract import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    GENERIC_COGNITION_INSTRUCTIONS,
    MEMORY_MAINTENANCE_INSTRUCTIONS,
    SLEEP_DECISION_INSTRUCTIONS,
    SUBJECT_SELF_CHECK_INSTRUCTIONS,
    VISUAL_OBSERVATION_CANDIDATE_VERSION,
    VISUAL_OBSERVATION_INSTRUCTIONS,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    load_voice_binding,
    parse_candidate,
)
from ._model_postgresql import ModelEpisodeSnapshot, PostgreSQLCognitiveModelRepository
from ._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
)
from ._reflection_contract import (
    REFLECT_FOCUS_INSTRUCTIONS,
    REFLECT_PROMPT_INSTRUCTIONS,
    REFLECT_SELF_INSTRUCTIONS,
    owner_reflection_schema,
)
from .api import (
    CognitionArtifactCatalogPort,
    CognitionFinalizationPort,
    CognitionModelAdapterFactory,
    CognitionModelPort,
    CognitionSchemaDocument,
    CognitionWakeupPort,
)

_WORK_KIND = WorkType.COGNITION_EXECUTE
COGNITION_EXECUTE = _WORK_KIND
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
_MAX_FORMAT_ATTEMPTS = 5
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


def _text_structure_error(
    binding: ModelBinding,
    snapshot: ModelEpisodeSnapshot,
    result: ModelInvocationResult,
) -> str | None:
    """Generation gate only; owner preparation and state validation run once later."""
    if binding.provider not in {"qwen", "deepseek"} or result.response_error_code:
        return None
    try:
        value = model_response_candidate(
            cast(bytes, result.response_bytes),
            expected_version=binding.response_contract_kind,
        )
        parse_candidate(
            value,
            expected_version=binding.response_contract_kind,
            purpose=snapshot.purpose,
            allowed_context_refs=frozenset(
                str(item["ref"]) for item in snapshot.included_context_refs
            ),
        )
    except CandidateViolation:
        return "MODEL-RESPONSE-SCHEMA"
    except ModelViolation as error:
        if error.code == "MODEL-RESPONSE-SCHEMA":
            return error.code
        # Semantic/reference or owner failures are not a regeneration budget.
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
        "_adapter_factory",
        "_adapter_schemas",
        "_adapters",
        "_autonomous_binding",
        "_catalog",
        "_custody",
        "_diagnostic",
        "_factory",
        "_failure_notification",
        "_finalization",
        "_lease_owner",
        "_prices",
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
        context: ContextCognitionReadPort,
        opportunities: OpportunityCognitionSelectionPort,
        work: DurableWorkPort,
        custody: ExecutionCustodyPort,
        finalization: CognitionFinalizationPort,
        adapter_factory: CognitionModelAdapterFactory,
        binding_path: Path,
        prices: PriceCatalog,
        wakeups: CognitionWakeupPort | None = None,
        diagnostic: Diagnostic | None = None,
        failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
    ) -> None:
        self._prices = prices
        load_active_binding(
            binding_path,
        )
        creator_input_binding = load_purpose_binding(
            "consider_creator_input",
            binding_path,
        )
        creator_voice_binding = load_voice_binding(binding_path)
        life_result_binding = load_purpose_binding(
            "consider_life_query_result",
            binding_path,
        )
        other_human_binding = load_purpose_binding(
            "consider_other_human_input",
            binding_path,
        )
        autonomous_binding = load_purpose_binding(
            "consider_autonomous_life",
            binding_path,
        )
        self._adapter_factory = adapter_factory
        self._autonomous_binding = autonomous_binding
        sleep_binding = load_purpose_binding(
            "consider_sleep",
            binding_path,
        )
        memory_maintenance_binding = load_purpose_binding(
            "maintain_subjective_memory",
            binding_path,
        )
        self_check_binding = load_purpose_binding(
            "perform_subject_self_check",
            binding_path,
        )
        visual_observation_binding = load_purpose_binding(
            "consider_visual_observation",
            binding_path,
        )
        reflect_self_binding = load_purpose_binding("reflect_self", binding_path)
        reflect_focus_binding = load_purpose_binding("reflect_focus", binding_path)
        reflect_prompt_binding = load_purpose_binding("reflect_prompt", binding_path)
        codex_task_binding = load_purpose_binding(
            "consider_codex_task",
            binding_path,
        )
        codex_result_binding = load_purpose_binding(
            "consider_codex_result",
            binding_path,
        )

        self._adapter_schemas: dict[str, tuple[dict[str, Any], str, str]] = {}

        def build_adapter(
            *,
            binding: ModelBinding,
            candidate_schema: dict[str, Any],
            instructions: str = GENERIC_COGNITION_INSTRUCTIONS,
            schema_name: str = "armi_cognition_candidate_v12",
        ) -> CognitionModelPort:
            self._adapter_schemas[binding.profile] = (
                candidate_schema,
                instructions,
                schema_name,
            )
            return adapter_factory(
                binding=binding,
                candidate_schema=CognitionSchemaDocument(
                    rfc8785.dumps(cast(Any, candidate_schema))
                ),
                instructions=instructions,
                schema_name=schema_name,
            )

        self._finalization = finalization
        self._factory = factory
        self._failure_notification = failure_notification
        self._storage = storage
        self._adapters = {
            "consider_creator_input": build_adapter(
                binding=creator_input_binding,
                candidate_schema=creator_cognitive_act_schema(),
                instructions=CREATOR_COGNITIVE_ACT_INSTRUCTIONS,
                schema_name="armi_creator_cognitive_act_candidate_v1",
            ),
            "consider_creator_voice_input": build_adapter(
                binding=creator_voice_binding,
                candidate_schema=creator_voice_act_schema(),
                instructions=CREATOR_VOICE_ACT_INSTRUCTIONS,
                schema_name="armi_creator_voice_act_candidate_v1",
            ),
            "consider_life_query_result": build_adapter(
                binding=life_result_binding,
                candidate_schema=creator_cognitive_act_schema(),
                instructions=LIFE_RESULT_ACT_INSTRUCTIONS,
                schema_name="armi_creator_cognitive_act_candidate_v1",
            ),
            "consider_visual_observation": build_adapter(
                binding=visual_observation_binding,
                candidate_schema=candidate_schema(VISUAL_OBSERVATION_CANDIDATE_VERSION),
                instructions=VISUAL_OBSERVATION_INSTRUCTIONS,
                schema_name="armi_visual_observation_candidate_v1",
            ),
            "consider_codex_task": build_adapter(
                binding=codex_task_binding,
                candidate_schema=candidate_schema(
                    codex_task_binding.response_contract_kind
                ),
            ),
            "consider_codex_result": build_adapter(
                binding=codex_result_binding,
                candidate_schema=creator_cognitive_act_schema(),
                instructions=CODEX_RESULT_ACT_INSTRUCTIONS,
                schema_name="armi_creator_cognitive_act_candidate_v8",
            ),
            "consider_other_human_input": build_adapter(
                binding=other_human_binding,
                candidate_schema=candidate_schema(
                    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
                ),
                instructions=OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
                schema_name="armi_other_human_dialogue_candidate_v1",
            ),
            "consider_sleep": build_adapter(
                binding=sleep_binding,
                candidate_schema=candidate_schema(sleep_binding.response_contract_kind),
                instructions=SLEEP_DECISION_INSTRUCTIONS,
                schema_name="armi_sleep_decision_candidate_v1",
            ),
            "maintain_subjective_memory": build_adapter(
                binding=memory_maintenance_binding,
                candidate_schema=candidate_schema(
                    memory_maintenance_binding.response_contract_kind,
                    purpose="maintain_subjective_memory",
                ),
                instructions=MEMORY_MAINTENANCE_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "perform_subject_self_check": build_adapter(
                binding=self_check_binding,
                candidate_schema=candidate_schema(
                    self_check_binding.response_contract_kind,
                    purpose="perform_subject_self_check",
                ),
                instructions=SUBJECT_SELF_CHECK_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "reflect_self": build_adapter(
                binding=reflect_self_binding,
                candidate_schema=owner_reflection_schema(target="self"),
                instructions=REFLECT_SELF_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
            "reflect_focus": build_adapter(
                binding=reflect_focus_binding,
                candidate_schema=owner_reflection_schema(target="focus"),
                instructions=REFLECT_FOCUS_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
            "reflect_prompt": build_adapter(
                binding=reflect_prompt_binding,
                candidate_schema=owner_reflection_schema(target="prompt"),
                instructions=REFLECT_PROMPT_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
        }
        self._catalog = catalog
        self._custody = custody
        self._repository = PostgreSQLCognitiveModelRepository(
            context,
            catalog,
            opportunities,
        )
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
        record = records[0]
        with diagnostic_scope(
            work_id=record.draft.work_id.value,
            trace_id=record.draft.trace_id.value,
            episode_id=record.draft.owner.reference,
        ):
            record_diagnostic(
                "cognition.execution.started",
                component="cognition",
                attempt=record.attempt_count,
            )
            await self._execute_with_renewal(record)
            record_diagnostic("cognition.execution.returned", component="cognition")
        return True

    async def _execute(self, record: WorkRecord) -> None:
        lease = cast(WorkLease, record.lease)
        response_saved = False
        snapshot: ModelEpisodeSnapshot | None = None
        custody_context = None
        custody_held = False
        try:
            if record.attempt_count > 1:
                async with self._factory.unit_of_work() as unit_of_work:
                    if await self._repository.end_abandoned_finalization(
                        unit_of_work, record
                    ):
                        return
            snapshot = await self._snapshot(record)
            custody_requests = [
                ExecutionCustodyRequest(
                    ExecutionCustodyScope(
                        ExecutionCustodyScopeKind.RUNTIME_AUTHORITY,
                        self._factory.environment_id,
                    ),
                    ExecutionCustodyMode.SHARED,
                )
            ]
            if snapshot.context_party_id is not None:
                custody_requests.append(
                    ExecutionCustodyRequest(
                        ExecutionCustodyScope(
                            ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY,
                            snapshot.context_party_id,
                        ),
                        ExecutionCustodyMode.SHARED,
                    )
                )
            if (
                snapshot.purpose
                in {"consider_autonomous_life", "consider_autonomy_check"}
                and snapshot.scene_id is not None
            ):
                custody_requests.append(
                    ExecutionCustodyRequest(
                        ExecutionCustodyScope(
                            ExecutionCustodyScopeKind.OUTREACH_SCENE,
                            snapshot.scene_id,
                        ),
                        ExecutionCustodyMode.SHARED,
                    )
                )
            custody_context = self._custody.hold(
                ordered_custody_requests(*custody_requests),
                deadline_at=record.draft.deadline_at,
            )
            await custody_context.__aenter__()
            custody_held = True
            # The first snapshot only identifies custody scopes.  Re-read under
            # custody so a Data Rights or Runtime exclusive holder cannot leave
            # this worker with a stale lease before file/provider I/O begins.
            snapshot = await self._snapshot(record)
            context_bytes = await self._read_context(snapshot)
            if snapshot.purpose == "consider_autonomy_check":
                engage = should_consider_autonomy(context_bytes)
                async with self._factory.unit_of_work() as unit_of_work:
                    await self._repository.finalize_autonomy_check(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        engage=engage,
                    )
                return
            adapter = self._adapter_for(
                snapshot.purpose, context_bytes, snapshot.included_context_refs
            )
            request_bytes = build_request_bytes(
                binding=adapter.binding,
                compiled_context=context_bytes,
                context_digest=snapshot.context_digest,
                base_subject_version=snapshot.base_subject_version,
                base_state_epoch=snapshot.base_state_epoch,
                bundle_activation_id=snapshot.bundle_activation_id,
                included_context_refs=snapshot.included_context_refs,
            )
            async with self._factory.unit_of_work() as unit_of_work:
                attempt_id = await self._repository.prepare_attempt(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    binding=adapter.binding,
                    request_artifact=None,
                )
            if attempt_id is None:
                self._diagnostic("model.outcome_unknown")
                return
            self._diagnostic("cognition.model.attempt.prepared")
            bound_attempt = attempt_id

            async def save_usage(receipt: ProviderCallReceipt) -> None:
                try:
                    async with self._factory.provider_usage_unit_of_work(
                        receipt=receipt
                    ) as usage_uow:
                        await self._repository.record_provider_call(
                            usage_uow,
                            attempt_id=bound_attempt,
                            receipt=receipt,
                        )
                except RuntimeTransactionFailure as error:
                    if error.code.startswith("LIFE-AUTONOMY-"):
                        raise ModelViolation(
                            "MODEL-" + error.code.removeprefix("LIFE-")
                        ) from None
                    raise

            usage_scope = ProviderMeterScope(save_usage, self._prices, snapshot.purpose)
            with (
                provider_meter_scope(usage_scope),
                diagnostic_scope(attempt_id=attempt_id),
            ):
                input_tokens = await self._tokenize(adapter, request_bytes, record)
            request = checked_model_request(
                prices=self._prices,
                binding=adapter.binding,
                request_bytes=request_bytes,
                context_digest=snapshot.context_digest,
                input_tokens=input_tokens,
            )
            published_request = await self._publish(
                adapter.request_evidence(request),
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
                await self._repository.attach_request(
                    unit_of_work,
                    lease=lease,
                    episode_id=snapshot.episode_id,
                    attempt_id=attempt_id,
                    request_artifact=request_registration.ref,
                )
            # DESIGN.md: only completed text with invalid candidate structure may
            # regenerate. Keep the frozen request, lease and one final commit.
            for generation in range(1, _MAX_FORMAT_ATTEMPTS + 1):
                if self._stop.is_set():
                    return
                async with self._factory.unit_of_work() as unit_of_work:
                    await self._repository.mark_dispatched(
                        unit_of_work,
                        lease=lease,
                        attempt_id=attempt_id,
                        episode_id=snapshot.episode_id,
                    )
                with (
                    provider_meter_scope(usage_scope),
                    diagnostic_scope(attempt_id=attempt_id),
                ):
                    record_diagnostic(
                        "cognition.model.request.started",
                        component="cognition",
                        generation=generation,
                    )
                    result = await adapter.invoke(request)
                if result.status is not ModelResultStatus.SUCCEEDED:
                    await self._settle_failure(
                        lease=lease,
                        snapshot=snapshot,
                        attempt_id=attempt_id,
                        result=result,
                    )
                    return
                structure_error = _text_structure_error(
                    adapter.binding, snapshot, result
                )
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
                        result=(
                            replace(result, response_error_code=structure_error)
                            if structure_error is not None
                            else result
                        ),
                    )
                    retry_structure = (
                        structure_error is not None
                        and generation < _MAX_FORMAT_ATTEMPTS
                    )
                    if not retry_structure:
                        await self._repository.finalize_primary_success(
                            unit_of_work,
                            lease=lease,
                            snapshot=snapshot,
                            attempt_id=attempt_id,
                            response_artifact=response_registration.ref,
                        )
                self._diagnostic("cognition.model.attempt.settled")
                if structure_error is not None:
                    record_diagnostic(
                        "cognition.model.response.rejected",
                        component="cognition",
                        level=30,
                        attempt_id=attempt_id,
                        generation=generation,
                        result_code=structure_error,
                    )
                    self._diagnostic("cognition.model.response.format_rejected")
                response_saved = True
                if self._stop.is_set():
                    return
                if retry_structure:
                    self._diagnostic("model.response.structure.retry")
                    async with self._factory.unit_of_work() as unit_of_work:
                        attempt_id = await self._repository.prepare_attempt(
                            unit_of_work,
                            lease=lease,
                            snapshot=snapshot,
                            binding=adapter.binding,
                            request_artifact=request_registration.ref,
                        )
                    if attempt_id is None:
                        return
                    self._diagnostic("cognition.model.attempt.prepared")
                    bound_attempt = attempt_id
                    response_saved = False
                    continue
                if result.response_error_code is not None:
                    await self._fail_finalization(
                        lease, snapshot, result.response_error_code
                    )
                    return
                await self._finalization.finalize(
                    record, attempt_id, cast(bytes, result.response_bytes)
                )
                return
            return
        except (CandidateViolation, SubjectCommitViolation) as error:
            if snapshot is None:
                raise
            await self._fail_finalization(lease, snapshot, error.code)
            return
        except ModelViolation as error:
            if response_saved and snapshot is not None:
                await self._fail_finalization(lease, snapshot, error.code)
                return
            if error.code == "MODEL-WORK-STALE":
                self._diagnostic("model.work.stale")
                return
            current_snapshot = locals().get("snapshot")
            attempt = locals().get("attempt_id")
            if isinstance(attempt, ModelAttemptId) and isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    attempt_id=attempt,
                    result=_error_result(error),
                )
                return
            await self._settle_before_attempt(
                record, lease, locals().get("snapshot"), error
            )
            return
        except ArtifactViolation:
            if response_saved and snapshot is not None:
                await self._fail_finalization(lease, snapshot, "MODEL-ARTIFACT")
                return
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
                    record,
                    lease,
                    current_snapshot,
                    error,
                )
            return
        except RuntimeTransactionFailure as error:
            if response_saved and snapshot is not None:
                await self._fail_finalization(lease, snapshot, error.code)
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
            return
        except WorkViolation as error:
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
            return
        except ExecutionCustodyViolation:
            self._diagnostic("model.worker.custody_unavailable")
            return
        finally:
            if custody_context is not None and custody_held:
                await custody_context.__aexit__(None, None, None)

    async def run_worker(self) -> None:
        observed = self._wakeups.version(COGNITION_EXECUTE)
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
                COGNITION_EXECUTE,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def _tokenize(
        self, adapter: CognitionModelPort, request_bytes: bytes, record: WorkRecord
    ) -> int:
        # DESIGN §6: retry only tokenization within this live lease and its
        # remaining work budget; a prepared usage record is not model dispatch.
        remaining = record.draft.max_attempts - record.attempt_count
        while True:
            if self._stop.is_set():
                raise asyncio.CancelledError
            try:
                return await adapter.tokenize(request_bytes)
            except ModelViolation as error:
                if not error.retryable or remaining <= 0:
                    raise
                remaining -= 1
                safe_code = error.code.lower().replace("-", "_")
                self._diagnostic(f"model.tokenization.retry.{safe_code}")
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _snapshot(self, work: WorkRecord) -> ModelEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.snapshot(unit_of_work, work)
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

    async def _fail_finalization(
        self, lease: WorkLease, snapshot: ModelEpisodeSnapshot, code: str
    ) -> None:
        async with self._factory.unit_of_work() as unit_of_work:
            await self._repository.fail_episode(
                unit_of_work, lease=lease, snapshot=snapshot, code=code
            )
        if self._failure_notification is not None and not self._stop.is_set():
            await self._failure_notification(snapshot.episode_id, code)

    async def _execute_with_renewal(self, record: WorkRecord) -> None:
        lease = cast(WorkLease, record.lease)
        task = asyncio.create_task(
            self._execute(record), name=f"cognition-{lease.attempt_id}"
        )
        stopped = asyncio.create_task(self._stop.wait())
        channel = "cognition.context.prepare"
        observed = self._wakeups.version(channel)
        changed: asyncio.Task[int] | None = None
        try:
            while True:
                changed = asyncio.create_task(
                    self._wakeups.wait(
                        channel,
                        observed,
                        stop=self._stop,
                        timeout_seconds=_RENEW_SECONDS,
                    )
                )
                done, _ = await asyncio.wait(
                    {task, stopped, changed},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stopped in done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return
                if task in done:
                    await task
                    return
                observed = await changed
                try:
                    lease = await self._work.renew(lease, lease_seconds=_LEASE_SECONDS)
                except WorkViolation:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self._diagnostic("cognition.work.stale")
                    return
        finally:
            if changed is not None:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
            stopped.cancel()
            task.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)

    def _adapter_for(
        self, purpose: str, context_bytes: bytes, refs: tuple[dict[str, object], ...]
    ) -> CognitionModelPort:
        if purpose == "consider_autonomous_life":
            return self._adapter_factory(
                binding=self._autonomous_binding,
                candidate_schema=CognitionSchemaDocument(
                    rfc8785.dumps(
                        bind_context_schema(
                            autonomous_schema_for_context(context_bytes), refs
                        )
                    )
                ),
                instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
                schema_name="armi_autonomous_activity_candidate_v12",
            )
        try:
            adapter = self._adapters[purpose]
        except KeyError:
            raise ModelViolation("MODEL-BINDING") from None
        if (
            purpose
            in {
                "consider_creator_input",
                "consider_life_query_result",
                "consider_codex_result",
            }
            and adapter.binding.response_contract_kind != CREATOR_COGNITIVE_ACT_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_creator_voice_input"
            and adapter.binding.response_contract_kind
            != "armi.creator-voice-act-candidate"
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_other_human_input"
            and adapter.binding.response_contract_kind
            != OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        schema, instructions, name = self._adapter_schemas[adapter.binding.profile]
        return self._adapter_factory(
            binding=adapter.binding,
            candidate_schema=CognitionSchemaDocument(
                rfc8785.dumps(bind_context_schema(schema, refs))
            ),
            instructions=instructions,
            schema_name=name,
        )

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
            await self._repository.fail_episode(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                code=result.error_code or "MODEL-PROVIDER-FAILED",
            )
        self._diagnostic("cognition.model.attempt.failed")
        if self._failure_notification is not None and not self._stop.is_set():
            await self._failure_notification(
                snapshot.episode_id, result.error_code or "MODEL-PROVIDER-FAILED"
            )

    async def _settle_before_attempt(
        self,
        record: WorkRecord,
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
                if error.retryable and record.attempt_count < record.draft.max_attempts:
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
                    await self._repository.fail_episode(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        code=error.code,
                    )
        except RuntimeTransactionFailure, ModelViolation, WorkViolation:
            self._diagnostic("model.preparation.settlement_deferred")
            return
        if (
            not (error.retryable and record.attempt_count < record.draft.max_attempts)
            and self._failure_notification is not None
            and not self._stop.is_set()
        ):
            await self._failure_notification(snapshot.episode_id, error.code)


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
        ModelResultStatus.REJECTED
        if error.code.startswith("MODEL-AUTONOMY-")
        else ModelResultStatus.OUTCOME_UNKNOWN
        if error.outcome_unknown
        else ModelResultStatus.TIMED_OUT
        if error.code == "MODEL-REQUEST-TIMEOUT"
        else ModelResultStatus.PROVIDER_FAILED
    )
    return ModelInvocationResult(status, None, None, None, None, error.code)


__all__ = ("ModelPipeline",)
