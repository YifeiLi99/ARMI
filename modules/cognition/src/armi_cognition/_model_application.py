"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

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
    DurableWorkPort,
    ModelAttemptId,
    ModelBinding,
    ModelInvocationResult,
    ModelRequest,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
    WorkLease,
    WorkRecord,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._creator_branch_contract import (
    CREATOR_APPRAISAL_INSTRUCTIONS,
    CREATOR_DIALOGUE_AGGREGATE_VERSION,
    CREATOR_RESPONSE_INSTRUCTIONS,
    CreatorAppraisalCandidate,
    CreatorDialogueAggregate,
    CreatorResponseCandidate,
    creator_appraisal_schema,
    creator_response_schema,
    parse_creator_appraisal,
    parse_creator_response,
)
from ._model_contract import (
    ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    ACTIVITY_ATTENTION_INSTRUCTIONS,
    ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
    ACTIVITY_INTERNAL_WORK_INSTRUCTIONS,
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    CREATOR_OUTREACH_INSTRUCTIONS,
    DIALOGUE_CANDIDATE_VERSION,
    MAINTENANCE_WORK_CANDIDATE_VERSION,
    MEMORY_MAINTENANCE_INSTRUCTIONS,
    SLEEP_DECISION_CANDIDATE_VERSION,
    SLEEP_DECISION_INSTRUCTIONS,
    SUBJECT_SELF_CHECK_INSTRUCTIONS,
    VISUAL_OBSERVATION_CANDIDATE_VERSION,
    VISUAL_OBSERVATION_INSTRUCTIONS,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    parse_candidate,
)
from ._model_postgresql import (
    ModelBranchSnapshot,
    ModelEpisodeSnapshot,
    PostgreSQLCognitiveModelRepository,
)
from ._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
    parse_other_human_dialogue_candidate,
)
from ._reflection_contract import (
    REFLECT_MIND_INSTRUCTIONS,
    REFLECT_PROMPT_INSTRUCTIONS,
    REFLECT_SELF_INSTRUCTIONS,
    owner_reflection_schema,
    parse_owner_reflection,
)
from .api import (
    CognitionArtifactCatalogPort,
    CognitionCandidateParser,
    CognitionModelAdapterFactory,
    CognitionModelPort,
    CognitionSchemaDocument,
    CognitionWakeupPort,
    CognitiveBranchRole,
)

_WORK_KIND = "cognition.model.invoke"
MODEL_INVOKE = _WORK_KIND
CANDIDATE_VALIDATE = "cognition.candidate.validate"
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
_APPRAISAL_GRACE_SECONDS = 10.0
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class _Pulse:
    version: int
    event: asyncio.Event


@dataclass(frozen=True, slots=True)
class _BranchCall:
    branch: ModelBranchSnapshot
    adapter: CognitionModelPort
    request: ModelRequest
    attempt_id: ModelAttemptId


class _DeterministicMoodReflectionAdapter:
    """Create a calculation request without asking a model for home-base values."""

    def __init__(self, binding: ModelBinding) -> None:
        self._binding = binding

    @property
    def binding(self) -> ModelBinding:
        return self._binding

    async def tokenize(self, canonical_request: bytes) -> int:
        return max(1, len(canonical_request) // 4)

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
            response,
            ModelUsage(max(1, len(request.canonical_bytes) // 4), 1, 0, 0),
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
        "_adapters",
        "_branch_adapters",
        "_catalog",
        "_diagnostic",
        "_dialogue_version",
        "_factory",
        "_late_tasks",
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
        context: ContextCognitionReadPort,
        opportunities: OpportunityCognitionSelectionPort,
        work: DurableWorkPort,
        adapter_factory: CognitionModelAdapterFactory,
        binding_path: Path,
        web_search_active: bool = False,
        wakeups: CognitionWakeupPort | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        dialogue_version = DIALOGUE_CANDIDATE_VERSION
        load_active_binding(
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        creator_response_binding = load_purpose_binding(
            "consider_creator_response",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        creator_appraisal_binding = load_purpose_binding(
            "appraise_creator_input",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        life_response_binding = load_purpose_binding(
            "consider_life_query_response",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        life_appraisal_binding = load_purpose_binding(
            "appraise_life_query_result",
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
        visual_observation_binding = load_purpose_binding(
            "consider_visual_observation",
            binding_path,
            expected_dialogue_version=dialogue_version,
        )
        reflect_self_binding = load_purpose_binding(
            "reflect_self", binding_path, expected_dialogue_version=dialogue_version
        )
        reflect_mind_binding = load_purpose_binding(
            "reflect_mind", binding_path, expected_dialogue_version=dialogue_version
        )
        reflect_mood_binding = load_purpose_binding(
            "reflect_mood", binding_path, expected_dialogue_version=dialogue_version
        )
        reflect_prompt_binding = load_purpose_binding(
            "reflect_prompt", binding_path, expected_dialogue_version=dialogue_version
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

        def parse_response_branch(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ) -> CreatorResponseCandidate:
            del allowed_context_refs
            try:
                candidate = parse_creator_response(json.loads(value))
                if candidate.kind == "web_research" and not web_search_active:
                    raise ValueError("web research is unavailable")
                return candidate
            except json.JSONDecodeError, UnicodeDecodeError, ValueError:
                raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None

        def parse_appraisal_branch(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ) -> CreatorAppraisalCandidate:
            try:
                return parse_creator_appraisal(
                    json.loads(value),
                    allowed_context_refs=allowed_context_refs,
                )
            except json.JSONDecodeError, UnicodeDecodeError, ValueError:
                raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None

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

        def parse_visual_observation(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            return parse_candidate(
                value,
                allowed_context_refs=allowed_context_refs,
                expected_version=VISUAL_OBSERVATION_CANDIDATE_VERSION,
            )

        def parse_reflection(
            value: bytes,
            *,
            allowed_context_refs: frozenset[str],
        ):
            try:
                return parse_owner_reflection(
                    json.loads(value),
                    allowed_context_refs=allowed_context_refs,
                )
            except json.JSONDecodeError, UnicodeDecodeError, ValueError:
                raise ModelViolation("MODEL-RESPONSE-SCHEMA") from None

        def build_adapter(
            *,
            binding: ModelBinding,
            candidate_schema: dict[str, Any],
            candidate_parser: CognitionCandidateParser,
            instructions: str | None = None,
            schema_name: str | None = None,
        ) -> CognitionModelPort:
            return adapter_factory(
                binding=binding,
                candidate_schema=CognitionSchemaDocument(
                    rfc8785.dumps(cast(Any, candidate_schema))
                ),
                candidate_parser=candidate_parser,
                instructions=instructions,
                schema_name=schema_name,
            )

        self._factory = factory
        self._storage = storage
        self._adapters = {
            "consider_web_evidence": build_adapter(
                binding=web_evidence_binding,
                candidate_schema=candidate_schema(
                    web_evidence_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_visual_observation": build_adapter(
                binding=visual_observation_binding,
                candidate_schema=candidate_schema(VISUAL_OBSERVATION_CANDIDATE_VERSION),
                candidate_parser=parse_visual_observation,
                instructions=VISUAL_OBSERVATION_INSTRUCTIONS,
                schema_name="armi_visual_observation_candidate_v1",
            ),
            "consider_codex_task": build_adapter(
                binding=codex_task_binding,
                candidate_schema=candidate_schema(
                    codex_task_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_codex_result": build_adapter(
                binding=codex_result_binding,
                candidate_schema=candidate_schema(
                    codex_result_binding.response_contract_version
                ),
                candidate_parser=parse_candidate,
            ),
            "consider_creator_outreach": build_adapter(
                binding=outreach_binding,
                candidate_schema=candidate_schema(DIALOGUE_CANDIDATE_VERSION),
                candidate_parser=parse_outreach,
                instructions=CREATOR_OUTREACH_INSTRUCTIONS,
                schema_name="armi_creator_outreach_candidate_v1",
            ),
            "consider_other_human_input": build_adapter(
                binding=other_human_binding,
                candidate_schema=candidate_schema(
                    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
                ),
                candidate_parser=parse_other_human,
                instructions=OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
                schema_name="armi_other_human_dialogue_candidate_v1",
            ),
            "consider_autonomous_life": build_adapter(
                binding=autonomous_binding,
                candidate_schema=candidate_schema(
                    autonomous_binding.response_contract_version
                ),
                candidate_parser=parse_autonomous,
                instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
                schema_name="armi_autonomous_activity_candidate_v1",
            ),
            "consider_activity_attention": build_adapter(
                binding=attention_binding,
                candidate_schema=candidate_schema(
                    attention_binding.response_contract_version
                ),
                candidate_parser=parse_attention,
                instructions=ACTIVITY_ATTENTION_INSTRUCTIONS,
                schema_name="armi_activity_attention_candidate_v2",
            ),
            "consider_activity_internal_work": build_adapter(
                binding=internal_work_binding,
                candidate_schema=candidate_schema(
                    internal_work_binding.response_contract_version
                ),
                candidate_parser=parse_internal_work,
                instructions=ACTIVITY_INTERNAL_WORK_INSTRUCTIONS,
                schema_name="armi_activity_internal_work_candidate_v1",
            ),
            "consider_sleep": build_adapter(
                binding=sleep_binding,
                candidate_schema=candidate_schema(
                    sleep_binding.response_contract_version
                ),
                candidate_parser=parse_sleep,
                instructions=SLEEP_DECISION_INSTRUCTIONS,
                schema_name="armi_sleep_decision_candidate_v1",
            ),
            "maintain_subjective_memory": build_adapter(
                binding=memory_maintenance_binding,
                candidate_schema=candidate_schema(
                    memory_maintenance_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=MEMORY_MAINTENANCE_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "perform_subject_self_check": build_adapter(
                binding=self_check_binding,
                candidate_schema=candidate_schema(
                    self_check_binding.response_contract_version
                ),
                candidate_parser=parse_maintenance_work,
                instructions=SUBJECT_SELF_CHECK_INSTRUCTIONS,
                schema_name="armi_maintenance_work_candidate_v1",
            ),
            "reflect_self": build_adapter(
                binding=reflect_self_binding,
                candidate_schema=owner_reflection_schema(),
                candidate_parser=parse_reflection,
                instructions=REFLECT_SELF_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
            "reflect_mind": build_adapter(
                binding=reflect_mind_binding,
                candidate_schema=owner_reflection_schema(),
                candidate_parser=parse_reflection,
                instructions=REFLECT_MIND_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
            "reflect_mood": _DeterministicMoodReflectionAdapter(reflect_mood_binding),
            "reflect_prompt": build_adapter(
                binding=reflect_prompt_binding,
                candidate_schema=owner_reflection_schema(),
                candidate_parser=parse_reflection,
                instructions=REFLECT_PROMPT_INSTRUCTIONS,
                schema_name="armi_owner_reflection_candidate_v1",
            ),
        }
        self._branch_adapters = {
            (
                "consider_creator_input",
                CognitiveBranchRole.RESPONSE_ACTION.value,
            ): build_adapter(
                binding=creator_response_binding,
                candidate_schema=creator_response_schema(web_search=web_search_active),
                candidate_parser=parse_response_branch,
                instructions=CREATOR_RESPONSE_INSTRUCTIONS,
                schema_name="armi_creator_response_candidate_v1",
            ),
            (
                "consider_creator_input",
                CognitiveBranchRole.EPISODE_APPRAISAL.value,
            ): build_adapter(
                binding=creator_appraisal_binding,
                candidate_schema=creator_appraisal_schema(),
                candidate_parser=parse_appraisal_branch,
                instructions=CREATOR_APPRAISAL_INSTRUCTIONS,
                schema_name="armi_creator_appraisal_candidate_v1",
            ),
            (
                "consider_creator_voice_appraisal",
                CognitiveBranchRole.EPISODE_APPRAISAL.value,
            ): build_adapter(
                binding=creator_appraisal_binding,
                candidate_schema=creator_appraisal_schema(),
                candidate_parser=parse_appraisal_branch,
                instructions=CREATOR_APPRAISAL_INSTRUCTIONS,
                schema_name="armi_creator_appraisal_candidate_v1",
            ),
            (
                "consider_life_query_result",
                CognitiveBranchRole.RESPONSE_ACTION.value,
            ): build_adapter(
                binding=life_response_binding,
                candidate_schema=creator_response_schema(web_search=web_search_active),
                candidate_parser=parse_response_branch,
                instructions=CREATOR_RESPONSE_INSTRUCTIONS,
                schema_name="armi_creator_response_candidate_v1",
            ),
            (
                "consider_life_query_result",
                CognitiveBranchRole.EPISODE_APPRAISAL.value,
            ): build_adapter(
                binding=life_appraisal_binding,
                candidate_schema=creator_appraisal_schema(),
                candidate_parser=parse_appraisal_branch,
                instructions=CREATOR_APPRAISAL_INSTRUCTIONS,
                schema_name="armi_creator_appraisal_candidate_v1",
            ),
        }
        self._catalog = catalog
        self._repository = PostgreSQLCognitiveModelRepository(
            context,
            catalog,
            opportunities,
        )
        self._work = work
        self._late_tasks: set[asyncio.Task[None]] = set()
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
        late_tasks = tuple(self._late_tasks)
        for task in late_tasks:
            task.cancel()
        if late_tasks:
            await asyncio.gather(*late_tasks, return_exceptions=True)

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
        lease = cast(WorkLease, record.lease)
        branch: ModelBranchSnapshot | None = None
        try:
            snapshot = await self._snapshot(record)
            if snapshot.purpose in {
                "consider_creator_input",
                "consider_creator_voice_appraisal",
                "consider_life_query_result",
            }:
                await self._invoke_dialogue_branches(record, lease, snapshot)
                return True
            branch = _branch(snapshot, CognitiveBranchRole.PRIMARY.value)
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
                    branch=branch,
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
                        branch=branch,
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
                self._wakeups.notify(CANDIDATE_VALIDATE)
            else:
                await self._settle_failure(
                    lease=lease,
                    snapshot=snapshot,
                    branch=branch,
                    attempt_id=attempt_id,
                    result=result,
                )
            return True
        except ModelViolation as error:
            if error.code == "MODEL-WORK-STALE":
                self._diagnostic("model.work.stale")
                return True
            current_snapshot = locals().get("snapshot")
            if isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ) and current_snapshot.purpose in {
                "consider_creator_input",
                "consider_creator_voice_appraisal",
                "consider_life_query_result",
            }:
                async with self._factory.unit_of_work() as unit_of_work:
                    await self._repository.abandon_hot_episode(
                        unit_of_work,
                        lease=lease,
                        snapshot=current_snapshot,
                        code=error.code,
                    )
                return True
            attempt = locals().get("attempt_id")
            if (
                isinstance(attempt, ModelAttemptId)
                and isinstance(current_snapshot, ModelEpisodeSnapshot)
                and branch is not None
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    branch=branch,
                    attempt_id=attempt,
                    result=_error_result(error),
                )
                return True
            await self._settle_before_attempt(
                record, lease, locals().get("snapshot"), error
            )
            return True
        except ArtifactViolation:
            error = ModelViolation("MODEL-ARTIFACT")
            attempt = locals().get("attempt_id")
            current_snapshot = locals().get("snapshot")
            if isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ) and current_snapshot.purpose in {
                "consider_creator_input",
                "consider_creator_voice_appraisal",
                "consider_life_query_result",
            }:
                async with self._factory.unit_of_work() as unit_of_work:
                    await self._repository.abandon_hot_episode(
                        unit_of_work,
                        lease=lease,
                        snapshot=current_snapshot,
                        code=error.code,
                    )
                return True
            if (
                isinstance(attempt, ModelAttemptId)
                and isinstance(current_snapshot, ModelEpisodeSnapshot)
                and branch is not None
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    branch=branch,
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
            return True
        except RuntimeTransactionFailure as error:
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
            return True
        except WorkViolation as error:
            self._diagnostic(f"model.worker.transient_failure.{error.code.lower()}")
            return True

    async def _invoke_dialogue_branches(
        self,
        record: WorkRecord,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
    ) -> None:
        context_bytes = await self._read_context(snapshot)
        response_branch = _branch_or_none(
            snapshot, CognitiveBranchRole.RESPONSE_ACTION.value
        )
        appraisal_branch = _branch(
            snapshot, CognitiveBranchRole.EPISODE_APPRAISAL.value
        )
        response = (
            await self._prepare_branch_call(
                lease,
                snapshot,
                context_bytes,
                CognitiveBranchRole.RESPONSE_ACTION.value,
            )
            if response_branch is not None
            and response_branch.status in {"prepared", "calling_model"}
            else None
        )
        appraisal = (
            await self._prepare_branch_call(
                lease,
                snapshot,
                context_bytes,
                CognitiveBranchRole.EPISODE_APPRAISAL.value,
            )
            if appraisal_branch.status in {"prepared", "calling_model"}
            else None
        )
        if response is not None and appraisal is not None:
            response_task = asyncio.create_task(
                response.adapter.invoke(response.request)
            )
            appraisal_task = asyncio.create_task(
                appraisal.adapter.invoke(appraisal.request)
            )
            try:
                (
                    response_result,
                    appraisal_result,
                    lease,
                ) = await self._await_hot_branches(
                    response_task,
                    appraisal_task,
                    lease,
                    late_appraisal=lambda task: self._schedule_late_appraisal(
                        task, snapshot, appraisal
                    ),
                )
            except asyncio.CancelledError:
                response_task.cancel()
                appraisal_task.cancel()
                await asyncio.gather(
                    response_task, appraisal_task, return_exceptions=True
                )
                raise
            await self._settle_branch_result(lease, snapshot, response, response_result)
            await self._settle_branch_result(
                lease, snapshot, appraisal, appraisal_result
            )
        elif response is not None:
            response_result, lease = await self._invoke_with_renewal(
                response.adapter, response.request, lease
            )
            await self._settle_branch_result(lease, snapshot, response, response_result)
        elif appraisal is not None:
            appraisal_result, lease = await self._invoke_with_renewal(
                appraisal.adapter, appraisal.request, lease
            )
            await self._settle_branch_result(
                lease, snapshot, appraisal, appraisal_result
            )
        current = await self._snapshot(record)
        response_branch = _branch_or_none(
            current, CognitiveBranchRole.RESPONSE_ACTION.value
        )
        if (
            response_branch is not None
            and response_branch.status != "succeeded"
            and response_branch.status != "outcome_unknown"
            and response_branch.attempt_count < 2
        ):
            retry_call = await self._prepare_branch_call(
                lease,
                current,
                context_bytes,
                CognitiveBranchRole.RESPONSE_ACTION.value,
            )
            if retry_call is not None:
                retry_result, lease = await self._invoke_with_renewal(
                    retry_call.adapter, retry_call.request, lease
                )
                await self._settle_branch_result(
                    lease, current, retry_call, retry_result
                )
                current = await self._snapshot(record)
        response_branch = _branch_or_none(
            current, CognitiveBranchRole.RESPONSE_ACTION.value
        )
        appraisal_branch = _branch(current, CognitiveBranchRole.EPISODE_APPRAISAL.value)
        response_ok = (
            response_branch is not None and response_branch.status == "succeeded"
        )
        appraisal_ok = appraisal_branch.status == "succeeded"
        outcome = _hot_aggregate_outcome(response_ok, appraisal_ok)
        if outcome is None:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail_episode(
                    unit_of_work,
                    lease=lease,
                    snapshot=current,
                    code="MODEL-HOT-BRANCHES-FAILED",
                )
            return
        response_candidate = (
            await self._read_branch_candidate(
                cast(ModelBranchSnapshot, response_branch), parse_creator_response
            )
            if response_ok
            else None
        )
        appraisal_candidate = (
            await self._read_branch_appraisal(appraisal_branch, current)
            if appraisal_ok
            else None
        )
        aggregate = CreatorDialogueAggregate(
            schema_version=CREATOR_DIALOGUE_AGGREGATE_VERSION,
            outcome=cast(Any, outcome),
            response=response_candidate,
            appraisal=appraisal_candidate,
        )
        aggregate_bytes = (
            rfc8785.dumps(
                {
                    "schema_version": "armi.model-response-artifact.v1",
                    "candidate": aggregate.model_dump(mode="json", exclude_none=True),
                }
            )
            + b"\n"
        )
        published = await self._publish(
            aggregate_bytes, logical_kind="model.response.aggregate", snapshot=current
        )
        primary_attempt = (
            None if response_branch is None else response_branch.selected_attempt_id
        ) or appraisal_branch.selected_attempt_id
        if primary_attempt is None:
            raise ModelViolation("MODEL-AGGREGATE")
        async with self._factory.unit_of_work() as unit_of_work:
            registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), published
            )
            if registration.inserted:
                await unit_of_work.audit.append(
                    _artifact_audit(unit_of_work, registration.ref, current)
                )
            await self._repository.finalize_dialogue_aggregate(
                unit_of_work,
                lease=lease,
                snapshot=current,
                outcome=outcome,
                response_branch_id=(
                    cast(ModelBranchSnapshot, response_branch).branch_id
                    if response_ok
                    else None
                ),
                appraisal_branch_id=appraisal_branch.branch_id
                if appraisal_ok
                else None,
                primary_attempt_id=ModelAttemptId(primary_attempt),
                aggregate_artifact=registration.ref,
                response_kind=None
                if response_candidate is None
                else response_candidate.kind,
            )
        self._wakeups.notify(CANDIDATE_VALIDATE)

    async def _prepare_branch_call(
        self,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        context_bytes: bytes,
        role: str,
    ) -> _BranchCall | None:
        branch = _branch(snapshot, role)
        try:
            adapter = self._branch_adapters[(snapshot.purpose, role)]
        except KeyError:
            raise ModelViolation("MODEL-BINDING") from None
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
        published = await self._publish(
            request.canonical_bytes,
            logical_kind=f"model.request.{role}",
            snapshot=snapshot,
        )
        async with self._factory.unit_of_work() as unit_of_work:
            registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), published
            )
            if registration.inserted:
                await unit_of_work.audit.append(
                    _artifact_audit(unit_of_work, registration.ref, snapshot)
                )
            attempt_id = await self._repository.prepare_attempt(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                branch=branch,
                binding=adapter.binding,
                request_artifact=registration.ref,
            )
            if attempt_id is None:
                return None
        async with self._factory.unit_of_work() as unit_of_work:
            await self._repository.mark_dispatched(
                unit_of_work,
                lease=lease,
                attempt_id=attempt_id,
                episode_id=snapshot.episode_id,
            )
        return _BranchCall(branch, adapter, request, attempt_id)

    async def _await_hot_branches(
        self,
        response: asyncio.Task[ModelInvocationResult],
        appraisal: asyncio.Task[ModelInvocationResult],
        lease: WorkLease,
        *,
        late_appraisal: Callable[[asyncio.Task[ModelInvocationResult]], None]
        | None = None,
    ) -> tuple[ModelInvocationResult, ModelInvocationResult, WorkLease]:
        current_lease = lease
        response_done_at: float | None = None
        loop = asyncio.get_running_loop()
        while not response.done() or not appraisal.done():
            timeout = _RENEW_SECONDS
            if response_done_at is not None and not appraisal.done():
                timeout = min(
                    timeout,
                    max(
                        0.0,
                        response_done_at + _APPRAISAL_GRACE_SECONDS - loop.time(),
                    ),
                )
            pending = {task for task in (response, appraisal) if not task.done()}
            done, _ = await asyncio.wait(
                pending,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if response in done and response_done_at is None:
                response_done_at = loop.time()
            if (
                response_done_at is not None
                and not appraisal.done()
                and (
                    not done
                    or loop.time() >= response_done_at + _APPRAISAL_GRACE_SECONDS
                )
            ):
                appraisal_result = await self._cancel_appraisal(
                    appraisal, late_appraisal=late_appraisal
                )
                return await response, appraisal_result, current_lease
            if not done:
                try:
                    current_lease = await self._work.renew(
                        current_lease, lease_seconds=_LEASE_SECONDS
                    )
                except WorkViolation:
                    response.cancel()
                    appraisal.cancel()
                    await asyncio.gather(response, appraisal, return_exceptions=True)
                    raise ModelViolation("MODEL-WORK-STALE") from None
        return await response, await appraisal, current_lease

    async def _cancel_appraisal(
        self,
        appraisal: asyncio.Task[ModelInvocationResult],
        *,
        late_appraisal: Callable[[asyncio.Task[ModelInvocationResult]], None]
        | None = None,
    ) -> ModelInvocationResult:
        appraisal.cancel()
        await asyncio.sleep(0)
        if appraisal.cancelled():
            return _appraisal_timeout_result(cancellation_confirmed=True)
        if late_appraisal is None:
            appraisal.add_done_callback(_consume_task_result)
        else:
            late_appraisal(appraisal)
        return _appraisal_timeout_result(cancellation_confirmed=False)

    def _schedule_late_appraisal(
        self,
        appraisal: asyncio.Task[ModelInvocationResult],
        snapshot: ModelEpisodeSnapshot,
        call: _BranchCall,
    ) -> None:
        task = asyncio.create_task(
            self._record_late_appraisal(appraisal, snapshot, call)
        )
        self._late_tasks.add(task)
        task.add_done_callback(self._late_tasks.discard)

    async def _record_late_appraisal(
        self,
        appraisal: asyncio.Task[ModelInvocationResult],
        snapshot: ModelEpisodeSnapshot,
        call: _BranchCall,
    ) -> None:
        try:
            result = await appraisal
            if (
                result.status is not ModelResultStatus.SUCCEEDED
                or result.response_bytes is None
            ):
                self._diagnostic("model.appraisal.late_result_failed")
                return
            published = await self._publish(
                result.response_bytes,
                logical_kind="model.response.episode_appraisal.late",
                snapshot=snapshot,
            )
            async with self._factory.unit_of_work() as unit_of_work:
                registration = await self._catalog.register(
                    unit_of_work, ArtifactId(uuid7()), published
                )
                if registration.inserted:
                    await unit_of_work.audit.append(
                        _artifact_audit(unit_of_work, registration.ref, snapshot)
                    )
                await self._repository.record_late_response(
                    unit_of_work,
                    snapshot=snapshot,
                    attempt_id=call.attempt_id,
                    response_artifact=registration.ref,
                )
            self._diagnostic("model.appraisal.late_result_observed")
        except asyncio.CancelledError:
            raise
        except Exception:
            self._diagnostic("model.appraisal.late_result_unavailable")

    async def _settle_branch_result(
        self,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        call: _BranchCall,
        result: ModelInvocationResult,
    ) -> None:
        if result.status is ModelResultStatus.SUCCEEDED:
            published = await self._publish(
                cast(bytes, result.response_bytes),
                logical_kind=f"model.response.{call.branch.role}",
                snapshot=snapshot,
            )
            async with self._factory.unit_of_work() as unit_of_work:
                registration = await self._catalog.register(
                    unit_of_work, ArtifactId(uuid7()), published
                )
                if registration.inserted:
                    await unit_of_work.audit.append(
                        _artifact_audit(unit_of_work, registration.ref, snapshot)
                    )
                await self._repository.settle_success(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    branch=call.branch,
                    attempt_id=call.attempt_id,
                    response_artifact=registration.ref,
                    result=result,
                )
            return
        async with self._factory.unit_of_work() as unit_of_work:
            await self._repository.settle_failure(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                branch=call.branch,
                attempt_id=call.attempt_id,
                result=result,
            )

    async def _read_branch_candidate(
        self,
        branch: ModelBranchSnapshot,
        parser: Callable[[object], CreatorResponseCandidate],
    ) -> CreatorResponseCandidate:
        if branch.response_artifact is None:
            raise ModelViolation("MODEL-AGGREGATE")
        raw = await self._read_artifact_bytes(branch.response_artifact)
        return parser(_response_candidate_value(raw))

    async def _read_branch_appraisal(
        self, branch: ModelBranchSnapshot, snapshot: ModelEpisodeSnapshot
    ) -> CreatorAppraisalCandidate:
        if branch.response_artifact is None:
            raise ModelViolation("MODEL-AGGREGATE")
        raw = await self._read_artifact_bytes(branch.response_artifact)
        return parse_creator_appraisal(
            _response_candidate_value(raw),
            allowed_context_refs=frozenset(
                str(i["ref"]) for i in snapshot.included_context_refs
            ),
        )

    async def _read_artifact_bytes(self, ref: ArtifactRef) -> bytes:
        try:
            stream = await self._storage.open_verified(ref)
            value: bytes | None = None
            async with stream:
                value = await stream.read()
            if value is None:
                raise ModelViolation("MODEL-ARTIFACT")
            return value
        except ArtifactViolation:
            raise ModelViolation("MODEL-ARTIFACT") from None

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
        branch: ModelBranchSnapshot,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
    ) -> None:
        async with self._factory.unit_of_work() as unit_of_work:
            await self._repository.settle_failure(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                branch=branch,
                attempt_id=attempt_id,
                result=result,
            )
            await self._repository.fail_episode(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                code=result.error_code or "MODEL-PROVIDER-FAILED",
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
                    branch = _branch(snapshot, CognitiveBranchRole.PRIMARY.value)
                    await self._repository.fail_before_attempt(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        branch=branch,
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
    return ModelInvocationResult(status, None, None, None, None, error.code)


def _branch(snapshot: ModelEpisodeSnapshot, role: str) -> ModelBranchSnapshot:
    for branch in snapshot.branches:
        if branch.role == role:
            return branch
    raise ModelViolation("MODEL-BRANCH-STATE")


def _branch_or_none(
    snapshot: ModelEpisodeSnapshot, role: str
) -> ModelBranchSnapshot | None:
    return next((branch for branch in snapshot.branches if branch.role == role), None)


def _response_candidate_value(value: bytes) -> object:
    try:
        response = json.loads(value)
        if not isinstance(response, dict):
            raise ModelViolation("MODEL-AGGREGATE")
        mapping = cast(dict[str, object], response)
        if (
            mapping.get("schema_version") != "armi.model-response-artifact.v1"
            or "candidate" not in mapping
        ):
            raise ModelViolation("MODEL-AGGREGATE")
        return mapping["candidate"]
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ModelViolation("MODEL-AGGREGATE") from None


def _appraisal_timeout_result(*, cancellation_confirmed: bool) -> ModelInvocationResult:
    return ModelInvocationResult(
        (
            ModelResultStatus.TIMED_OUT
            if cancellation_confirmed
            else ModelResultStatus.OUTCOME_UNKNOWN
        ),
        None,
        None,
        None,
        None,
        (
            "MODEL-APPRAISAL-TIMEOUT"
            if cancellation_confirmed
            else "MODEL-OUTCOME-UNKNOWN"
        ),
    )


def _hot_aggregate_outcome(
    response_succeeded: bool, appraisal_succeeded: bool
) -> str | None:
    if response_succeeded and appraisal_succeeded:
        return "complete"
    if response_succeeded:
        return "response_only"
    if appraisal_succeeded:
        return "internal_only"
    return None


def _consume_task_result(task: asyncio.Task[ModelInvocationResult]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        task.result()


__all__ = ("ModelPipeline",)
