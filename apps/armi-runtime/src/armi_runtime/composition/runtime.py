"""Explicit S009 Runtime composition root and Uvicorn process ownership."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import selectors
import signal
import threading
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import uvicorn
from armi_activity.api import ActivityViolation
from armi_adapter_esp32_display import (
    MoodDisplayAdapter,
    MoodDisplayViolation,
    load_mood_display_config,
)
from armi_artifact_store.api import ArtifactLifecyclePort
from armi_artifact_store.bootstrap import (
    bootstrap_artifact_catalog,
    bootstrap_artifact_lifecycle,
)
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import LifeViolation
from armi_attention.bootstrap import (
    bootstrap_opportunity_owner,
    bootstrap_opportunity_sleep,
)
from armi_capability.api import CapabilityAvailability
from armi_capability.bootstrap import bootstrap_capability
from armi_codex.api import CodexDelegationViolation, CodexRuntimePort
from armi_codex.bootstrap import bootstrap_codex_commit
from armi_cognition.bootstrap import (
    bootstrap_cognition_context,
    bootstrap_cognition_owner,
)
from armi_context.api import ContextViolation
from armi_data_rights.api import (
    CreatorExportViolation,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderResult,
    DataRightsViolation,
)
from armi_effect.api import EffectViolation
from armi_effect.bootstrap import (
    bootstrap_effect_operation_read,
)
from armi_experience.bootstrap import bootstrap_experience_owner
from armi_expression.api import ResponseViolation
from armi_interaction.api import (
    CreatorInputCommand,
    CreatorInputViolation,
    ExternalMessageViolation,
    OtherHumanInputCommand,
    OtherHumanPartyKey,
    OtherHumanSceneCommand,
    RegisterOtherHumanPartyCommand,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
)
from armi_kernel.application import (
    CandidateViolation,
    ExecutionCustodyMode,
    ExecutionCustodyRequest,
    ExecutionCustodyScope,
    ExecutionCustodyScopeKind,
    LifeRecordQueryViolation,
    ModelViolation,
    OtherHumanRecordViolation,
    RecoveryDecision,
    RecoveryStatus,
    RecoveryViolation,
    RuntimeAuthorityViolation,
    RuntimeInstanceId,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId
from armi_live_vision.api import (
    CameraSourceIdentity,
    LiveVisionRuntimePort,
    LiveVisionViolation,
    ObservationOriginKind,
    ScreenSourceIdentity,
    VisualCaptureFormat,
    VisualObservation,
    VisualSourceKind,
)
from armi_live_vision.bootstrap import (
    compose_live_vision,
    compose_live_vision_retention,
    compose_visual_capture_router,
    compose_visual_observation_sink,
)
from armi_live_voice.api import LiveVoiceRuntimePort, LiveVoiceViolation
from armi_live_voice.bootstrap import bootstrap_live_voice_context_read
from armi_local_control.runtime_errors import RuntimeViolation
from armi_memory.api import MemoryViolation
from armi_perception.bootstrap import bootstrap_visual_recognition_attempts
from armi_prompt.api import CreatorPromptViolation
from armi_relationship.api import RelationshipViolation
from armi_sleep.api import CreatorMaintenanceViolation, SleepViolation
from armi_web_observation.api import (
    WebObservationRuntimePort,
    WebObservationViolation,
    WebResearchRuntimePort,
    WebResearchViolation,
)
from armi_web_observation.bootstrap import bootstrap_web_context_read
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from armi_runtime.adapters.model.external_content import (
    VolcengineArkExternalContentRecognizer,
    load_external_recognition_binding,
)
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.runtime_observability import (
    RuntimeObservationError,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera
from armi_runtime.adapters.vision.windows_screen import WindowsScreenSource
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio
from armi_runtime.application.cognition_cycle import RuntimeCognitionState
from armi_runtime.application.creator_contract import (
    CodexAvailabilityResponse,
    LiveVisionObservationResponse,
    LiveVisionSourceStatusResponse,
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    QQChannelHealthResponse,
    Readiness,
    RuntimeComponentHealthResponse,
    RuntimeStatusResponse,
)
from armi_runtime.application.creator_media import CreatorMedia
from armi_runtime.application.creator_timeline import CreatorTimelineProjectionAssembler
from armi_runtime.application.life_opportunity import RuntimeLifeOpportunityFacts
from armi_runtime.application.live_voice import (
    RuntimeLiveVoiceEffectAdapter,
    RuntimeLiveVoiceResultObserver,
)
from armi_runtime.application.maintenance import RuntimeSleepFacts
from armi_runtime.application.subject_summary import RuntimeSubjectSummaryAssembler
from armi_runtime.composition.perception_availability import UnavailableMediaFetch
from armi_runtime.interfaces.browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
)
from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.creator_events import CreatorEventBroker
from armi_runtime.interfaces.static_assets import AssetViolation, StaticAssetStore

from .admin_control import (
    RuntimeAdminControlServer,
    load_admin_control_incarnation,
)
from .authority import (
    LocalAuthorityState,
    RuntimeAuthorityController,
)
from .config_assets import runtime_config_path
from .configuration_consumption import ConfigurationConsumption
from .creator_session import compose_browser_sessions, derive_timeline_cursor_key
from .data_rights_identity import derive_data_rights_identity_token_key
from .database import (
    ContinuityState,
    DatabaseViolation,
    compose_activity_module,
    compose_candidate_validation_pipeline,
    compose_codex_pipeline,
    compose_codex_read_ports,
    compose_cognition_exact_life_query,
    compose_context_candidate_read,
    compose_context_dialogue_read,
    compose_context_embedding_pipeline,
    compose_context_pipeline,
    compose_context_projection_invalidation,
    compose_creator_operation_query,
    compose_data_rights_core,
    compose_data_rights_module,
    compose_effect_owner_context,
    compose_effect_pipeline,
    compose_evidence_module,
    compose_exact_life_query_pipeline,
    compose_execution_custody,
    compose_expression_module,
    compose_interaction_identity,
    compose_interaction_module,
    compose_life_opportunity_pipeline,
    compose_life_record_query,
    compose_material_module,
    compose_memory_module,
    compose_model_pipeline,
    compose_mood_module,
    compose_opportunity_admission,
    compose_other_human_record_query,
    compose_perception_module,
    compose_prompt_module,
    compose_relationship_module,
    compose_runtime_authority,
    compose_runtime_observation,
    compose_runtime_recovery,
    compose_runtime_unit_of_work_factory,
    compose_sleep_module,
    compose_subject_commit_pipeline,
    compose_subject_state_module,
    compose_web_research_admission_pipeline,
    compose_web_search_pipeline,
    inspect_creator_context,
    inspect_runtime_continuity,
    runtime_database_reason,
)
from .diagnostics import StructuredDiagnosticLog
from .environment import PreparedEnvironment
from .lifecycle import RUNTIME_BLOCKING_REASONS, LifecycleController
from .live_voice import compose_runtime_live_voice
from .napcat_process import compose_qq_health, disabled_qq_health
from .owner_roster import compose_runtime_owner_roster
from .qq_channel import QQChannelBinding, compose_qq_channel
from .runtime_credentials import codex_local_availability
from .runtime_observability import RuntimeObservationDriver
from .supervisor import RuntimeSupervisor
from .work_wakeup import WorkWakeupBus

EXIT_GRACEFUL = 0
EXIT_LISTENER_FAILURE = 3
EXIT_GRACEFUL_TIMEOUT = 4


class _RuntimeServer(uvicorn.Server):
    """Keep handled Windows console signals inside the Runtime lifecycle."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        handled = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGBREAK"):
            handled.append(signal.SIGBREAK)
        original = {
            current: signal.signal(current, self.handle_exit) for current in handled
        }
        try:
            yield
        finally:
            for current, handler in original.items():
                signal.signal(current, handler)


class _SwitchableIngress:
    """Keep the listener bound while explicitly pausing external admission."""

    __slots__ = ("_app", "enabled")

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self.enabled = True

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not self.enabled:
            await StarletteResponse(status_code=503)(scope, receive, send)
            return
        await self._app(scope, receive, send)


async def _compose_live_vision_sources(
    *,
    prepared: PreparedEnvironment,
    config: Any,
    factory: Any,
    catalog: Any,
    evidence: Any,
    opportunity: Any,
    subject_id: UUID,
    model_locator: Any,
) -> tuple[
    dict[VisualSourceKind, LiveVisionRuntimePort],
    dict[VisualSourceKind, Any],
]:
    recognition_binding = load_external_recognition_binding(
        runtime_config_path("model-bindings.yaml", environment_root=prepared.root)
    )
    source_specs: list[tuple[VisualSourceKind, Any, Any, Any]] = []
    camera_config = config.vision.camera
    if camera_config.enabled and camera_config.identity is not None:
        source_specs.append(
            (
                VisualSourceKind.CAMERA,
                camera_config,
                CameraSourceIdentity(
                    camera_config.identity.name,
                    camera_config.identity.device_path,
                    camera_config.identity.usb_location_id,
                ),
                DirectShowUsbCamera(),
            )
        )
    screen_config = config.vision.screen
    if screen_config.enabled and screen_config.identity is not None:
        source_specs.append(
            (
                VisualSourceKind.SCREEN,
                screen_config,
                ScreenSourceIdentity(
                    screen_config.identity.source_device_name,
                    screen_config.identity.monitor_device_path,
                    screen_config.identity.edid_name,
                    screen_config.identity.width,
                    screen_config.identity.height,
                ),
                WindowsScreenSource(),
            )
        )
    services: dict[VisualSourceKind, LiveVisionRuntimePort] = {}
    sinks: dict[VisualSourceKind, Any] = {}
    for source_kind, source_config, identity, adapter in source_specs:
        try:
            width = (
                identity.width
                if isinstance(identity, ScreenSourceIdentity)
                else source_config.width
            )
            height = (
                identity.height
                if isinstance(identity, ScreenSourceIdentity)
                else source_config.height
            )
            fps = float(
                source_config.capture_hz
                if source_kind is VisualSourceKind.SCREEN
                else source_config.fps
            )
            sink = compose_visual_observation_sink(
                factory=factory,
                storage=ContentAddressedArtifactStore(
                    prepared.data_root / "artifacts",
                    max_object_bytes=config.artifacts.max_object_bytes,
                    publication_catalog=catalog,
                    publication_uow_factory=factory,
                    orphan_grace_seconds=config.artifacts.orphan_grace_seconds,
                ),
                catalog=catalog,
                work=PostgreSQLDurableWorkGateway(factory),
                recognizer=VolcengineArkExternalContentRecognizer(
                    credential_port=prepared.credential_port,
                    locator=model_locator,
                    binding=recognition_binding.ark,
                ),
                attempts=bootstrap_visual_recognition_attempts(),
                evidence=evidence,
                opportunity=opportunity,
                subject_id=subject_id,
                source_kind=source_kind,
                source=identity,
                width=width,
                height=height,
                fps=fps,
                retention=timedelta(seconds=source_config.frame_retention_seconds),
            )
            service = compose_live_vision(
                source_kind=source_kind,
                source=adapter,
                sink=sink,
                identity=identity,
                format=VisualCaptureFormat(width, height, fps),
                hourly_limit=source_config.hourly_observation_limit,
                automatic_cooldown=timedelta(
                    seconds=source_config.automatic_cooldown_seconds
                ),
                periodic_refresh=timedelta(
                    seconds=source_config.periodic_refresh_seconds
                ),
                reconnect=timedelta(seconds=source_config.reconnect_seconds),
                change_threshold=source_config.change_threshold,
                stable_change_samples=source_config.stable_change_samples,
                sample_interval=timedelta(seconds=1 / source_config.change_sample_hz),
                capture_interval=timedelta(seconds=1 / source_config.capture_hz)
                if source_kind is VisualSourceKind.SCREEN
                else timedelta(0),
            )
            sink.bind_capture(service.capture_frames)
            services[source_kind] = service
            sinks[source_kind] = sink
            if source_config.auto_start:
                await service.start()
        except ValueError, ModelViolation:
            services.pop(source_kind, None)
            sinks.pop(source_kind, None)
    return services, sinks


async def _serve(
    prepared: PreparedEnvironment,
    *,
    creator_web_resources: Path | None,
    configuration_consumption: ConfigurationConsumption,
    instance_uuid: UUID | None = None,
) -> int:
    config = prepared.effective.config
    try:
        with configuration_consumption.consumer("mood-display"):
            mood_display_config = load_mood_display_config(prepared.root)
    except MoodDisplayViolation as error:
        raise RuntimeViolation(
            error.code, "mood display configuration is invalid"
        ) from error
    instance_uuid = instance_uuid or uuid7()
    instance_id = str(instance_uuid)
    lifecycle = LifecycleController(
        environment_id=str(config.environment.environment_id)
    )
    diagnostic = StructuredDiagnosticLog(
        data_root=prepared.data_root,
        environment_id=str(config.environment.environment_id),
        instance_id=instance_id,
        on_degraded=lifecycle.add_degradation,
        rotation_max_bytes=config.diagnostics.rotation_max_bytes,
        retention_seconds=config.diagnostics.retention_seconds,
    )
    web_assets_error: str | None = None
    try:
        assets = (
            StaticAssetStore.load_packaged()
            if creator_web_resources is None
            else StaticAssetStore.load_directory(creator_web_resources)
        )
    except AssetViolation as error:
        web_assets_error = error.code
        assets = StaticAssetStore({})
        diagnostic.emit("creator.web.unavailable", result_code=error.code)
    lifecycle.start()
    diagnostic.emit("runtime.lifecycle.starting", result_code="LIFE_STARTING")
    database_reasons = runtime_database_reason(prepared)
    continuity = (
        inspect_runtime_continuity(prepared)
        if not database_reasons
        else ContinuityState.INVALID
    )
    authority_port = None
    authority: RuntimeAuthorityController | None = None
    execution_custody = None
    recovery_port = None
    runtime_unit_of_work_factory: PostgreSQLUnitOfWorkFactory | None = None
    artifact_lifecycle: ArtifactLifecyclePort | None = None
    observation_port = None
    observation_driver: RuntimeObservationDriver | None = None
    recovery_reasons: tuple[str, ...] = ()
    browser_sessions: BrowserSessionStore | None = None
    interaction_module = None
    evidence_module = None
    scene_timeline_query = None
    creator_scenes = None
    activity_module = None
    data_rights_module = None
    life_record_query = None
    exact_life_query_pipeline = None
    creator_relationship_query = None
    relationship_module = None
    memory_module = None
    material_module = None
    sleep_module = None
    subject_state_module = None
    mood_module = None
    mood_display: MoodDisplayAdapter | None = None
    prompt_module = None
    creator_events: CreatorEventBroker | None = None
    creator_input = None
    media_uploads = None
    creator_context = None
    subject_summary_provider: RuntimeSubjectSummaryAssembler | None = None
    creator_operations = None
    other_human_input = None
    external_message_input = None
    perception_module = None
    qq_channel: QQChannelBinding | None = None
    qq_server: _RuntimeServer | None = None
    qq_ingress: _SwitchableIngress | None = None
    other_human_record_query = None
    life_opportunity_pipeline = None
    context_pipeline = None
    context_embedding_pipeline = None
    model_pipeline = None
    candidate_pipeline = None
    subject_commit_pipeline = None
    codex_availability = CapabilityAvailability(
        config.codex.enabled,
        False,
        "CODEX-DISABLED" if not config.codex.enabled else "CODEX-UNAVAILABLE",
    )
    capability_read = bootstrap_capability(lambda: codex_availability)
    effect_pipeline = None
    web_search_pipeline: WebObservationRuntimePort | None = None
    web_research_pipeline: WebResearchRuntimePort | None = None
    codex_pipeline: CodexRuntimePort | None = None
    admin_control: RuntimeAdminControlServer | None = None
    work_wakeups = WorkWakeupBus()
    live_voice_service: LiveVoiceRuntimePort | None = None
    live_vision_services: dict[VisualSourceKind, LiveVisionRuntimePort] = {}
    vision_sinks: dict[VisualSourceKind, Any] = {}
    vision_capture_router = None
    live_vision_retention = None

    def inject_admin_fault(name: str) -> None:
        if admin_control is not None:
            admin_control.trigger_fault(name)

    if continuity is ContinuityState.BORN:
        try:
            subject_state_module = compose_subject_state_module()
            await subject_state_module.open()
            mood_module = compose_mood_module()
            await mood_module.open()
            execution_custody = compose_execution_custody(prepared)
            await execution_custody.open()
            authority_port = compose_runtime_authority(prepared)
            await authority_port.open()
            authority = RuntimeAuthorityController(
                authority_port,
                lease_seconds=config.runtime.lease_seconds,
            )
            authority_request = ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.RUNTIME_AUTHORITY,
                    config.environment.environment_id,
                ),
                ExecutionCustodyMode.EXCLUSIVE,
            )
            async with execution_custody.hold((authority_request,), deadline_at=None):
                acquired = await authority.acquire(RuntimeInstanceId(instance_uuid))
                await authority.heartbeat_once()
            diagnostic.emit(
                "runtime.authority.acquired",
                result_code="AUTH_ACQUIRED",
            )
            if acquired.fence.runtime_instance_id.value != instance_uuid:
                raise RuntimeAuthorityViolation("AUTH-INSTANCE-MISMATCH")
            runtime_unit_of_work_factory = compose_runtime_unit_of_work_factory(
                prepared,
                authority_admission=authority.require_writable,
            )
            await runtime_unit_of_work_factory.open()
            if mood_display_config is not None and mood_display_config.enabled:
                display_subject_id = authority.require_writable().subject_id

                async def read_mood_display_snapshot():
                    async with runtime_unit_of_work_factory.unit_of_work(
                        read_only=True
                    ) as unit:
                        return await mood_module.read.snapshot(
                            unit.transaction, subject_id=display_subject_id
                        )

                mood_display = MoodDisplayAdapter(
                    mood_display_config, read_mood_display_snapshot
                )
            artifact_catalog = bootstrap_artifact_catalog()
            from .media_uploads import compose_media_uploads

            media_uploads = compose_media_uploads(
                prepared.data_root,
                config.environment.environment_id,
                authority.require_writable().life_generation_id,
                runtime_unit_of_work_factory,
                artifact_catalog,
            )
            artifact_storage = ContentAddressedArtifactStore(
                prepared.data_root / "artifacts",
                max_object_bytes=config.artifacts.max_object_bytes,
            )
            await artifact_storage.prepare()
            artifact_lifecycle = bootstrap_artifact_lifecycle(
                artifact_storage,
                runtime_unit_of_work_factory,
                PostgreSQLDurableWorkGateway(runtime_unit_of_work_factory),
            )
            live_vision_retention = compose_live_vision_retention(
                runtime_unit_of_work_factory,
                artifact_catalog,
            )
            await live_vision_retention.purge_once()
            await artifact_lifecycle.recover()
            effect_owner = bootstrap_effect_operation_read()
            identity_tokens = derive_data_rights_identity_token_key(prepared)
            interaction_identity = compose_interaction_identity(identity_tokens)
            creator_context = await inspect_creator_context(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                identity=interaction_identity,
            )
            if creator_context is None:
                raise BrowserSessionViolation(
                    "SEC_CREATOR_IDENTITY_UNAVAILABLE",
                    status_code=503,
                )
            prompt_module = compose_prompt_module(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
                catalog=artifact_catalog,
            )
            await prompt_module.open()
            data_rights_core = compose_data_rights_core()
            owner_roster = compose_runtime_owner_roster(
                data_rights=data_rights_core.participant,
                mood_read=mood_module.read,
                prompt_read=prompt_module.read,
                subject_state_read=subject_state_module.read,
            )
            lifecycle.begin_recovery()
            diagnostic.emit(
                "runtime.lifecycle.recovering",
                result_code="LIFE_RECOVERING",
            )
            recovery_port = compose_runtime_recovery(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                authority_admission=authority.require_writable,
                owner_roster=owner_roster,
                catalog=artifact_catalog,
            )
            await recovery_port.open()
            recovery = await recovery_port.recover()
            if recovery.status is RecoveryStatus.BLOCKED:
                recovery_reasons = tuple(
                    dict.fromkeys(
                        (
                            "RUNTIME_RECOVERY_BLOCKED",
                            *(
                                finding.reason_code
                                for finding in recovery.findings
                                if finding.decision is RecoveryDecision.BLOCKED
                            ),
                        )
                    )
                )
                diagnostic.emit(
                    "runtime.recovery.blocked",
                    level=logging.ERROR,
                    result_code="REC_BLOCKED",
                    reason_codes=recovery_reasons,
                )
                raise RecoveryViolation("REC-BLOCKED")
            else:
                diagnostic.emit(
                    "runtime.recovery.safe",
                    result_code="REC_SAFE",
                )
            try:
                observation_port = compose_runtime_observation(
                    runtime_unit_of_work_factory,
                    effects=effect_owner,
                    artifacts=artifact_catalog,
                )
                await observation_port.open()
                observation_driver = RuntimeObservationDriver(
                    observation_port,
                    data_root=prepared.data_root,
                    sample_interval_seconds=(
                        config.observability.sample_interval_seconds
                    ),
                    disk_warning_free_bytes=(
                        config.observability.disk_warning_free_bytes
                    ),
                    disk_critical_free_bytes=(
                        config.observability.disk_critical_free_bytes
                    ),
                    diagnostic_status=lambda: diagnostic.status,
                    diagnostic=lambda event: diagnostic.emit(
                        event,
                        level=logging.WARNING,
                        result_code="RUNTIME_OBSERVABILITY",
                    ),
                )
            except DatabaseViolation, RuntimeObservationError:
                if observation_port is not None:
                    await observation_port.close()
                observation_port = None
                observation_driver = None
                lifecycle.add_degradation("RUNTIME_OBSERVABILITY_UNAVAILABLE")
                diagnostic.emit(
                    "runtime.observability.unavailable",
                    level=logging.WARNING,
                    result_code="OBSERVABILITY_UNAVAILABLE",
                )
            browser_sessions = compose_browser_sessions(
                prepared,
                creator_party_id=creator_context.party_id,
                default_scene_key=creator_context.default_scene_key,
            )
            creator_events = CreatorEventBroker(
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CREATOR_EVENT_STREAM",
                )
            )
            evidence_module = compose_evidence_module()
            await evidence_module.open()
            experience_owner = bootstrap_experience_owner()
            cognition_owner = bootstrap_cognition_owner()
            cognition_context = bootstrap_cognition_context(
                experiences=experience_owner
            )
            opportunity_owner = bootstrap_opportunity_owner()
            opportunity_sleep = bootstrap_opportunity_sleep()
            web_context = bootstrap_web_context_read()
            activity_module = compose_activity_module(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
                environment_id=config.environment.environment_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                subject_state=subject_state_module.read,
            )
            await activity_module.open()
            relationship_module = compose_relationship_module(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
                environment_id=config.environment.environment_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                visibility=data_rights_core.visibility,
            )
            await relationship_module.open()
            creator_relationship_query = relationship_module.read
            memory_module = compose_memory_module(
                runtime_unit_of_work_factory,
                environment_id=config.environment.environment_id,
                creator_party_id=creator_context.party_id,
                subject_id=authority.require_writable().subject_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                visibility=data_rights_core.visibility,
            )
            await memory_module.open()
            material_module = compose_material_module(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                data_root=prepared.data_root,
                max_object_bytes=config.artifacts.max_object_bytes,
                catalog=artifact_catalog,
            )
            await material_module.open()
            life_record_query = compose_life_record_query(
                runtime_unit_of_work_factory,
                environment_id=config.environment.environment_id,
                creator_party_id=creator_context.party_id,
                subject_id=authority.require_writable().subject_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                activity_read=activity_module.read,
                memory_read=memory_module.read,
                material_read=material_module.read,
                relationship_read=relationship_module.read,
                subject_state_read=subject_state_module.read,
                visibility=data_rights_core.visibility,
                experiences=experience_owner,
            )
            await life_record_query.open()
            opportunity_admission = compose_opportunity_admission()
            cognition_operation = cognition_owner
            codex_reads = compose_codex_read_ports()
            timeline_projections = CreatorTimelineProjectionAssembler(
                evidence=evidence_module.read,
                opportunity_admission=opportunity_admission,
                opportunity_read=opportunity_owner,
                cognition=cognition_operation,
                catalog=artifact_catalog,
                codex=codex_reads.task_sources,
            )
            exact_life_query_pipeline = compose_exact_life_query_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                query=life_record_query,
                cognition=compose_cognition_exact_life_query(),
                opportunity=opportunity_admission,
                catalog=artifact_catalog,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="EXACT_LIFE_QUERY",
                ),
            )
            await exact_life_query_pipeline.open()
            sleep_module = compose_sleep_module(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
                environment_id=config.environment.environment_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                runtime_facts=RuntimeSleepFacts(
                    cognition=cognition_operation,
                    effects=effect_owner,
                ),
                opportunities=opportunity_sleep,
            )
            await sleep_module.open()
            context_projection_invalidation = compose_context_projection_invalidation()
            voice_context_read = bootstrap_live_voice_context_read()
            interaction_module = compose_interaction_module(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                notifier=creator_events,
                subject_state_read=subject_state_module.read,
                evidence=evidence_module.write,
                evidence_read=evidence_module.read,
                opportunity=opportunity_admission,
                data_rights=data_rights_core.gate,
                custody=execution_custody,
                visibility=data_rights_core.visibility,
                identity=interaction_identity,
                identity_tokens=identity_tokens,
                catalog=artifact_catalog,
                timeline_projections=timeline_projections,
                voice_responses=voice_context_read,
                sleep_maintenance=sleep_module.maintenance,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CREATOR_INPUT",
                ),
                fault_injector=inject_admin_fault,
            )
            await interaction_module.open()
            other_human_record_query = compose_other_human_record_query(
                runtime_unit_of_work_factory,
                environment_id=config.environment.environment_id,
                cursor_key=derive_timeline_cursor_key(prepared),
                data_root=prepared.data_root,
                max_object_bytes=config.artifacts.max_object_bytes,
                catalog=artifact_catalog,
                visibility=data_rights_core.visibility,
                interaction=interaction_module.other_human_read,
                evidence=evidence_module.read,
                effect=effect_owner,
            )
            await other_human_record_query.open()
            data_rights_module = compose_data_rights_module(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                creator_party_id=creator_context.party_id,
                core=data_rights_core,
                business_participants=owner_roster.data_rights,
                catalog=artifact_catalog,
                parties=interaction_module.identity,
                party_roster=interaction_module.party_catalog,
                notifier=creator_events,
                artifact_lifecycle=artifact_lifecycle,
                execution_custody=execution_custody,
                identity_key=identity_tokens.key_identity,
            )
            await data_rights_module.open()
            expression_module = compose_expression_module(
                relationship_read=relationship_module.read,
                relationship_policy=relationship_module.policy,
                interaction_routes=interaction_module.effect_routes,
                interaction_scenes=interaction_module.scene_transitions,
            )
            codex_artifacts = compose_effect_owner_context(
                codex=codex_reads,
                catalog=artifact_catalog,
            )
            scene_timeline_query = interaction_module.scene_timeline
            creator_scenes = interaction_module.creator_scenes
            creator_input = interaction_module.creator_input
            dialogue_read = compose_context_dialogue_read(
                prepared,
                catalog=artifact_catalog,
                evidence=evidence_module.read,
                interaction=interaction_module.context_read,
                expression=expression_module.intents,
                effects=effect_owner,
            )
            if config.voice.enabled:
                try:
                    with configuration_consumption.consumer("voice"):
                        live_voice_service = compose_runtime_live_voice(
                            prepared,
                            factory=runtime_unit_of_work_factory,
                            subject_id=authority.require_writable().subject_id,
                            creator=creator_context,
                            interaction=interaction_module.creator_input,
                            timeline=interaction_module.effect_delivery,
                        )
                except LiveVoiceViolation:
                    live_voice_service = None
                    lifecycle.add_degradation("RUNTIME_LIVE_VOICE_UNAVAILABLE")
                    diagnostic.emit(
                        "runtime.live_voice.unavailable",
                        level=logging.WARNING,
                        result_code="LIVE_VOICE_UNAVAILABLE",
                    )
            subject_summary_provider = RuntimeSubjectSummaryAssembler(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                subject_state=subject_state_module.read,
            )
            other_human_input = interaction_module.other_human_input
            external_message_input = interaction_module.external_message_input
            creator_operations = compose_creator_operation_query(
                unit_of_work_factory=runtime_unit_of_work_factory,
                creator_party_id=creator_context.party_id,
                interaction=interaction_module.creator_transaction,
                evidence=evidence_module.read,
                expression=expression_module.intents,
                codex=codex_reads.task_sources,
                codex_executions=codex_reads.executions,
                opportunity=opportunity_owner,
                cognition=cognition_owner,
                effect=effect_owner,
            )
            with configuration_consumption.consumer("qq"):
                qq_channel = await compose_qq_channel(
                    prepared,
                    input_port=external_message_input,
                )
            try:
                with configuration_consumption.consumer("perception"):
                    perception_module = compose_perception_module(
                        prepared,
                        unit_of_work_factory=runtime_unit_of_work_factory,
                        fetch=qq_channel.media_fetch
                        if qq_channel is not None
                        else UnavailableMediaFetch(),
                        evidence=evidence_module.write,
                        evidence_read=evidence_module.read,
                        interaction=interaction_module.perception,
                        data_rights=data_rights_core.fence,
                        opportunity=opportunity_admission,
                        catalog=artifact_catalog,
                        wakeups=work_wakeups,
                        diagnostic=lambda event: diagnostic.emit(
                            event,
                            result_code="EXTERNAL_CONTENT",
                        ),
                    )
                    await perception_module.open()
            except ModelViolation:
                raise ExternalMessageViolation(
                    "EXTERNAL-MESSAGE-RECOGNITION-UNAVAILABLE"
                ) from None
            model_locator = config.secret_locators.get("model.ark_api_key")
            if model_locator is not None:
                with configuration_consumption.consumer("vision"):
                    (
                        live_vision_services,
                        vision_sinks,
                    ) = await _compose_live_vision_sources(
                        prepared=prepared,
                        config=config,
                        factory=runtime_unit_of_work_factory,
                        catalog=artifact_catalog,
                        evidence=evidence_module.write,
                        opportunity=opportunity_admission,
                        subject_id=authority.require_writable().subject_id,
                        model_locator=model_locator,
                    )
            vision_capture_router = compose_visual_capture_router(
                factory=runtime_unit_of_work_factory,
                work=PostgreSQLDurableWorkGateway(runtime_unit_of_work_factory),
                coordinators=vision_sinks,
            )
            life_opportunity_pipeline = compose_life_opportunity_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                facts=RuntimeLifeOpportunityFacts(
                    activities=activity_module.read,
                    cognition=cognition_operation,
                    effects=effect_owner,
                    expression=expression_module.intents,
                    interaction=interaction_module.identity,
                ),
                activity_read=activity_module.read,
                material_read=material_module.read,
                relationship_read=relationship_module.read,
                relationship_policy=relationship_module.policy,
                sleep_maintenance=sleep_module.maintenance,
                sleep_read=sleep_module.read,
                subject_state_read=subject_state_module.read,
                wakeups=work_wakeups,
                notifier=creator_events,
            )
            await life_opportunity_pipeline.open()
            opportunity_cognition = opportunity_owner
            runtime_cognition_state = RuntimeCognitionState()
            context_pipeline = compose_context_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                activity_read=activity_module.read,
                capability_read=capability_read,
                codex_read=codex_reads.task_sources,
                codex_context=codex_reads.context,
                cognition_context=cognition_context,
                evidence_read=evidence_module.read,
                interaction_context=interaction_module.context_read,
                dialogue_read=dialogue_read,
                interaction_cognition=interaction_module.cognition_read,
                opportunity_cognition=opportunity_cognition,
                runtime_subjects=runtime_cognition_state,
                web_context=web_context,
                expression_read=expression_module.intents,
                effect_read=effect_owner,
                data_rights=data_rights_module.cognition,
                custody=execution_custody,
                memory_read=memory_module.read,
                memory_projection=memory_module.projection,
                mood_read=mood_module.read,
                prompt_read=prompt_module.read,
                material_projection=material_module.projection,
                relationship_read=relationship_module.read,
                sleep_read=sleep_module.read,
                subject_state_read=subject_state_module.read,
                catalog=artifact_catalog,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CONTEXT_PIPELINE",
                ),
            )
            await context_pipeline.open()
            candidate_context = compose_context_candidate_read()
            subject_commit_pipeline = compose_subject_commit_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                activity_cognition=activity_module.cognition,
                activity_commit=activity_module.commit,
                codex_commit=bootstrap_codex_commit(
                    codex_reads.task_sources,
                    expression_module.commit,
                    artifact_catalog,
                    lambda: codex_availability.available,
                ),
                cognition_commit=cognition_owner,
                experience_commit=experience_owner,
                context_projections=context_projection_invalidation,
                data_rights=data_rights_module.subject_commit,
                evidence=evidence_module.write,
                evidence_read=evidence_module.read,
                expression_commit=expression_module.commit,
                interaction_commit=interaction_module.subject_commit,
                memory_commit=memory_module.commit,
                memory_cognition=memory_module.cognition,
                mood_commit=mood_module.commit,
                mood_cognition=mood_module.cognition,
                opportunity_transition=opportunity_owner,
                prompt_cognition=prompt_module.cognition,
                prompt_commit=prompt_module.commit,
                material_cognition=material_module.cognition,
                material_commit=material_module.commit,
                relationship_cognition=relationship_module.cognition,
                relationship_commit=relationship_module.commit,
                sleep_cognition=sleep_module.cognition,
                sleep_commit=sleep_module.commit,
                subject_state_cognition=subject_state_module.cognition,
                subject_state_commit=subject_state_module.commit,
                catalog=artifact_catalog,
                notifier=creator_events,
                voice_results=(
                    None
                    if live_voice_service is None
                    else RuntimeLiveVoiceResultObserver(
                        service=live_voice_service,
                        factory=runtime_unit_of_work_factory,
                        read=voice_context_read,
                    )
                ),
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="SUBJECT_COMMIT_PIPELINE",
                ),
                fault_injector=inject_admin_fault,
            )
            candidate_pipeline = compose_candidate_validation_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                submission=subject_commit_pipeline,
                activity_cognition=activity_module.cognition,
                activity_read=activity_module.read,
                material_context=candidate_context.material,
                memory_context=candidate_context.memory,
                context=candidate_context.cognition,
                runtime_state=runtime_cognition_state,
                interaction=interaction_module.cognition_read,
                opportunity_context=opportunity_cognition,
                opportunity_transitions=opportunity_cognition,
                evidence=evidence_module.read,
                codex=codex_reads.task_sources,
                codex_available=lambda: codex_availability.available,
                memory_cognition=memory_module.cognition,
                memory_read=memory_module.read,
                mood_cognition=mood_module.cognition,
                mood_read=mood_module.read,
                prompt_cognition=prompt_module.cognition,
                prompt_read=prompt_module.read,
                material_cognition=material_module.cognition,
                material_read=material_module.read,
                relationship_cognition=relationship_module.cognition,
                relationship_read=relationship_module.read,
                sleep_cognition=sleep_module.cognition,
                sleep_read=sleep_module.read,
                subject_state_cognition=subject_state_module.cognition,
                subject_state_read=subject_state_module.read,
                catalog=artifact_catalog,
                visual_sources_active=frozenset(
                    kind.value for kind in live_vision_services
                ),
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CANDIDATE_PIPELINE",
                ),
            )
            effect_pipeline = compose_effect_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                intents=expression_module.intents,
                codex_artifacts=codex_artifacts,
                routes=interaction_module.effect_routes,
                interaction_delivery=interaction_module.effect_delivery,
                custody=execution_custody,
                data_rights=data_rights_module.effect_gate,
                data_rights_fence=data_rights_module.fence,
                runtime_admission=authority.require_writable,
                notifier=creator_events,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event, result_code="EFFECT_REGISTRATION"
                ),
                fault_injector=inject_admin_fault,
                external_message_adapter=(
                    None if qq_channel is None else qq_channel.effect_adapter
                ),
                live_voice_adapter=(
                    None
                    if live_voice_service is None
                    else RuntimeLiveVoiceEffectAdapter(
                        service=live_voice_service,
                        factory=runtime_unit_of_work_factory,
                        read=voice_context_read,
                    )
                ),
            )
            await effect_pipeline.open()
            codex_availability = codex_local_availability(prepared)
            codex_pipeline = compose_codex_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                creator_party_id=creator_context.party_id,
                creator_input=interaction_module.creator_transaction,
                evidence=evidence_module.write,
                evidence_read=evidence_module.read,
                identity=interaction_module.identity,
                opportunity=opportunity_admission,
                expression=expression_module.intents,
                sources=codex_reads.task_sources,
                unavailable_reason=lambda: codex_availability.reason_code,
                custody=execution_custody,
                data_rights=data_rights_module.effect_gate,
                interaction_data_rights=data_rights_module.gate,
                data_rights_fence=data_rights_module.fence,
                runtime_admission=authority.require_writable,
                catalog=artifact_catalog,
                notifier=creator_events,
                diagnostic=lambda event: diagnostic.emit(
                    event, result_code="CODEX_DELEGATION"
                ),
            )
            try:
                await codex_pipeline.open()
            except CodexDelegationViolation:
                codex_availability = CapabilityAvailability(
                    config.codex.enabled, False, "CODEX-UNAVAILABLE"
                )
                lifecycle.add_degradation("RUNTIME_CODEX_UNAVAILABLE")
                diagnostic.emit(
                    "runtime.codex.unavailable",
                    level=logging.WARNING,
                    result_code="CODEX_UNAVAILABLE",
                )
            if config.model.semantic_recall_enabled:
                try:
                    with configuration_consumption.consumer("context-embedding"):
                        context_embedding_pipeline = compose_context_embedding_pipeline(
                            prepared,
                            unit_of_work_factory=runtime_unit_of_work_factory,
                            custody=execution_custody,
                            memory_projection=memory_module.projection,
                            material_projection=material_module.projection,
                        )
                        await context_embedding_pipeline.open()
                except ModelViolation:
                    context_embedding_pipeline = None
                    lifecycle.add_degradation("RUNTIME_SEMANTIC_RECALL_UNAVAILABLE")
                    diagnostic.emit(
                        "runtime.semantic_recall.unavailable",
                        level=logging.WARNING,
                        result_code="SEMANTIC_RECALL_UNAVAILABLE",
                    )
            if "model.ark_api_key" in config.secret_locators:
                try:
                    with configuration_consumption.consumer("cognition"):
                        model_pipeline = compose_model_pipeline(
                            prepared,
                            finalization=candidate_pipeline,
                            unit_of_work_factory=runtime_unit_of_work_factory,
                            context=candidate_context.cognition,
                            opportunities=opportunity_cognition,
                            catalog=artifact_catalog,
                            custody=execution_custody,
                            wakeups=work_wakeups,
                            diagnostic=lambda event: diagnostic.emit(
                                event,
                                result_code="MODEL_PIPELINE",
                            ),
                        )
                        await model_pipeline.open()
                except ModelViolation:
                    model_pipeline = None
                    lifecycle.add_degradation("RUNTIME_MODEL_UNAVAILABLE")
                    diagnostic.emit(
                        "runtime.model.unavailable",
                        level=logging.WARNING,
                        result_code="MODEL_UNAVAILABLE",
                        reason_codes=("RUNTIME_MODEL_UNAVAILABLE",),
                    )
                if config.web.enabled:
                    try:
                        with configuration_consumption.consumer("web-search"):
                            web_search_pipeline = compose_web_search_pipeline(
                                prepared,
                                unit_of_work_factory=runtime_unit_of_work_factory,
                                evidence=evidence_module.write,
                                opportunity=opportunity_admission,
                                catalog=artifact_catalog,
                                custody=execution_custody,
                                diagnostic=lambda event: diagnostic.emit(
                                    event,
                                    result_code="WEB_SEARCH_CUSTODY",
                                ),
                            )
                            await web_search_pipeline.open()
                        with configuration_consumption.consumer("web-research"):
                            web_research_pipeline = (
                                compose_web_research_admission_pipeline(
                                    prepared,
                                    unit_of_work_factory=runtime_unit_of_work_factory,
                                    custody=web_search_pipeline,
                                    evidence=evidence_module.write,
                                    opportunity=opportunity_admission,
                                    catalog=artifact_catalog,
                                    diagnostic=lambda event: diagnostic.emit(
                                        event,
                                        result_code="WEB_RESEARCH_ADMISSION",
                                    ),
                                )
                            )
                            await web_research_pipeline.open()
                    except WebObservationViolation, WebResearchViolation:
                        if web_research_pipeline is not None:
                            await web_research_pipeline.close()
                            web_research_pipeline = None
                        if web_search_pipeline is not None:
                            await web_search_pipeline.close()
                        web_search_pipeline = None
                        configuration_consumption.release("web-search")
                        configuration_consumption.release("web-research")
                        diagnostic.emit(
                            "runtime.web_search.unavailable",
                            level=logging.WARNING,
                            result_code="WEB_SEARCH_UNAVAILABLE",
                        )
            else:
                lifecycle.add_degradation("RUNTIME_MODEL_UNAVAILABLE")
        except DatabaseViolation, RuntimeAuthorityViolation:
            diagnostic.emit(
                "runtime.authority.unavailable",
                level=logging.ERROR,
                result_code="AUTH_UNAVAILABLE",
                reason_codes=("RUNTIME_AUTHORITY_UNAVAILABLE",),
            )
            if observation_port is not None:
                await observation_port.close()
            if execution_custody is not None:
                await execution_custody.close()
            if runtime_unit_of_work_factory is not None:
                await runtime_unit_of_work_factory.close()
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        except RecoveryViolation as error:
            recovery_reasons = ("RUNTIME_RECOVERY_BLOCKED", error.code)
            diagnostic.emit(
                "runtime.recovery.failed",
                level=logging.ERROR,
                result_code="REC_FAILED",
                reason_codes=recovery_reasons,
            )
            if prompt_module is not None:
                await prompt_module.close()
            if mood_module is not None:
                await mood_module.close()
            if subject_state_module is not None:
                await subject_state_module.close()
            if authority is not None:
                await authority.release()
            if execution_custody is not None:
                await execution_custody.close()
            if runtime_unit_of_work_factory is not None:
                await runtime_unit_of_work_factory.close()
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        except (
            BrowserSessionViolation,
            CandidateViolation,
            ContextViolation,
            CreatorInputViolation,
            ActivityViolation,
            CreatorMaintenanceViolation,
            CreatorExportViolation,
            DataRightsViolation,
            CreatorPromptViolation,
            MemoryViolation,
            RelationshipViolation,
            SleepViolation,
            OtherHumanRecordViolation,
            LifeRecordQueryViolation,
            SceneQueryViolation,
            SubjectCommitViolation,
            ResponseViolation,
            EffectViolation,
            ExternalMessageViolation,
            LifeViolation,
        ) as error:
            diagnostic.emit(
                "runtime.creator_interface.unavailable",
                level=logging.ERROR,
                result_code="CREATOR_INTERFACE_UNAVAILABLE",
                reason_codes=(
                    "RUNTIME_CREATOR_INTERFACE_UNAVAILABLE",
                    error.code,
                ),
            )
            if interaction_module is not None:
                await interaction_module.close()
            if activity_module is not None:
                await activity_module.close()
            if exact_life_query_pipeline is not None:
                await exact_life_query_pipeline.close()
            if life_record_query is not None:
                await life_record_query.close()
            if other_human_record_query is not None:
                await other_human_record_query.close()
            if sleep_module is not None:
                await sleep_module.close()
            if relationship_module is not None:
                await relationship_module.close()
            if memory_module is not None:
                await memory_module.close()
            if material_module is not None:
                await material_module.close()
            if subject_state_module is not None:
                await subject_state_module.close()
            if mood_module is not None:
                await mood_module.close()
            if prompt_module is not None:
                await prompt_module.close()
            if data_rights_module is not None:
                await data_rights_module.close()
            if perception_module is not None:
                await perception_module.close()
            if qq_channel is not None:
                await qq_channel.close()
            if context_pipeline is not None:
                await context_pipeline.close()
            if context_embedding_pipeline is not None:
                await context_embedding_pipeline.close()
            if life_opportunity_pipeline is not None:
                await life_opportunity_pipeline.close()
            if model_pipeline is not None:
                await model_pipeline.close()
            if web_research_pipeline is not None:
                await web_research_pipeline.close()
            if web_search_pipeline is not None:
                await web_search_pipeline.close()
            if effect_pipeline is not None:
                await effect_pipeline.close()
            if codex_pipeline is not None:
                await codex_pipeline.close()
            if authority is not None:
                await authority.release()
            if observation_port is not None:
                await observation_port.close()
            if execution_custody is not None:
                await execution_custody.close()
            if runtime_unit_of_work_factory is not None:
                await runtime_unit_of_work_factory.close()
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        finally:
            if recovery_port is not None:
                await recovery_port.close()
    elif continuity is ContinuityState.UNBORN:
        lifecycle.mark_unborn()

    def background_task_failed(name: str, error: BaseException) -> None:
        error_code = getattr(error, "code", type(error).__name__)
        safe_error_code = "".join(
            character if character.isalnum() else "_"
            for character in str(error_code).lower()
        ).strip("_")
        if not safe_error_code:
            safe_error_code = "unknown"
        diagnostic.emit(
            f"runtime.background_worker.{name}.failed.{safe_error_code}",
            level=logging.ERROR,
            result_code="BACKGROUND_WORKER_FAILED",
            reason_codes=("RUNTIME_BACKGROUND_WORKER_FAILED",),
        )
        server.should_exit = True

    supervisor = RuntimeSupervisor(
        authority,
        on_task_failure=background_task_failed,
    )
    drain_timed_out = False

    async def _start_resources() -> None:
        if diagnostic.status.reason_code is not None:
            lifecycle.add_degradation(diagnostic.status.reason_code)
        if continuity is ContinuityState.UNBORN:
            snapshot = lifecycle.snapshot()
        else:
            subject_reasons = (
                ("RUNTIME_SUBJECT_STATE_INVALID",)
                if continuity is ContinuityState.INVALID and not database_reasons
                else ()
            )
            snapshot = lifecycle.complete_startup(
                (
                    *RUNTIME_BLOCKING_REASONS,
                    *database_reasons,
                    *subject_reasons,
                    *recovery_reasons,
                )
            )
        event_by_state = {
            "unborn": ("runtime.lifecycle.unborn", "LIFE_UNBORN", logging.INFO),
            "ready": ("runtime.lifecycle.ready", "LIFE_READY", logging.INFO),
            "degraded": (
                "runtime.lifecycle.degraded",
                "LIFE_DEGRADED",
                logging.WARNING,
            ),
            "blocked": (
                "runtime.lifecycle.blocked",
                "LIFE_BLOCKED",
                logging.WARNING,
            ),
        }
        event, result_code, level = event_by_state[snapshot.runtime_state.value]
        diagnostic.emit(
            event,
            level=level,
            result_code=result_code,
            reason_codes=snapshot.reason_codes,
        )
        if authority is not None:
            supervisor.start(
                heartbeat_loop(authority),
                name="runtime-authority-heartbeat",
                heartbeat=True,
            )
        if artifact_lifecycle is not None:
            supervisor.start(
                artifact_lifecycle.run(),
                name="artifact-lifecycle-worker",
            )
        if data_rights_module is not None:
            supervisor.start(
                data_rights_module.run(),
                name="data-rights-reconciliation",
            )
        if live_vision_retention is not None:
            supervisor.start(
                live_vision_retention.run(),
                name="live-vision-retention",
            )
        if vision_capture_router is not None:
            supervisor.start(
                vision_capture_router.run(),
                name="live-vision-capture-worker",
            )
        for source_kind, sink in vision_sinks.items():
            supervisor.start(
                sink.run_recognition_worker(),
                name=f"live-vision-{source_kind.value}-recognition-worker",
            )
        if observation_driver is not None:
            supervisor.start(
                observation_driver.run(),
                name="runtime-observability",
            )
        if mood_display is not None:
            supervisor.start(
                mood_display.run(),
                name="mood-display-adapter",
            )
        if context_pipeline is not None:
            supervisor.start(
                context_pipeline.run_selector(),
                name="context-opportunity-selector",
            )
            supervisor.start(
                context_pipeline.run_worker(),
                name="context-prepare-worker",
            )
        if context_embedding_pipeline is not None:
            supervisor.start(
                context_embedding_pipeline.run_worker(),
                name="context-embedding-worker",
            )
        if life_opportunity_pipeline is not None:
            supervisor.start(
                life_opportunity_pipeline.run(),
                name="life-opportunity-source",
            )
        if exact_life_query_pipeline is not None:
            supervisor.start(
                exact_life_query_pipeline.run_worker(),
                name="exact-life-query-worker",
            )
        if perception_module is not None:
            supervisor.start(
                perception_module.worker.run_worker(),
                name="external-content-worker",
            )
        if model_pipeline is not None:
            for index in range(config.model.concurrency):
                supervisor.start(
                    model_pipeline.run_worker(),
                    name=f"cognition-execute-worker-{index + 1}",
                )
        if web_search_pipeline is not None:
            if web_research_pipeline is not None:
                supervisor.start(
                    web_research_pipeline.run_worker(),
                    name="web-research-admission-worker",
                )
            for index in range(config.web.concurrency):
                supervisor.start(
                    web_search_pipeline.run_worker(),
                    name=f"web-search-worker-{index + 1}",
                )
        if effect_pipeline is not None:
            supervisor.start(
                effect_pipeline.run(),
                name="effect-registration-worker",
            )
        if qq_server is not None:
            supervisor.start(
                qq_server.serve(),
                name="qq-napcat-event-listener",
            )
        if codex_pipeline is not None and codex_availability.available:
            supervisor.start(
                codex_pipeline.run_worker(),
                name="codex-delegation-worker",
            )
        if admin_control is not None:
            await admin_control.start()

    async def started() -> None:
        try:
            await _start_resources()
        except BaseException:
            # Every successfully acquired task/resource is already present in the
            # composition ledger consumed by stopping(); startup failure must run
            # the same exhaustive fail-stop path as a background task failure.
            await stopping()
            raise

    async def stopping() -> None:
        nonlocal drain_timed_out
        failures: list[tuple[str, BaseException]] = []

        async def shutdown_step(name: str, operation: Callable[[], object]) -> None:
            try:
                result = operation()
                if inspect.isawaitable(result):
                    await result
            except BaseException as error:
                failures.append((name, error))
                diagnostic.emit(
                    f"runtime.shutdown.{name}.failed",
                    level=logging.ERROR,
                    result_code="RUNTIME_SHUTDOWN_STEP_FAILED",
                    reason_codes=("RUNTIME_SHUTDOWN_INCOMPLETE",),
                )

        def revoke_browser_sessions() -> None:
            assert browser_sessions is not None
            browser_sessions.revoke_all()
            diagnostic.emit(
                "creator.session.revoked_all",
                result_code="CREATOR_SESSION_REVOKED",
            )

        # Phase 1: close every new intake and claim boundary while authority is ACTIVE.
        if admin_control is not None:
            await shutdown_step("admin_control", admin_control.close)
        if qq_server is not None:
            await shutdown_step(
                "qq_intake", lambda: setattr(qq_server, "should_exit", True)
            )
        if creator_events is not None:
            await shutdown_step("creator_events", creator_events.close_active)
        if browser_sessions is not None:
            await shutdown_step("browser_sessions", revoke_browser_sessions)
        if live_voice_service is not None:
            await shutdown_step("live_voice_intake", live_voice_service.stop)
        for source_kind, service in live_vision_services.items():
            await shutdown_step(f"live_vision_{source_kind.value}_intake", service.stop)
        if observation_driver is not None:
            await shutdown_step("observation_claim", observation_driver.stop)
        await shutdown_step("lifecycle_drain", lifecycle.drain)
        diagnostic.emit("runtime.lifecycle.draining", result_code="LIFE_DRAINING")

        # Phase 2: signal every worker, then let the supervisor drain/cancel them.
        stop_operations = (
            (
                "perception",
                None if perception_module is None else perception_module.stop,
            ),
            ("context", None if context_pipeline is None else context_pipeline.stop),
            (
                "context_embedding",
                None
                if context_embedding_pipeline is None
                else context_embedding_pipeline.stop,
            ),
            (
                "life_opportunity",
                None
                if life_opportunity_pipeline is None
                else life_opportunity_pipeline.stop,
            ),
            (
                "exact_life_query",
                None
                if exact_life_query_pipeline is None
                else exact_life_query_pipeline.stop,
            ),
            ("model", None if model_pipeline is None else model_pipeline.stop),
            (
                "web_search",
                None if web_search_pipeline is None else web_search_pipeline.stop,
            ),
            (
                "web_research",
                None if web_research_pipeline is None else web_research_pipeline.stop,
            ),
            ("effect", None if effect_pipeline is None else effect_pipeline.stop),
            ("codex", None if codex_pipeline is None else codex_pipeline.stop),
            (
                "artifact",
                None if artifact_lifecycle is None else artifact_lifecycle.stop,
            ),
            (
                "data_rights",
                None if data_rights_module is None else data_rights_module.stop,
            ),
            (
                "vision_retention",
                None if live_vision_retention is None else live_vision_retention.stop,
            ),
        )
        for sink in vision_sinks.values():
            sink.stop_worker()
        if vision_capture_router is not None:
            vision_capture_router.stop()
        for name, operation in stop_operations:
            if operation is not None:
                await shutdown_step(f"{name}_stop", operation)
        if recovery_port is not None:
            await shutdown_step("conversation_end", recovery_port.end_interrupted_work)
        released = False
        try:
            released = await supervisor.drain(
                deadline_seconds=config.lifecycle.graceful_shutdown_seconds,
            )
        except BaseException as error:
            failures.append(("supervisor_drain", error))

        # Phase 3: independently close all resources; one failure never skips another.
        close_operations = (
            (
                "interaction",
                None if interaction_module is None else interaction_module.close,
            ),
            ("activity", None if activity_module is None else activity_module.close),
            (
                "other_human_records",
                None
                if other_human_record_query is None
                else other_human_record_query.close,
            ),
            ("sleep", None if sleep_module is None else sleep_module.close),
            (
                "relationship",
                None if relationship_module is None else relationship_module.close,
            ),
            ("memory", None if memory_module is None else memory_module.close),
            ("material", None if material_module is None else material_module.close),
            (
                "subject_state",
                None if subject_state_module is None else subject_state_module.close,
            ),
            ("mood", None if mood_module is None else mood_module.close),
            ("prompt", None if prompt_module is None else prompt_module.close),
            (
                "data_rights",
                None if data_rights_module is None else data_rights_module.close,
            ),
            ("context", None if context_pipeline is None else context_pipeline.close),
            (
                "context_embedding",
                None
                if context_embedding_pipeline is None
                else context_embedding_pipeline.close,
            ),
            (
                "life_opportunity",
                None
                if life_opportunity_pipeline is None
                else life_opportunity_pipeline.close,
            ),
            (
                "exact_life_query",
                None
                if exact_life_query_pipeline is None
                else exact_life_query_pipeline.close,
            ),
            (
                "perception",
                None if perception_module is None else perception_module.close,
            ),
            (
                "life_record_query",
                None if life_record_query is None else life_record_query.close,
            ),
            ("model", None if model_pipeline is None else model_pipeline.close),
            (
                "web_research",
                None if web_research_pipeline is None else web_research_pipeline.close,
            ),
            (
                "web_search",
                None if web_search_pipeline is None else web_search_pipeline.close,
            ),
            ("effect", None if effect_pipeline is None else effect_pipeline.close),
            ("qq_channel", None if qq_channel is None else qq_channel.close),
            ("codex", None if codex_pipeline is None else codex_pipeline.close),
        )
        for name, operation in close_operations:
            if operation is not None:
                await shutdown_step(f"{name}_close", operation)
        if authority is not None:
            diagnostic.emit(
                (
                    "runtime.authority.released"
                    if released
                    else "runtime.authority.release_deferred"
                ),
                level=logging.INFO if released else logging.WARNING,
                result_code=("AUTH_RELEASED" if released else "AUTH_RELEASE_DEFERRED"),
            )
        drain_timed_out = not released or bool(failures)
        await shutdown_step("lifecycle_stop", lifecycle.stop)
        diagnostic.emit("runtime.lifecycle.stopped", result_code="LIFE_STOPPED")
        diagnostic.close()

    async def heartbeat_loop(controller: RuntimeAuthorityController) -> None:
        suspended = False
        while True:
            if not suspended:
                await asyncio.sleep(config.runtime.heartbeat_seconds)
            try:
                snapshot = await controller.heartbeat_once()
            except RuntimeAuthorityViolation:
                diagnostic.emit(
                    "runtime.authority.lost",
                    level=logging.ERROR,
                    result_code="AUTH_LOST",
                    reason_codes=("RUNTIME_AUTHORITY_LOST",),
                )
                server.should_exit = True
                return
            if snapshot.state is LocalAuthorityState.SUSPENDED:
                suspended = True
                diagnostic.emit(
                    "runtime.authority.suspended",
                    level=logging.WARNING,
                    result_code="AUTH_SUSPENDED",
                    reason_codes=("RUNTIME_AUTHORITY_SUSPENDED",),
                )
            else:
                suspended = False
                diagnostic.emit(
                    "runtime.authority.heartbeat",
                    result_code="AUTH_HEARTBEAT",
                )

    def runtime_status() -> RuntimeStatusResponse:
        snapshot = lifecycle.snapshot()
        try:
            authority_state = (
                LocalAuthorityState.INACTIVE
                if authority is None
                else authority.snapshot().state
            )
        except RuntimeAuthorityViolation:
            authority_state = LocalAuthorityState.LOST
            server.should_exit = True
        admitted = (
            snapshot.readiness is Readiness.READY
            and authority_state is LocalAuthorityState.ACTIVE
        )
        status_reasons = list(snapshot.reason_codes)
        if authority_state is not LocalAuthorityState.ACTIVE:
            status_reasons.append("RUNTIME_AUTHORITY_NOT_ACTIVE")
        observation = (
            None if observation_driver is None else observation_driver.snapshot()
        )
        database_ready = (
            observation is not None and observation.get("status") == "available"
        )
        database_reason = (
            "DATABASE_OBSERVATION_UNAVAILABLE"
            if observation is None
            else str(
                observation.get("reason_code") or "DATABASE_OBSERVATION_UNAVAILABLE"
            )
        )
        database_reasons = [] if database_ready else [database_reason]
        return RuntimeStatusResponse(
            codex=CodexAvailabilityResponse(
                enabled=codex_availability.enabled,
                available=codex_availability.available,
                reason_code=codex_availability.reason_code,
            ),
            contract_version="1.0",
            environment_id=snapshot.environment_id,
            runtime_state=snapshot.runtime_state,
            readiness=Readiness.READY if admitted else Readiness.NOT_READY,
            authority_state=authority_state.value,
            reason_codes=list(dict.fromkeys(status_reasons)),
            components=[
                RuntimeComponentHealthResponse(
                    component="database",
                    state="ready" if database_ready else "unavailable",
                    reason_codes=database_reasons,
                ),
                RuntimeComponentHealthResponse(
                    component="runtime",
                    state=(
                        "ready"
                        if snapshot.runtime_state.value == "ready" and admitted
                        else "degraded"
                    ),
                    reason_codes=list(dict.fromkeys(status_reasons)),
                ),
                RuntimeComponentHealthResponse(
                    component="creator_web",
                    state="ready" if web_assets_error is None else "unavailable",
                    reason_codes=[]
                    if web_assets_error is None
                    else [web_assets_error.replace("-", "_")],
                ),
            ],
            observed_at=snapshot.observed_at,
        )

    async def qq_health_status() -> QQChannelHealthResponse:
        configured = qq_channel is not None
        enabled = qq_ingress is not None and qq_ingress.enabled
        if qq_channel is None:
            health = disabled_qq_health()
        else:
            health = compose_qq_health(
                await qq_channel.inspect_health(
                    expected_account_id=qq_channel.account_id
                ),
                ingress_ready=qq_server is not None and qq_server.started,
                environment_root=prepared.root,
            )
        return QQChannelHealthResponse(
            contract_version="1.0",
            projection_version="creator-channel-health.v2",
            channel="qq",
            driver="napcat",
            configured=configured,
            enabled=enabled,
            state="disabled" if configured and not enabled else health.state,
            ingress_ready=enabled and health.ingress_ready,
            api_reachable=health.api_reachable,
            account_online=health.account_online,
            account_matches=health.account_matches,
            webui_url=health.webui_url,
            observed_at=health.observed_at,
            reason_codes=[]
            if configured and not enabled
            else list(health.reason_codes),
        )

    async def qq_channel_control(action: str) -> QQChannelHealthResponse:
        if qq_ingress is not None:
            qq_ingress.enabled = action == "start"
        return await qq_health_status()

    async def live_voice_control(action: str) -> LiveVoiceStatusResponse:
        voice_config = config.voice
        voice_service = live_voice_service
        reasons: list[str] = []
        state = "disabled"
        input_label = None
        output_label = None
        if voice_config.input_device is not None:
            input_label = (
                f"{voice_config.input_device.host_api} / "
                f"{voice_config.input_device.name}"
            )
        if voice_config.output_device is not None:
            output_label = (
                f"{voice_config.output_device.host_api} / "
                f"{voice_config.output_device.name}"
            )
        if voice_config.enabled:
            try:
                devices = WasapiRawAudio.devices()
                input_config = voice_config.input_device
                output_config = voice_config.output_device
                input_found = input_config is not None and any(
                    item.host_api == input_config.host_api
                    and item.name == input_config.name
                    and item.input_channels > 0
                    for item in devices
                )
                output_found = output_config is not None and any(
                    item.host_api == output_config.host_api
                    and item.name == output_config.name
                    and item.output_channels > 0
                    for item in devices
                )
                if not input_found:
                    reasons.append("VOICE_INPUT_DEVICE_UNAVAILABLE")
                if not output_found:
                    reasons.append("VOICE_OUTPUT_DEVICE_UNAVAILABLE")
            except Exception:
                reasons.append("VOICE_AUDIO_UNAVAILABLE")
            if voice_service is None:
                reasons.append("VOICE_PIPELINE_UNAVAILABLE")
            if reasons:
                state = "unavailable"
            else:
                assert voice_service is not None
                try:
                    if action == "start":
                        await voice_service.start()
                    elif action == "stop":
                        await voice_service.stop()
                except LiveVoiceViolation as error:
                    reasons.append(error.code.replace("-", "_"))
                state = voice_service.status().value
                if voice_service.last_error is not None:
                    reasons.append(voice_service.last_error.replace("-", "_"))
        recent_turn = (
            None if voice_service is None else await voice_service.recent_turn()
        )
        return LiveVoiceStatusResponse(
            contract_version="1.0",
            projection_version="creator-live-voice-status.v2",
            state=state,
            enabled=voice_config.enabled,
            input_device=input_label,
            output_device=output_label,
            asr_ready=voice_service is not None and not reasons,
            llm_ready=voice_service is not None and not reasons,
            tts_ready=voice_service is not None and not reasons,
            recent_turn_ref=None if recent_turn is None else str(recent_turn.turn_id),
            recent_turn_status=None if recent_turn is None else recent_turn.status,
            playback_extent=(
                None if recent_turn is None else recent_turn.playback_extent.value
            ),
            frames_written=None if recent_turn is None else recent_turn.frames_written,
            last_error=(
                None
                if recent_turn is None or recent_turn.error_code is None
                else recent_turn.error_code.replace("-", "_")
            ),
            observed_at=(
                datetime.now(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            ),
            reason_codes=reasons,
        )

    async def admin_voice(action: str) -> dict[str, object]:
        return (await live_voice_control(action)).model_dump(mode="json")

    async def admin_vision(action: str, source: str | None) -> dict[str, object]:
        if action == "observe" and source is not None:
            return (await live_vision_observe(source, f"cli:{uuid7()}")).model_dump(
                mode="json"
            )
        return (await live_vision_control(action, source)).model_dump(mode="json")

    def _vision_observation_response(
        observation: VisualObservation,
    ) -> LiveVisionObservationResponse:
        return LiveVisionObservationResponse(
            projection_version="creator-live-vision-observation.v2",
            observation_id=str(observation.observation_id),
            source_kind=observation.source_kind.value,
            origin_kind=observation.origin_kind.value,
            trigger=observation.trigger.value,
            status=observation.status.value,
            registered_at=observation.registered_at.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            change_score=observation.change_score,
            summary=observation.summary,
            error_code=(
                None
                if observation.error_code is None
                else observation.error_code.replace("-", "_")
            ),
        )

    async def live_vision_observe(
        source_kind: str,
        idempotency_key: str,
    ) -> LiveVisionObservationResponse:
        try:
            kind = VisualSourceKind(source_kind)
        except ValueError:
            raise LiveVisionViolation(
                "VISION-SOURCE-KIND", "unknown visual source"
            ) from None
        service = live_vision_services.get(kind)
        if service is None:
            raise LiveVisionViolation(
                "VISION-PIPELINE-UNAVAILABLE", "vision pipeline is unavailable"
            )
        try:
            observation = await service.observe(
                origin_kind=ObservationOriginKind.CREATOR,
                idempotency_key=idempotency_key,
            )
        except RuntimeError as error:
            code = str(error)
            if code.startswith("VISION-"):
                raise LiveVisionViolation(code, "vision admission failed") from None
            raise
        return _vision_observation_response(observation)

    async def live_vision_observation(
        observation_id: UUID,
    ) -> LiveVisionObservationResponse | None:
        for sink in vision_sinks.values():
            observation = await sink.get_observation(observation_id)
            if observation is not None:
                return _vision_observation_response(observation)
        return None

    async def live_vision_control(
        action: str, selected_source: str | None
    ) -> LiveVisionStatusResponse:
        selected = None
        if selected_source is not None:
            try:
                selected = VisualSourceKind(selected_source)
            except ValueError:
                raise LiveVisionViolation(
                    "VISION-SOURCE-KIND", "unknown visual source"
                ) from None
        if action in {"start", "stop"} and selected is not None:
            service = live_vision_services.get(selected)
            if service is not None:
                if action == "start":
                    await service.start()
                else:
                    await service.stop()
        now = (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        source_responses: list[LiveVisionSourceStatusResponse] = []
        for kind, configured_source in (
            (VisualSourceKind.CAMERA, config.vision.camera),
            (VisualSourceKind.SCREEN, config.vision.screen),
        ):
            source_config: Any = configured_source
            service = live_vision_services.get(kind)
            snapshot = None if service is None else service.status()
            last_observation = None if snapshot is None else snapshot.last_observation
            identity = source_config.identity
            identity_label = None
            if identity is not None:
                identity_label = (
                    f"{identity.name} / {identity.usb_location_id}"
                    if kind is VisualSourceKind.CAMERA
                    else f"{identity.edid_name} / {identity.source_device_name}"
                )
            reasons: list[str] = []
            if source_config.enabled and service is None:
                reasons.append("VISION_PIPELINE_UNAVAILABLE")
            if snapshot is not None and snapshot.reason_code is not None:
                reasons.append(snapshot.reason_code.replace("-", "_"))
            source_responses.append(
                LiveVisionSourceStatusResponse(
                    contract_version="1.0",
                    projection_version="creator-live-vision-source-status.v3",
                    source_kind=kind.value,
                    state=(
                        "disabled"
                        if not source_config.enabled
                        else "unavailable"
                        if snapshot is None
                        else snapshot.state.value
                    ),
                    enabled=source_config.enabled,
                    expected_running=False
                    if snapshot is None
                    else snapshot.expected_running,
                    identity=identity_label,
                    capture_ready=snapshot is not None
                    and snapshot.last_frame_at is not None,
                    perception_ready=service is not None,
                    last_frame_at=None
                    if snapshot is None or snapshot.last_frame_at is None
                    else snapshot.last_frame_at.isoformat(
                        timespec="microseconds"
                    ).replace("+00:00", "Z"),
                    last_observation_at=None
                    if last_observation is None
                    else last_observation.registered_at.isoformat(
                        timespec="microseconds"
                    ).replace("+00:00", "Z"),
                    current_manual_observation_ref=str(last_observation.observation_id)
                    if last_observation is not None
                    and last_observation.trigger.value == "manual"
                    else None,
                    observations_last_hour=0
                    if snapshot is None
                    else snapshot.observations_last_hour,
                    hourly_limit=source_config.hourly_observation_limit,
                    observed_at=now,
                    reason_codes=reasons,
                )
            )
        return LiveVisionStatusResponse(
            contract_version="1.0",
            projection_version="creator-live-vision-status.v3",
            sources=source_responses,
            observed_at=now,
        )

    def live_vision_preview(source_kind: str) -> bytes | None:
        try:
            service = live_vision_services.get(VisualSourceKind(source_kind))
        except ValueError:
            return None
        return None if service is None else service.preview()

    def security_event(event: str) -> None:
        diagnostic.emit(event, result_code="CREATOR_SECURITY_EVENT")

    def admin_status() -> dict[str, object]:
        from armi_local_control.configuration.editing import configuration_digest

        snapshot = lifecycle.snapshot()
        configuration_values = config.model_dump(mode="json")
        result: dict[str, object] = {
            "runtime_state": snapshot.runtime_state.value,
            "instance_id": instance_id,
            "readiness": snapshot.readiness.value,
            "reason_codes": list(snapshot.reason_codes),
            "runtime_configuration_digest": configuration_digest(
                config.model_dump(mode="json")
            ),
            "configuration_sources": list(prepared.effective.applied_sources),
            "configuration_overrides": [
                {
                    "variable": name,
                    "path": list(path),
                    "value": configuration_values[path[0]][path[1]],
                }
                for name, path in prepared.effective.environment_overrides
            ],
            "configuration_assets": configuration_consumption.snapshot(),
        }
        if observation_driver is not None:
            result["observability"] = observation_driver.snapshot()
        return result

    def admin_drain() -> None:
        lifecycle.drain()
        for pipeline in (
            life_opportunity_pipeline,
            exact_life_query_pipeline,
            context_pipeline,
            context_embedding_pipeline,
            model_pipeline,
            web_search_pipeline,
            web_research_pipeline,
            effect_pipeline,
            codex_pipeline,
        ):
            if pipeline is not None:
                pipeline.stop()

    def admin_stop() -> None:
        if lifecycle.snapshot().runtime_state.value != "draining":
            raise RuntimeViolation(
                "ADMIN-CONTROL-NOT-DRAINED", "runtime is not drained"
            )
        server.should_exit = True

    async def admin_input(message: str, idempotency_key: str) -> dict[str, object]:
        if creator_input is None:
            raise RuntimeViolation(
                "ADMIN-CONTROL-INPUT-UNAVAILABLE", "creator intake is unavailable"
            )
        acceptance = await creator_input.accept(
            CreatorInputCommand(
                scene_key="default",
                message=message,
                idempotency_key=IdempotencyKey(idempotency_key),
                trace_id=TraceId(os.urandom(16).hex()),
            )
        )
        return {
            "interaction_id": str(acceptance.interaction_id),
            "evidence_id": str(acceptance.evidence_id),
            "opportunity_id": str(acceptance.opportunity_id),
            "newly_accepted": acceptance.newly_accepted,
        }

    def data_rights_result_wire(result: DataRightsOrderResult) -> dict[str, object]:
        return {
            "order_id": str(result.order_id),
            "requester_party_id": str(result.requester_party_id),
            "requester_kind": result.requester_kind.value,
            "order_kind": result.order_kind.value,
            "scope_kind": result.scope_kind.value,
            "status": result.status,
            "execution_status": result.execution_status.value,
            "effective_at": result.effective_at.to_wire(),
            "completed_at": (
                None if result.completed_at is None else result.completed_at.to_wire()
            ),
            "newly_created": result.newly_created,
        }

    def data_rights_detail_wire(detail: DataRightsOrderDetail) -> dict[str, object]:
        return {
            **data_rights_result_wire(detail.order),
            "items": [
                {
                    "item_id": str(item.item_id),
                    "target_kind": item.target_kind,
                    "required_action": item.required_action,
                    "result_status": item.result_status.value,
                    "retention_reason": item.retention_reason,
                    "created_at": item.created_at.to_wire(),
                    "completed_at": (
                        None
                        if item.completed_at is None
                        else item.completed_at.to_wire()
                    ),
                }
                for item in detail.items
            ],
        }

    async def admin_other_human(
        action: str, payload: dict[str, object]
    ) -> dict[str, object]:
        if other_human_input is None:
            raise RuntimeViolation(
                "ADMIN-CONTROL-OTHER-HUMAN-UNAVAILABLE",
                "other-human intake is unavailable",
            )
        trace_id = TraceId(os.urandom(16).hex())
        if action == "party_register" and set(payload) == {
            "party_key",
            "display_label",
        }:
            view = await other_human_input.register_party(
                RegisterOtherHumanPartyCommand(
                    OtherHumanPartyKey(str(payload["party_key"])),
                    str(payload["display_label"]),
                    "other_human",
                    trace_id,
                )
            )
            return {
                "party_id": str(view.party_id),
                "party_key": view.party_key.value,
                "display_label": view.display_label,
                "identity_assurance": view.identity_assurance,
            }
        if action == "scene_set" and set(payload) == {
            "party_key",
            "scene_key",
            "status",
        }:
            view = await other_human_input.set_scene(
                OtherHumanSceneCommand(
                    OtherHumanPartyKey(str(payload["party_key"])),
                    SceneKey(str(payload["scene_key"])),
                    SceneStatus(str(payload["status"])),
                    trace_id,
                )
            )
            return {
                "scene_id": str(view.scene_id),
                "party_id": str(view.party_id),
                "scene_key": view.scene_key.value,
                "status": view.status.value,
            }
        if action == "message_send" and set(payload) == {
            "party_key",
            "scene_key",
            "message",
            "idempotency_key",
        }:
            accepted = await other_human_input.accept(
                OtherHumanInputCommand(
                    OtherHumanPartyKey(str(payload["party_key"])),
                    SceneKey(str(payload["scene_key"])),
                    str(payload["message"]),
                    IdempotencyKey(str(payload["idempotency_key"])),
                    trace_id,
                )
            )
            return {
                "party_id": str(accepted.party_id),
                "scene_id": str(accepted.scene_id),
                "interaction_id": str(accepted.interaction_id.value),
                "evidence_id": str(accepted.evidence_id),
                "opportunity_id": str(accepted.opportunity_id),
                "newly_accepted": accepted.newly_accepted,
            }
        orders = None if data_rights_module is None else data_rights_module.orders
        if orders is None:
            raise RuntimeViolation(
                "ADMIN-CONTROL-DATA-RIGHTS-UNAVAILABLE",
                "data-rights orders are unavailable",
            )
        party_key = OtherHumanPartyKey(str(payload.get("party_key", "")))
        if action == "data_rights_request" and set(payload) == {
            "party_key",
            "order_kind",
            "idempotency_key",
        }:
            result = await orders.request_other_human(
                party_key,
                DataRightsOrderCommand(
                    DataRightsOrderKind(str(payload["order_kind"])),
                    IdempotencyKey(str(payload["idempotency_key"])),
                    trace_id,
                ),
            )
            return data_rights_result_wire(result)
        if action == "data_rights_list" and set(payload) == {"party_key"}:
            details = await orders.list_other_human(party_key)
            return {"orders": [data_rights_detail_wire(item) for item in details]}
        if action == "data_rights_get" and set(payload) == {
            "party_key",
            "order_id",
        }:
            detail = await orders.detail_other_human(
                party_key, UUID(str(payload["order_id"]))
            )
            return {
                "order": None if detail is None else data_rights_detail_wire(detail)
            }
        raise RuntimeViolation(
            "ADMIN-CONTROL-OTHER-HUMAN-INPUT",
            "other-human control input is invalid",
        )

    async def admin_data_deletion(arguments: dict[str, Any]) -> dict[str, Any]:
        orders = None if data_rights_module is None else data_rights_module.orders
        if orders is None:
            raise RuntimeViolation(
                "ADMIN-CONTROL-DATA-RIGHTS-UNAVAILABLE",
                "data-rights orders are unavailable",
            )
        action = arguments.get("action")
        expected = (
            {"action", "party_key"}
            if action == "preview"
            else {"action", "party_key", "idempotency_key"}
            if action == "reconcile"
            else {"action", "party_key", "scope_digest", "idempotency_key"}
        )
        if (
            action not in {"preview", "apply", "reconcile"}
            or set(arguments) != expected
        ):
            raise RuntimeViolation(
                "ADMIN-CONTROL-DATA-RIGHTS-INPUT", "invalid deletion request"
            )
        key = (
            None
            if arguments["party_key"] is None
            else OtherHumanPartyKey(arguments["party_key"])
        )
        if action == "reconcile":
            found = await orders.find_deletion_request(
                key, IdempotencyKey(arguments["idempotency_key"])
            )
            return {"order": None if found is None else data_rights_result_wire(found)}
        if action == "preview":
            preview = await orders.preview_deletion(key)
            return {
                "party_id": str(preview.party_id),
                "scope_digest": preview.scope_digest.value,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                "scope": "party_local_data",
                "target_count": len(preview.targets),
                "targets": [
                    {
                        "kind": item.kind,
                        "id": str(item.ref),
                        "action": item.required_action,
                        "retention_reason": item.retention_reason,
                        "owner": item.responsible_owner,
                    }
                    for item in preview.targets
                ],
            }
        command = DataRightsOrderCommand(
            DataRightsOrderKind.DELETE_RELATED,
            IdempotencyKey(arguments["idempotency_key"]),
            TraceId(uuid7().hex),
            Digest(arguments["scope_digest"]),
        )
        result = (
            await orders.request_creator(command)
            if key is None
            else await orders.request_other_human(key, command)
        )
        return data_rights_result_wire(result)

    app = create_runtime_app(
        creator_media=None
        if media_uploads is None or interaction_module is None
        else CreatorMedia(media_uploads, interaction_module.creator_media),
        media_uploads=media_uploads,
        machine_environment_root=prepared.root,
        machine_environment_id=config.environment.environment_id,
        machine_creator_party_id=None
        if creator_context is None
        else creator_context.party_id,
        readiness=lambda: runtime_status().readiness,
        runtime_status=runtime_status,
        qq_channel_health=qq_health_status,
        qq_channel_control=qq_channel_control,
        live_voice_control=live_voice_control,
        live_vision_control=live_vision_control,
        live_vision_observe=live_vision_observe,
        live_vision_observation=live_vision_observation,
        live_vision_preview=live_vision_preview,
        assets=assets,
        browser_sessions=browser_sessions,
        creator_scenes=creator_scenes,
        scene_timeline_query=scene_timeline_query,
        creator_activity_query=(
            None if activity_module is None else activity_module.read
        ),
        life_record_query=life_record_query,
        other_human_record_query=other_human_record_query,
        creator_life_material_query=(
            None if material_module is None else material_module.read
        ),
        creator_memory_query=(None if memory_module is None else memory_module.read),
        creator_maintenance_query=(None if sleep_module is None else sleep_module.read),
        creator_relationship_query=creator_relationship_query,
        creator_prompt=None if prompt_module is None else prompt_module.creator,
        creator_export=(
            None if data_rights_module is None else data_rights_module.exports
        ),
        data_rights=(None if data_rights_module is None else data_rights_module.orders),
        creator_emergency_wake=life_opportunity_pipeline,
        creator_events=creator_events,
        creator_input=creator_input,
        creator_operations=creator_operations,
        subject_summary=subject_summary_provider,
        effect_ledger=effect_pipeline,
        codex_task_admission=(
            codex_pipeline.task_sources if codex_pipeline is not None else None
        ),
        expected_authority=f"{config.creator.bind_host}:{config.creator.port}",
        request_body_max_bytes=config.creator.request_body_max_bytes,
        request_body_timeout_seconds=config.http.body_timeout_seconds,
        request_header_max_bytes=config.http.header_max_bytes,
        request_header_max_count=config.http.header_max_count,
        on_started=started,
        on_stopping=stopping,
        on_security_event=security_event,
    )
    server = _RuntimeServer(
        uvicorn.Config(
            app,
            host=config.creator.bind_host,
            port=config.creator.port,
            workers=1,
            proxy_headers=False,
            forwarded_allow_ips="",
            access_log=False,
            log_level="warning",
            log_config=None,
            server_header=False,
            limit_concurrency=config.http.connection_limit,
            backlog=config.http.backlog,
            timeout_keep_alive=config.http.keepalive_seconds,
            h11_max_incomplete_event_size=config.http.header_max_bytes,
            timeout_graceful_shutdown=config.lifecycle.graceful_shutdown_seconds,
        )
    )
    if qq_channel is not None:
        qq_ingress = _SwitchableIngress(qq_channel.event_app)
        qq_server = _RuntimeServer(
            uvicorn.Config(
                qq_ingress,
                host="127.0.0.1",
                port=qq_channel.event_port,
                workers=1,
                proxy_headers=False,
                forwarded_allow_ips="",
                access_log=False,
                log_level="warning",
                log_config=None,
                server_header=False,
                limit_concurrency=config.http.connection_limit,
                backlog=config.http.backlog,
                timeout_keep_alive=config.http.keepalive_seconds,
                h11_max_incomplete_event_size=config.http.header_max_bytes,
                timeout_graceful_shutdown=(config.lifecycle.graceful_shutdown_seconds),
            )
        )
    control_incarnation = load_admin_control_incarnation(
        prepared.root,
        str(config.environment.environment_id),
    )
    if control_incarnation is not None:
        test_controls_enabled = False
        if runtime_unit_of_work_factory is not None:
            async with runtime_unit_of_work_factory.unit_of_work(
                read_only=True
            ) as control_unit:
                control_environment = await (
                    await control_unit.transaction.execute(
                        "SELECT environment_kind,test_controls_enabled FROM armi.deployment_environments WHERE environment_id=%s AND incarnation=%s",
                        (config.environment.environment_id, control_incarnation),
                    )
                ).fetchone()
                test_controls_enabled = (
                    control_environment is not None
                    and control_environment[0] in {"system_test", "acceptance"}
                    and control_environment[1] is True
                )
        admin_control = RuntimeAdminControlServer(
            test_controls_enabled=test_controls_enabled,
            run_root=prepared.root / "run" / "admin-control",
            environment_id=str(config.environment.environment_id),
            incarnation=control_incarnation,
            instance_id=instance_id,
            on_status=admin_status,
            on_drain=admin_drain,
            on_stop=admin_stop,
            on_input=admin_input if creator_input is not None else None,
            on_other_human=(
                admin_other_human if other_human_input is not None else None
            ),
            on_voice=admin_voice,
            on_data_deletion=admin_data_deletion,
            on_vision=admin_vision,
        )
    try:
        await server.serve()
    except SystemExit:
        if server.started and server.should_exit:
            return EXIT_GRACEFUL_TIMEOUT if server.force_exit else EXIT_GRACEFUL
        if lifecycle.snapshot().runtime_state.value != "stopped":
            await stopping()
        return EXIT_LISTENER_FAILURE
    except OSError:
        if server.started and server.should_exit:
            return EXIT_GRACEFUL_TIMEOUT if server.force_exit else EXIT_GRACEFUL
        if lifecycle.snapshot().runtime_state.value != "stopped":
            await stopping()
        return EXIT_LISTENER_FAILURE
    finally:
        if interaction_module is not None:
            await interaction_module.close()
        if activity_module is not None:
            await activity_module.close()
        if exact_life_query_pipeline is not None:
            await exact_life_query_pipeline.close()
        if life_record_query is not None:
            await life_record_query.close()
        if other_human_record_query is not None:
            await other_human_record_query.close()
        if sleep_module is not None:
            await sleep_module.close()
        if relationship_module is not None:
            await relationship_module.close()
        if memory_module is not None:
            await memory_module.close()
        if material_module is not None:
            await material_module.close()
        if subject_state_module is not None:
            await subject_state_module.close()
        if mood_module is not None:
            await mood_module.close()
        if prompt_module is not None:
            await prompt_module.close()
        if data_rights_module is not None:
            await data_rights_module.close()
        if context_pipeline is not None:
            await context_pipeline.close()
        if life_opportunity_pipeline is not None:
            await life_opportunity_pipeline.close()
        if effect_pipeline is not None:
            await effect_pipeline.close()
        if qq_channel is not None:
            await qq_channel.close()
        if codex_pipeline is not None:
            await codex_pipeline.close()
        if web_search_pipeline is not None:
            await web_search_pipeline.close()
        if observation_port is not None:
            await observation_port.close()
        if execution_custody is not None:
            await execution_custody.close()
        if runtime_unit_of_work_factory is not None:
            await runtime_unit_of_work_factory.close()
        if authority_port is not None:
            await authority_port.close()
    if server.force_exit:
        return EXIT_GRACEFUL_TIMEOUT
    if drain_timed_out:
        return EXIT_GRACEFUL_TIMEOUT
    if not server.started:
        return EXIT_LISTENER_FAILURE
    return EXIT_GRACEFUL


def run_runtime(
    prepared: PreparedEnvironment,
    *,
    creator_web_resources: Path | None = None,
    instance_uuid: UUID | None = None,
) -> int:
    """Run exactly one process-local Runtime; no reload or worker discovery."""

    try:
        consumption = ConfigurationConsumption(prepared.root)
        return asyncio.run(
            _serve(
                prepared,
                creator_web_resources=creator_web_resources,
                configuration_consumption=consumption,
                instance_uuid=instance_uuid,
            ),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    except KeyboardInterrupt:
        return EXIT_GRACEFUL
    except RuntimeViolation:
        raise
    except AssetViolation:
        return EXIT_LISTENER_FAILURE
    except OSError:
        return EXIT_LISTENER_FAILURE


__all__ = (
    "EXIT_GRACEFUL",
    "EXIT_GRACEFUL_TIMEOUT",
    "EXIT_LISTENER_FAILURE",
    "run_runtime",
)
