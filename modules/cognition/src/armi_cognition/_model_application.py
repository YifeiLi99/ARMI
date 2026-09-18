"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
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
    ModelRequest,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    SubjectCommitViolation,
    WorkLease,
    WorkRecord,
    WorkType,
    WorkViolation,
    ordered_custody_requests,
    provider_meter_scope,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._autonomous_activity_contract import autonomous_schema_for_context
from ._context_schema import bind_context_schema
from ._creator_cognitive_act_contract import (
    CREATOR_COGNITIVE_ACT_INSTRUCTIONS,
    CREATOR_COGNITIVE_ACT_VERSION,
    CREATOR_VOICE_ACT_INSTRUCTIONS,
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
)
from ._model_postgresql import ModelEpisodeSnapshot, PostgreSQLCognitiveModelRepository
from ._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
)
from ._reflection_contract import (
    REFLECT_MIND_INSTRUCTIONS,
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
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class _Pulse:
    version: int
    event: asyncio.Event


class _DeterministicMoodReflectionAdapter:
    """Create a calculation request without asking a model for home-base values."""

    def __init__(self, binding: ModelBinding) -> None:
        self._binding = binding

    @property
    def binding(self) -> ModelBinding:
        return self._binding

    async def tokenize(self, canonical_request: bytes) -> int:
        return max(1, len(canonical_request) // 4)

    def request_evidence(self, request: ModelRequest) -> bytes:
        return (
            rfc8785.dumps(
                {
                    "schema_version": "armi.model-input-evidence.v1",
                    "execution": "deterministic",
                    "canonical_request": request.canonical_bytes.decode("utf-8"),
                    "provider_request": None,
                }
            )
            + b"\n"
        )

    async def invoke(self, request: ModelRequest) -> ModelInvocationResult:
        try:
            raw = cast(dict[str, object], json.loads(request.canonical_bytes))
            compiled = cast(dict[str, object], raw["compiled_context"])
            refs = cast(list[dict[str, object]], raw["included_context_refs"])
            mood_ref = next(
                str(item["ref"]) for item in refs if item["item_kind"] == "mood"
            )
            phase_ref = next(
                str(item["ref"])
                for item in refs
                if item["item_kind"] == "current_maintenance_phase"
            )
            mood_item = next(
                item
                for layer in cast(list[dict[str, object]], compiled["layers"])
                for item in cast(list[dict[str, object]], layer["items"])
                if item["item_kind"] == "mood"
            )
            source = cast(dict[str, object], mood_item["source"])
            version_value = source["version"]
            if not isinstance(version_value, int):
                raise ModelViolation("MODEL-CONTEXT")
            expected_version = version_value
            response = rfc8785.dumps(
                {
                    "kind": "update",
                    "target": "mood",
                    "summary": "按固定时间采样规则检查长期心情基线",
                    "basis_refs": [phase_ref, mood_ref],
                    "expected_version": expected_version,
                    "next_state": {},
                }
            )
        except KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError:
            raise ModelViolation("MODEL-CONTEXT") from None
        return ModelInvocationResult(
            ModelResultStatus.SUCCEEDED,
            "local-mood-reflection",
            self._binding.model_id,
            rfc8785.dumps(
                {
                    "schema_version": "armi.model-response-artifact.v3",
                    "provider_request_id": "local-mood-reflection",
                    "provider_model_id": self._binding.model_id,
                    "output_text": '{"candidate":' + response.decode("utf-8") + "}",
                    "usage": {
                        "input_tokens": max(1, len(request.canonical_bytes) // 4),
                        "output_tokens": 1,
                        "cached_input_tokens": 0,
                    },
                }
            ),
            ModelUsage(max(1, len(request.canonical_bytes) // 4), 1, 0),
        )


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
        web_search_active: bool = False,
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
        reflect_mind_binding = load_purpose_binding("reflect_mind", binding_path)
        reflect_mood_binding = load_purpose_binding("reflect_mood", binding_path)
        reflect_prompt_binding = load_purpose_binding("reflect_prompt", binding_path)
        web_evidence_binding = load_purpose_binding(
            "consider_web_evidence",
            binding_path,
        )
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
                candidate_schema=creator_cognitive_act_schema(
                    web_search=web_search_active
                ),
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
                candidate_schema=creator_cognitive_act_schema(
                    web_search=web_search_active
                ),
                instructions=CREATOR_COGNITIVE_ACT_INSTRUCTIONS,
                schema_name="armi_creator_cognitive_act_candidate_v1",
            ),
            "consider_web_evidence": build_adapter(
                binding=web_evidence_binding,
                candidate_schema=candidate_schema(
                    web_evidence_binding.response_contract_version
                ),
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
                    codex_task_binding.response_contract_version
                ),
            ),
            "consider_codex_result": build_adapter(
                binding=codex_result_binding,
                candidate_schema=candidate_schema(
                    codex_result_binding.response_contract_version
                ),
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
                candidate_schema=candidate_schema(
                    sleep_binding.response_contract_version
                ),
                instructions=SLEEP_DECISION_INSTRUCTIONS,
                schema_name="armi_sleep_decision_candidate_v1",
            ),
            "maintain_subjective_memory": build_adapter(
                binding=memory_maintenance_binding,
                candidate_schema=candidate_schema(
                    memory_maintenance_binding.response_contract_version,
                    purpose="maintain_subjective_memory",
                ),
                instructions=MEMORY_MAINTENANCE_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "perform_subject_self_check": build_adapter(
                binding=self_check_binding,
                candidate_schema=candidate_schema(
                    self_check_binding.response_contract_version,
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
            "reflect_mind": build_adapter(
                binding=reflect_mind_binding,
                candidate_schema=owner_reflection_schema(target="mind"),
                instructions=REFLECT_MIND_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
            "reflect_mood": _DeterministicMoodReflectionAdapter(reflect_mood_binding),
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
        await self._execute_with_renewal(records[0])
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
                snapshot.purpose == "consider_autonomous_life"
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
                budget_exclusions=snapshot.budget_exclusions,
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
            with provider_meter_scope(usage_scope):
                input_tokens = await adapter.tokenize(request_bytes)
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
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.mark_dispatched(
                    unit_of_work,
                    lease=lease,
                    attempt_id=attempt_id,
                    episode_id=snapshot.episode_id,
                )
            with provider_meter_scope(usage_scope):
                result = await adapter.invoke(request)
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
                    await self._repository.finalize_primary_success(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        attempt_id=attempt_id,
                        response_artifact=response_registration.ref,
                    )
                response_saved = True
                if self._stop.is_set():
                    return
                if result.response_error_code is not None:
                    await self._fail_finalization(
                        lease, snapshot, result.response_error_code
                    )
                    return
                await self._finalization.finalize(
                    record, attempt_id, cast(bytes, result.response_bytes)
                )
            else:
                await self._settle_failure(
                    lease=lease,
                    snapshot=snapshot,
                    attempt_id=attempt_id,
                    result=result,
                )
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
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task, stopped},
                    timeout=_RENEW_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if task in done:
                    await task
                    return
                if stopped in done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return
                try:
                    lease = await self._work.renew(lease, lease_seconds=_LEASE_SECONDS)
                except WorkViolation:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self._diagnostic("cognition.work.stale")
                    return
        finally:
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
                schema_name="armi_autonomous_activity_candidate_v9",
            )
        try:
            adapter = self._adapters[purpose]
        except KeyError:
            raise ModelViolation("MODEL-BINDING") from None
        if (
            purpose in {"consider_creator_input", "consider_life_query_result"}
            and adapter.binding.response_contract_version
            != CREATOR_COGNITIVE_ACT_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_creator_voice_input"
            and adapter.binding.response_contract_version
            != "armi.creator-voice-act-candidate.v7"
        ):
            raise ModelViolation("MODEL-BINDING")
        if (
            purpose == "consider_other_human_input"
            and adapter.binding.response_contract_version
            != OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
        ):
            raise ModelViolation("MODEL-BINDING")
        if purpose == "reflect_mood":
            return adapter
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
