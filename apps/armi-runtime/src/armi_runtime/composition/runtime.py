"""Explicit S009 Runtime composition root and Uvicorn process ownership."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import selectors
import signal
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import uvicorn
from armi_activity.api import ActivityViolation
from armi_adapter_esp32_display import (
    MoodDisplayAdapter,
    MoodDisplayViolation,
    load_mood_display_config,
)
from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import LifeViolation
from armi_attention.bootstrap import (
    bootstrap_opportunity_owner,
    bootstrap_opportunity_sleep,
)
from armi_capability.api import CapabilityViolation
from armi_codex.api import CodexDelegationViolation, CodexRuntimePort
from armi_codex.bootstrap import bootstrap_codex_commit
from armi_cognition.bootstrap import (
    bootstrap_cognition_context,
    bootstrap_cognition_owner,
)
from armi_context.api import ContextViolation
from armi_data_rights.api import CreatorExportViolation, DataRightsViolation
from armi_effect.api import EffectViolation
from armi_effect.bootstrap import bootstrap_effect_operation_read
from armi_experience.bootstrap import bootstrap_experience_owner
from armi_expression.api import ResponseViolation
from armi_interaction.api import (
    CreatorInputCommand,
    CreatorInputViolation,
    ExternalMessageViolation,
    SceneQueryViolation,
)
from armi_kernel.application import (
    CandidateViolation,
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
from armi_kernel.contracts import IdempotencyKey, TraceId
from armi_live_vision.api import (
    CameraDevice,
    CameraFormat,
    LiveVisionRuntimePort,
    LiveVisionViolation,
)
from armi_live_vision.bootstrap import (
    compose_live_vision,
    compose_visual_observation_sink,
)
from armi_live_voice.api import LiveVoiceRuntimePort
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

from armi_runtime.adapters.model.external_content import (
    VolcengineArkExternalContentRecognizer,
    load_external_recognition_binding,
)
from armi_runtime.adapters.persistence.runtime_observability import (
    RuntimeObservationError,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio
from armi_runtime.application.action_lifecycle import RuntimeCodexGrantActivation
from armi_runtime.application.cognition_cycle import RuntimeCognitionState
from armi_runtime.application.creator_timeline import CreatorTimelineProjectionAssembler
from armi_runtime.application.life_opportunity import RuntimeLifeOpportunityFacts
from armi_runtime.application.maintenance import RuntimeSleepFacts
from armi_runtime.application.subject_summary import RuntimeSubjectSummaryAssembler
from armi_runtime.interfaces.browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
)
from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.creator_contract import (
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    QQChannelHealthResponse,
    RuntimeStatusResponse,
)
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
from .creator_session import compose_browser_sessions, derive_timeline_cursor_key
from .database import (
    ContinuityState,
    DatabaseViolation,
    compose_activity_module,
    compose_candidate_validation_pipeline,
    compose_capability_policy,
    compose_codex_pipeline,
    compose_codex_read_ports,
    compose_cognition_exact_life_query,
    compose_context_candidate_read,
    compose_context_embedding_pipeline,
    compose_context_pipeline,
    compose_context_projection_invalidation,
    compose_creator_operation_query,
    compose_data_rights_core,
    compose_data_rights_module,
    compose_effect_grant_cancellation,
    compose_effect_owner_context,
    compose_effect_registration_pipeline,
    compose_evidence_module,
    compose_exact_life_query_pipeline,
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
    compose_response_admission_pipeline,
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
from .napcat_process import compose_qq_health, disabled_qq_health
from .owner_roster import compose_runtime_owner_roster
from .qq_channel import QQChannelBinding, compose_qq_channel
from .runtime_errors import RuntimeViolation
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


async def _serve(
    prepared: PreparedEnvironment,
    *,
    creator_web_resources: Path | None,
) -> int:
    config = prepared.effective.config
    try:
        mood_display_config = load_mood_display_config(prepared.root)
    except MoodDisplayViolation as error:
        raise RuntimeViolation(
            error.code, "mood display configuration is invalid"
        ) from error
    instance_uuid = uuid7()
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
    assets = (
        StaticAssetStore.load_packaged()
        if creator_web_resources is None
        else StaticAssetStore.load_directory(creator_web_resources)
    )
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
    recovery_port = None
    runtime_unit_of_work_factory: PostgreSQLUnitOfWorkFactory | None = None
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
    subject_summary_provider: RuntimeSubjectSummaryAssembler | None = None
    creator_operations = None
    other_human_input = None
    external_message_input = None
    perception_module = None
    qq_channel: QQChannelBinding | None = None
    qq_server: _RuntimeServer | None = None
    other_human_record_query = None
    life_opportunity_pipeline = None
    context_pipeline = None
    context_embedding_pipeline = None
    model_pipeline = None
    candidate_pipeline = None
    subject_commit_pipeline = None
    capability_policy = None
    response_pipeline = None
    effect_pipeline = None
    web_search_pipeline: WebObservationRuntimePort | None = None
    web_research_pipeline: WebResearchRuntimePort | None = None
    codex_pipeline: CodexRuntimePort | None = None
    admin_control: RuntimeAdminControlServer | None = None
    work_wakeups = WorkWakeupBus()
    live_voice_service: LiveVoiceRuntimePort | None = None
    live_vision_service: LiveVisionRuntimePort | None = None

    def inject_admin_fault(name: str) -> None:
        if admin_control is not None:
            admin_control.trigger_fault(name)

    if continuity is ContinuityState.BORN:
        try:
            subject_state_module = compose_subject_state_module()
            await subject_state_module.open()
            mood_module = compose_mood_module()
            await mood_module.open()
            authority_port = compose_runtime_authority(prepared)
            await authority_port.open()
            authority = RuntimeAuthorityController(
                authority_port,
                lease_seconds=config.runtime.lease_seconds,
            )
            acquired = await authority.acquire(RuntimeInstanceId(instance_uuid))
            diagnostic.emit(
                "runtime.authority.acquired",
                result_code="AUTH_ACQUIRED",
            )
            if acquired.fence.runtime_instance_id.value != instance_uuid:
                raise RuntimeAuthorityViolation("AUTH-INSTANCE-MISMATCH")
            await authority.heartbeat_once()
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
            effect_owner = bootstrap_effect_operation_read()
            interaction_identity = compose_interaction_identity()
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
                subject_state=subject_state_module.read,
            )
            await activity_module.open()
            relationship_module = compose_relationship_module(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                creator_party_id=creator_context.party_id,
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
                runtime_facts=RuntimeSleepFacts(
                    cognition=cognition_operation,
                    effects=effect_owner,
                ),
                opportunities=opportunity_sleep,
            )
            await sleep_module.open()
            context_projection_invalidation = compose_context_projection_invalidation()
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
                visibility=data_rights_core.visibility,
                identity=interaction_identity,
                catalog=artifact_catalog,
                timeline_projections=timeline_projections,
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
                notifier=creator_events,
            )
            await data_rights_module.open()
            expression_module = compose_expression_module(
                relationship_read=relationship_module.read,
                relationship_policy=relationship_module.policy,
                interaction_routes=interaction_module.effect_routes,
                interaction_scenes=interaction_module.scene_transitions,
            )
            effect_registration_context, codex_artifacts = compose_effect_owner_context(
                expression=expression_module.intents,
                interaction=interaction_module.effect_routes,
                codex=codex_reads,
                catalog=artifact_catalog,
            )
            scene_timeline_query = interaction_module.scene_timeline
            creator_scenes = interaction_module.creator_scenes
            creator_input = interaction_module.creator_input
            subject_summary_provider = RuntimeSubjectSummaryAssembler(
                runtime_unit_of_work_factory,
                subject_id=authority.require_writable().subject_id,
                subject_state=subject_state_module.read,
            )
            other_human_input = interaction_module.other_human_input
            external_message_input = interaction_module.external_message_input
            effect_grant_cancellation = compose_effect_grant_cancellation()
            capability_policy = compose_capability_policy(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                cursor_key=derive_timeline_cursor_key(prepared),
                effect_cancellation=effect_grant_cancellation,
                codex_activation=RuntimeCodexGrantActivation(expression_module.intents),
                notifier=creator_events,
            )
            await capability_policy.open()
            creator_operations = compose_creator_operation_query(
                unit_of_work_factory=runtime_unit_of_work_factory,
                creator_party_id=creator_context.party_id,
                interaction=interaction_module.creator_transaction,
                evidence=evidence_module.read,
                expression=expression_module.intents,
                capability=capability_policy.operations,
                codex=codex_reads.task_sources,
                codex_executions=codex_reads.executions,
                opportunity=opportunity_owner,
                cognition=cognition_owner,
                effect=effect_owner,
            )
            qq_channel = await compose_qq_channel(
                prepared,
                input_port=external_message_input,
            )
            if qq_channel is not None:
                try:
                    perception_module = compose_perception_module(
                        prepared,
                        unit_of_work_factory=runtime_unit_of_work_factory,
                        fetch=qq_channel.media_fetch,
                        evidence=evidence_module.write,
                        evidence_read=evidence_module.read,
                        interaction=interaction_module.perception,
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
            if config.vision.enabled and config.vision.device is not None:
                model_locator = config.secret_locators.get("model.ark_api_key")
                if model_locator is not None:
                    try:
                        recognition_binding = load_external_recognition_binding(
                            runtime_config_path("model-bindings.yaml")
                        )
                        vision_device = CameraDevice(
                            config.vision.device.name,
                            config.vision.device.device_path,
                            config.vision.device.usb_location_id,
                        )
                        vision_sink = compose_visual_observation_sink(
                            factory=runtime_unit_of_work_factory,
                            storage=ContentAddressedArtifactStore(
                                prepared.data_root / "artifacts",
                                max_object_bytes=config.artifacts.max_object_bytes,
                            ),
                            catalog=artifact_catalog,
                            recognizer=VolcengineArkExternalContentRecognizer(
                                credential_port=prepared.credential_port,
                                locator=model_locator,
                                binding=recognition_binding.ark,
                            ),
                            attempts=bootstrap_visual_recognition_attempts(),
                            evidence=evidence_module.write,
                            opportunity=opportunity_admission,
                            subject_id=authority.require_writable().subject_id,
                            device=vision_device,
                            retention=timedelta(
                                seconds=config.vision.frame_retention_seconds
                            ),
                        )
                        live_vision_service = compose_live_vision(
                            camera=DirectShowUsbCamera(),
                            sink=vision_sink,
                            device=vision_device,
                            format=CameraFormat(
                                config.vision.width,
                                config.vision.height,
                                float(config.vision.fps),
                            ),
                            hourly_limit=config.vision.hourly_observation_limit,
                            automatic_cooldown=timedelta(
                                seconds=config.vision.automatic_cooldown_seconds
                            ),
                            periodic_refresh=timedelta(
                                seconds=config.vision.periodic_refresh_seconds
                            ),
                            reconnect=timedelta(
                                seconds=config.vision.reconnect_seconds
                            ),
                            change_threshold=config.vision.change_threshold,
                            stable_change_samples=config.vision.stable_change_samples,
                        )
                        if config.vision.auto_start:
                            await live_vision_service.start()
                    except ValueError, ModelViolation:
                        live_vision_service = None
            life_opportunity_pipeline = compose_life_opportunity_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                facts=RuntimeLifeOpportunityFacts(
                    activities=activity_module.read,
                    capabilities=capability_policy.operations,
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
                capability_read=capability_policy.read,
                codex_read=codex_reads.task_sources,
                codex_context=codex_reads.context,
                cognition_context=cognition_context,
                evidence_read=evidence_module.read,
                interaction_context=interaction_module.context_read,
                interaction_cognition=interaction_module.cognition_read,
                opportunity_cognition=opportunity_cognition,
                runtime_subjects=runtime_cognition_state,
                web_context=web_context,
                expression_read=expression_module.intents,
                effect_read=effect_owner,
                data_rights=data_rights_module.cognition,
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
            candidate_pipeline = compose_candidate_validation_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
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
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CANDIDATE_PIPELINE",
                ),
            )
            await candidate_pipeline.open()
            subject_commit_pipeline = compose_subject_commit_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                activity_cognition=activity_module.cognition,
                activity_commit=activity_module.commit,
                capability_commit=capability_policy.commit,
                capability_read=capability_policy.read,
                codex_commit=bootstrap_codex_commit(
                    codex_reads.task_sources,
                    expression_module.commit,
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
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="SUBJECT_COMMIT_PIPELINE",
                ),
                fault_injector=inject_admin_fault,
            )
            await subject_commit_pipeline.open()
            response_pipeline = compose_response_admission_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                expression=expression_module.admission,
                capability=capability_policy.admission,
                data_rights=data_rights_module.effect_gate,
                catalog=artifact_catalog,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="RESPONSE_ADMISSION",
                ),
            )
            await response_pipeline.open()
            effect_pipeline = compose_effect_registration_pipeline(
                prepared,
                unit_of_work_factory=runtime_unit_of_work_factory,
                authorization=capability_policy.authorization,
                intents=expression_module.intents,
                effect_links=expression_module.effect_links,
                registration_context=effect_registration_context,
                codex_artifacts=codex_artifacts,
                routes=interaction_module.effect_routes,
                interaction_delivery=interaction_module.effect_delivery,
                notifier=creator_events,
                wakeups=work_wakeups,
                diagnostic=lambda event: diagnostic.emit(
                    event, result_code="EFFECT_REGISTRATION"
                ),
                fault_injector=inject_admin_fault,
                external_message_adapter=(
                    None if qq_channel is None else qq_channel.effect_adapter
                ),
            )
            await effect_pipeline.open()
            if "codex.auth_json" in config.secret_locators:
                try:
                    codex_pipeline = compose_codex_pipeline(
                        prepared,
                        unit_of_work_factory=runtime_unit_of_work_factory,
                        creator_party_id=creator_context.party_id,
                        creator_input=interaction_module.creator_transaction,
                        evidence=evidence_module.write,
                        evidence_read=evidence_module.read,
                        identity=interaction_module.identity,
                        opportunity=opportunity_admission,
                        dispatch_authorization=(
                            capability_policy.dispatch_authorization
                        ),
                        expression=expression_module.intents,
                        sources=codex_reads.task_sources,
                        catalog=artifact_catalog,
                        notifier=creator_events,
                        diagnostic=lambda event: diagnostic.emit(
                            event, result_code="CODEX_DELEGATION"
                        ),
                    )
                    await codex_pipeline.open()
                except CodexDelegationViolation:
                    codex_pipeline = None
                    lifecycle.add_degradation("RUNTIME_CODEX_UNAVAILABLE")
                    diagnostic.emit(
                        "runtime.codex.unavailable",
                        level=logging.WARNING,
                        result_code="CODEX_UNAVAILABLE",
                    )
            if config.model.semantic_recall_enabled:
                try:
                    context_embedding_pipeline = compose_context_embedding_pipeline(
                        prepared,
                        unit_of_work_factory=runtime_unit_of_work_factory,
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
                    model_pipeline = compose_model_pipeline(
                        prepared,
                        unit_of_work_factory=runtime_unit_of_work_factory,
                        context=candidate_context.cognition,
                        opportunities=opportunity_cognition,
                        catalog=artifact_catalog,
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
                        web_search_pipeline = compose_web_search_pipeline(
                            prepared,
                            unit_of_work_factory=runtime_unit_of_work_factory,
                            evidence=evidence_module.write,
                            opportunity=opportunity_admission,
                            catalog=artifact_catalog,
                            diagnostic=lambda event: diagnostic.emit(
                                event,
                                result_code="WEB_SEARCH_CUSTODY",
                            ),
                        )
                        await web_search_pipeline.open()
                        web_research_pipeline = compose_web_research_admission_pipeline(
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
                        await web_research_pipeline.open()
                    except WebObservationViolation, WebResearchViolation:
                        if web_research_pipeline is not None:
                            await web_research_pipeline.close()
                            web_research_pipeline = None
                        if web_search_pipeline is not None:
                            await web_search_pipeline.close()
                        web_search_pipeline = None
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
            if runtime_unit_of_work_factory is not None:
                await runtime_unit_of_work_factory.close()
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        except (
            BrowserSessionViolation,
            CandidateViolation,
            CapabilityViolation,
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
            if candidate_pipeline is not None:
                await candidate_pipeline.close()
            if subject_commit_pipeline is not None:
                await subject_commit_pipeline.close()
            if response_pipeline is not None:
                await response_pipeline.close()
            if effect_pipeline is not None:
                await effect_pipeline.close()
            if codex_pipeline is not None:
                await codex_pipeline.close()
            if capability_policy is not None:
                await capability_policy.close()
            if authority is not None:
                await authority.release()
            if observation_port is not None:
                await observation_port.close()
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

    async def started() -> None:
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
                    name=f"model-invoke-worker-{index + 1}",
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
        if candidate_pipeline is not None:
            supervisor.start(
                candidate_pipeline.run_worker(),
                name="candidate-validation-worker",
            )
        if subject_commit_pipeline is not None:
            supervisor.start(
                subject_commit_pipeline.run_worker(),
                name="subject-commit-worker",
            )
        if response_pipeline is not None:
            supervisor.start(
                response_pipeline.run_worker(),
                name="response-admission-worker",
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
        if codex_pipeline is not None:
            supervisor.start(
                codex_pipeline.run_worker(),
                name="codex-delegation-worker",
            )
        if capability_policy is not None:
            supervisor.start(
                capability_policy.run_expiry_reconciler(),
                name="capability-grant-expiry",
            )
        if admin_control is not None:
            await admin_control.start()

    async def stopping() -> None:
        nonlocal drain_timed_out
        if admin_control is not None:
            await admin_control.close()
        if qq_server is not None:
            qq_server.should_exit = True
        if observation_driver is not None:
            observation_driver.stop()
        lifecycle.drain()
        diagnostic.emit("runtime.lifecycle.draining", result_code="LIFE_DRAINING")
        if creator_events is not None:
            await creator_events.close_active()
        if browser_sessions is not None:
            browser_sessions.revoke_all()
            diagnostic.emit(
                "creator.session.revoked_all",
                result_code="CREATOR_SESSION_REVOKED",
            )
        if interaction_module is not None:
            await interaction_module.close()
        if activity_module is not None:
            await activity_module.close()
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
            perception_module.stop()
        if live_vision_service is not None:
            await live_vision_service.stop()
        if context_pipeline is not None:
            context_pipeline.stop()
        if context_embedding_pipeline is not None:
            context_embedding_pipeline.stop()
        if life_opportunity_pipeline is not None:
            life_opportunity_pipeline.stop()
        if exact_life_query_pipeline is not None:
            exact_life_query_pipeline.stop()
        if model_pipeline is not None:
            model_pipeline.stop()
        if web_search_pipeline is not None:
            web_search_pipeline.stop()
        if web_research_pipeline is not None:
            web_research_pipeline.stop()
        if candidate_pipeline is not None:
            candidate_pipeline.stop()
        if subject_commit_pipeline is not None:
            subject_commit_pipeline.stop()
        if response_pipeline is not None:
            response_pipeline.stop()
        if effect_pipeline is not None:
            effect_pipeline.stop()
        if codex_pipeline is not None:
            codex_pipeline.stop()
        if capability_policy is not None:
            capability_policy.stop()
        released = await supervisor.drain(
            deadline_seconds=config.lifecycle.graceful_shutdown_seconds,
        )
        if context_pipeline is not None:
            await context_pipeline.close()
        if context_embedding_pipeline is not None:
            await context_embedding_pipeline.close()
        if life_opportunity_pipeline is not None:
            await life_opportunity_pipeline.close()
        if exact_life_query_pipeline is not None:
            await exact_life_query_pipeline.close()
        if perception_module is not None:
            await perception_module.close()
        if life_record_query is not None:
            await life_record_query.close()
        if model_pipeline is not None:
            await model_pipeline.close()
        if web_research_pipeline is not None:
            await web_research_pipeline.close()
        if web_search_pipeline is not None:
            await web_search_pipeline.close()
        if candidate_pipeline is not None:
            await candidate_pipeline.close()
        if subject_commit_pipeline is not None:
            await subject_commit_pipeline.close()
        if response_pipeline is not None:
            await response_pipeline.close()
        if effect_pipeline is not None:
            await effect_pipeline.close()
        if qq_channel is not None:
            await qq_channel.close()
        if codex_pipeline is not None:
            await codex_pipeline.close()
        if capability_policy is not None:
            await capability_policy.close()
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
        drain_timed_out = not released
        lifecycle.stop()
        diagnostic.emit("runtime.lifecycle.stopped", result_code="LIFE_STOPPED")
        diagnostic.close()

    async def heartbeat_loop(controller: RuntimeAuthorityController) -> None:
        while True:
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
                diagnostic.emit(
                    "runtime.authority.suspended",
                    level=logging.WARNING,
                    result_code="AUTH_SUSPENDED",
                    reason_codes=("RUNTIME_AUTHORITY_SUSPENDED",),
                )
            else:
                diagnostic.emit(
                    "runtime.authority.heartbeat",
                    result_code="AUTH_HEARTBEAT",
                )

    def runtime_status() -> RuntimeStatusResponse:
        snapshot = lifecycle.snapshot()
        return RuntimeStatusResponse(
            contract_version="1.0",
            environment_id=snapshot.environment_id,
            runtime_state=snapshot.runtime_state,
            readiness=snapshot.readiness,
            reason_codes=list(snapshot.reason_codes),
            observed_at=snapshot.observed_at,
        )

    async def qq_health_status() -> QQChannelHealthResponse:
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
            state=health.state,
            ingress_ready=health.ingress_ready,
            api_reachable=health.api_reachable,
            account_online=health.account_online,
            account_matches=health.account_matches,
            webui_url=health.webui_url,
            observed_at=health.observed_at,
            reason_codes=list(health.reason_codes),
        )

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
                if action == "start":
                    await voice_service.start()  # pyright: ignore[reportGeneralTypeIssues]
                elif action == "stop":
                    await voice_service.stop()  # pyright: ignore[reportGeneralTypeIssues]
                state = voice_service.status().value
        return LiveVoiceStatusResponse(
            contract_version="1.0",
            projection_version="creator-live-voice-status.v1",
            state=state,
            enabled=voice_config.enabled,
            input_device=input_label,
            output_device=output_label,
            asr_ready=voice_service is not None and not reasons,
            llm_ready=voice_service is not None and not reasons,
            tts_ready=voice_service is not None and not reasons,
            observed_at=(
                datetime.now(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            ),
            reason_codes=reasons,
        )

    async def admin_voice(action: str) -> dict[str, object]:
        return (await live_voice_control(action)).model_dump(mode="json")

    async def admin_vision(action: str) -> dict[str, object]:
        return (await live_vision_control(action)).model_dump(mode="json")

    async def live_vision_control(action: str) -> LiveVisionStatusResponse:
        vision_config = config.vision
        service = live_vision_service
        reasons: list[str] = []
        state = "disabled"
        snapshot = None
        if vision_config.enabled:
            if service is None:
                state = "unavailable"
                reasons.append("VISION_PIPELINE_UNAVAILABLE")
            else:
                snapshot = service.status()
                try:
                    if action == "start":
                        await service.start()
                    elif action == "stop":
                        await service.stop()
                    elif action == "observe":
                        await service.observe()
                except LiveVisionViolation as error:
                    reasons.append(error.code.replace("-", "_"))
                snapshot = service.status()
                state = snapshot.state.value
        device = vision_config.device
        now = (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        last_observation = None if snapshot is None else snapshot.last_observation
        return LiveVisionStatusResponse(
            contract_version="1.0",
            projection_version="creator-live-vision-status.v1",
            state=state,
            enabled=vision_config.enabled,
            expected_running=False if snapshot is None else snapshot.expected_running,
            device=None
            if device is None
            else f"{device.name} / {device.usb_location_id}",
            capture_ready=snapshot is not None and snapshot.last_frame_at is not None,
            perception_ready=service is not None,
            last_frame_at=(
                None
                if snapshot is None or snapshot.last_frame_at is None
                else snapshot.last_frame_at.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                )
            ),
            last_observation_at=(
                None
                if last_observation is None
                else last_observation.registered_at.isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z")
            ),
            observations_last_hour=0
            if snapshot is None
            else snapshot.observations_last_hour,
            hourly_limit=vision_config.hourly_observation_limit,
            observed_at=now,
            reason_codes=reasons
            + (
                []
                if snapshot is None or snapshot.reason_code is None
                else [snapshot.reason_code.replace("-", "_")]
            ),
        )

    def live_vision_preview() -> bytes | None:
        return None if live_vision_service is None else live_vision_service.preview()

    def security_event(event: str) -> None:
        diagnostic.emit(event, result_code="CREATOR_SECURITY_EVENT")

    def admin_status() -> dict[str, object]:
        snapshot = lifecycle.snapshot()
        result: dict[str, object] = {
            "runtime_state": snapshot.runtime_state.value,
            "readiness": snapshot.readiness.value,
            "reason_codes": list(snapshot.reason_codes),
        }
        if observation_driver is not None:
            result["observability"] = observation_driver.snapshot()
        return result

    def admin_drain() -> None:
        lifecycle.drain()
        if authority is not None:
            authority.begin_drain()
        for pipeline in (
            life_opportunity_pipeline,
            exact_life_query_pipeline,
            context_pipeline,
            context_embedding_pipeline,
            model_pipeline,
            web_search_pipeline,
            web_research_pipeline,
            candidate_pipeline,
            subject_commit_pipeline,
            response_pipeline,
            effect_pipeline,
            codex_pipeline,
            capability_policy,
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

    app = create_runtime_app(
        readiness=lambda: lifecycle.snapshot().readiness,
        runtime_status=runtime_status,
        qq_channel_health=qq_health_status,
        live_voice_control=live_voice_control,
        live_vision_control=live_vision_control,
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
        other_human_input=other_human_input,
        creator_operations=creator_operations,
        subject_summary=subject_summary_provider,
        capability_policy=capability_policy,
        effect_ledger=effect_pipeline,
        codex_task_admission=(
            codex_pipeline.task_sources if codex_pipeline is not None else None
        ),
        expected_authority=f"{config.creator.bind_host}:{config.creator.port}",
        request_body_max_bytes=config.creator.request_body_max_bytes,
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
            timeout_graceful_shutdown=config.lifecycle.graceful_shutdown_seconds,
        )
    )
    if qq_channel is not None:
        qq_server = _RuntimeServer(
            uvicorn.Config(
                qq_channel.event_app,
                host="127.0.0.1",
                port=qq_channel.event_port,
                workers=1,
                proxy_headers=False,
                forwarded_allow_ips="",
                access_log=False,
                log_level="warning",
                log_config=None,
                server_header=False,
                timeout_graceful_shutdown=(config.lifecycle.graceful_shutdown_seconds),
            )
        )
    control_incarnation = load_admin_control_incarnation(
        prepared.root,
        str(config.environment.environment_id),
    )
    if control_incarnation is not None:
        admin_control = RuntimeAdminControlServer(
            run_root=prepared.root / "run" / "admin-control",
            environment_id=str(config.environment.environment_id),
            incarnation=control_incarnation,
            instance_id=instance_id,
            on_status=admin_status,
            on_drain=admin_drain,
            on_stop=admin_stop,
            on_input=admin_input if creator_input is not None else None,
            on_voice=admin_voice,
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
        if candidate_pipeline is not None:
            await candidate_pipeline.close()
        if capability_policy is not None:
            await capability_policy.close()
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
) -> int:
    """Run exactly one process-local Runtime; no reload or worker discovery."""

    try:
        return asyncio.run(
            _serve(prepared, creator_web_resources=creator_web_resources),
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
