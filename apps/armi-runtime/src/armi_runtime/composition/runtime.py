"""Explicit S008 Runtime composition root and Uvicorn process ownership."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import selectors
import signal
import threading
from collections.abc import Generator
from uuid import uuid7

import uvicorn
from armi_kernel.application import (
    CandidateViolation,
    CapabilityViolation,
    ContextViolation,
    CreatorInputViolation,
    EffectViolation,
    ModelViolation,
    RecoveryStatus,
    RecoveryViolation,
    ResponseViolation,
    RuntimeAuthorityViolation,
    RuntimeInstanceId,
    SceneQueryViolation,
    SubjectCommitViolation,
    WebObservationViolation,
)

from armi_runtime.interfaces.browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
)
from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.creator_contract import RuntimeStatusResponse
from armi_runtime.interfaces.creator_events import CreatorEventBroker
from armi_runtime.interfaces.static_assets import AssetViolation, StaticAssetStore

from .authority import (
    LocalAuthorityState,
    RuntimeAuthorityController,
)
from .creator_session import compose_browser_sessions, derive_timeline_cursor_key
from .database import (
    ContinuityState,
    DatabaseViolation,
    compose_candidate_validation_pipeline,
    compose_capability_policy,
    compose_context_pipeline,
    compose_creator_input,
    compose_effect_registration_pipeline,
    compose_model_pipeline,
    compose_response_admission_pipeline,
    compose_runtime_authority,
    compose_runtime_recovery,
    compose_scene_timeline_query,
    compose_subject_commit_pipeline,
    compose_web_search_pipeline,
    inspect_creator_context,
    inspect_runtime_continuity,
    runtime_database_reason,
)
from .diagnostics import StructuredDiagnosticLog
from .environment import PreparedEnvironment
from .lifecycle import RUNTIME_BLOCKING_REASONS, LifecycleController
from .runtime_errors import RuntimeViolation
from .supervisor import RuntimeSupervisor

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


async def _serve(prepared: PreparedEnvironment) -> int:
    config = prepared.effective.config
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
    )
    assets = StaticAssetStore.load_packaged()
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
    recovery_reasons: tuple[str, ...] = ()
    browser_sessions: BrowserSessionStore | None = None
    scene_timeline_query = None
    creator_events: CreatorEventBroker | None = None
    creator_input = None
    context_pipeline = None
    model_pipeline = None
    candidate_pipeline = None
    subject_commit_pipeline = None
    capability_policy = None
    response_pipeline = None
    effect_pipeline = None
    web_search_pipeline = None
    if continuity is ContinuityState.BORN:
        try:
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
            lifecycle.begin_recovery()
            diagnostic.emit(
                "runtime.lifecycle.recovering",
                result_code="LIFE_RECOVERING",
            )
            recovery_port = compose_runtime_recovery(
                prepared,
                authority_admission=authority.require_writable,
            )
            await recovery_port.open()
            recovery = await recovery_port.recover()
            if recovery.status is RecoveryStatus.BLOCKED:
                recovery_reasons = ("RUNTIME_RECOVERY_BLOCKED",)
                diagnostic.emit(
                    "runtime.recovery.blocked",
                    level=logging.ERROR,
                    result_code="REC_BLOCKED",
                    reason_codes=recovery_reasons,
                )
            else:
                diagnostic.emit(
                    "runtime.recovery.safe",
                    result_code="REC_SAFE",
                )
            creator_context = inspect_creator_context(prepared)
            if creator_context is None:
                raise BrowserSessionViolation(
                    "SEC_CREATOR_IDENTITY_UNAVAILABLE",
                    status_code=503,
                )
            browser_sessions = compose_browser_sessions(
                prepared,
                creator_party_id=creator_context.party_id,
                default_scene_key=creator_context.default_scene_key,
            )
            scene_timeline_query = compose_scene_timeline_query(
                prepared,
                creator_party_id=creator_context.party_id,
                cursor_key=derive_timeline_cursor_key(prepared),
            )
            await scene_timeline_query.open()
            creator_events = CreatorEventBroker(
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CREATOR_EVENT_STREAM",
                )
            )
            capability_policy = compose_capability_policy(
                prepared,
                authority_admission=authority.require_writable,
                cursor_key=derive_timeline_cursor_key(prepared),
                notifier=creator_events,
            )
            await capability_policy.open()
            creator_input = compose_creator_input(
                prepared,
                creator_party_id=creator_context.party_id,
                authority_admission=authority.require_writable,
                notifier=creator_events,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CREATOR_INPUT",
                ),
            )
            await creator_input.open()
            context_pipeline = compose_context_pipeline(
                prepared,
                authority_admission=authority.require_writable,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CONTEXT_PIPELINE",
                ),
            )
            await context_pipeline.open()
            candidate_pipeline = compose_candidate_validation_pipeline(
                prepared,
                authority_admission=authority.require_writable,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="CANDIDATE_PIPELINE",
                ),
            )
            await candidate_pipeline.open()
            subject_commit_pipeline = compose_subject_commit_pipeline(
                prepared,
                authority_admission=authority.require_writable,
                notifier=creator_events,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="SUBJECT_COMMIT_PIPELINE",
                ),
            )
            await subject_commit_pipeline.open()
            response_pipeline = compose_response_admission_pipeline(
                prepared,
                authority_admission=authority.require_writable,
                diagnostic=lambda event: diagnostic.emit(
                    event,
                    result_code="RESPONSE_ADMISSION",
                ),
            )
            await response_pipeline.open()
            effect_pipeline = compose_effect_registration_pipeline(
                prepared,
                authority_admission=authority.require_writable,
                notifier=creator_events,
                diagnostic=lambda event: diagnostic.emit(
                    event, result_code="EFFECT_REGISTRATION"
                ),
            )
            await effect_pipeline.open()
            if "model.ark_api_key" in config.secret_locators:
                try:
                    model_pipeline = compose_model_pipeline(
                        prepared,
                        authority_admission=authority.require_writable,
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
                try:
                    web_search_pipeline = compose_web_search_pipeline(
                        prepared,
                        authority_admission=authority.require_writable,
                        diagnostic=lambda event: diagnostic.emit(
                            event,
                            result_code="WEB_SEARCH_CUSTODY",
                        ),
                    )
                    await web_search_pipeline.open()
                except WebObservationViolation:
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
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        except RecoveryViolation:
            recovery_reasons = ("RUNTIME_RECOVERY_BLOCKED",)
            diagnostic.emit(
                "runtime.recovery.failed",
                level=logging.ERROR,
                result_code="REC_FAILED",
                reason_codes=recovery_reasons,
            )
        except (
            BrowserSessionViolation,
            CandidateViolation,
            CapabilityViolation,
            ContextViolation,
            CreatorInputViolation,
            SceneQueryViolation,
            SubjectCommitViolation,
            ResponseViolation,
            EffectViolation,
        ):
            diagnostic.emit(
                "runtime.creator_interface.unavailable",
                level=logging.ERROR,
                result_code="CREATOR_INTERFACE_UNAVAILABLE",
                reason_codes=("RUNTIME_CREATOR_INTERFACE_UNAVAILABLE",),
            )
            if scene_timeline_query is not None:
                await scene_timeline_query.close()
            if creator_input is not None:
                await creator_input.close()
            if context_pipeline is not None:
                await context_pipeline.close()
            if candidate_pipeline is not None:
                await candidate_pipeline.close()
            if subject_commit_pipeline is not None:
                await subject_commit_pipeline.close()
            if response_pipeline is not None:
                await response_pipeline.close()
            if effect_pipeline is not None:
                await effect_pipeline.close()
            if capability_policy is not None:
                await capability_policy.close()
            if authority is not None:
                await authority.release()
            if authority_port is not None:
                await authority_port.close()
            diagnostic.close()
            return EXIT_LISTENER_FAILURE
        finally:
            if recovery_port is not None:
                await recovery_port.close()
    elif continuity is ContinuityState.UNBORN:
        lifecycle.mark_unborn()

    supervisor = RuntimeSupervisor(authority)
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
                heartbeat_loop(),
                name="runtime-authority-heartbeat",
                heartbeat=True,
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
        if model_pipeline is not None:
            for index in range(config.model.concurrency):
                supervisor.start(
                    model_pipeline.run_worker(),
                    name=f"model-invoke-worker-{index + 1}",
                )
        if web_search_pipeline is not None:
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
        if capability_policy is not None:
            supervisor.start(
                capability_policy.run_expiry_reconciler(),
                name="capability-grant-expiry",
            )

    async def stopping() -> None:
        nonlocal drain_timed_out
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
        if scene_timeline_query is not None:
            await scene_timeline_query.close()
        if creator_input is not None:
            await creator_input.close()
        if context_pipeline is not None:
            context_pipeline.stop()
        if model_pipeline is not None:
            model_pipeline.stop()
        if web_search_pipeline is not None:
            web_search_pipeline.stop()
        if candidate_pipeline is not None:
            candidate_pipeline.stop()
        if subject_commit_pipeline is not None:
            subject_commit_pipeline.stop()
        if response_pipeline is not None:
            response_pipeline.stop()
        if effect_pipeline is not None:
            effect_pipeline.stop()
        if capability_policy is not None:
            capability_policy.stop()
        released = await supervisor.drain(
            deadline_seconds=config.lifecycle.graceful_shutdown_seconds,
        )
        if context_pipeline is not None:
            await context_pipeline.close()
        if model_pipeline is not None:
            await model_pipeline.close()
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

    async def heartbeat_loop() -> None:
        assert authority is not None
        while True:
            await asyncio.sleep(config.runtime.heartbeat_seconds)
            try:
                snapshot = await authority.heartbeat_once()
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

    def security_event(event: str) -> None:
        diagnostic.emit(event, result_code="CREATOR_SECURITY_EVENT")

    app = create_runtime_app(
        readiness=lambda: lifecycle.snapshot().readiness,
        runtime_status=runtime_status,
        assets=assets,
        browser_sessions=browser_sessions,
        scene_timeline_query=scene_timeline_query,
        creator_events=creator_events,
        creator_input=creator_input,
        creator_operations=creator_input,
        subject_summary=(
            creator_input.get_subject_summary if creator_input is not None else None
        ),
        capability_policy=capability_policy,
        effect_ledger=effect_pipeline,
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
        if scene_timeline_query is not None:
            await scene_timeline_query.close()
        if creator_input is not None:
            await creator_input.close()
        if context_pipeline is not None:
            await context_pipeline.close()
        if candidate_pipeline is not None:
            await candidate_pipeline.close()
        if capability_policy is not None:
            await capability_policy.close()
        if effect_pipeline is not None:
            await effect_pipeline.close()
        if web_search_pipeline is not None:
            await web_search_pipeline.close()
        if authority_port is not None:
            await authority_port.close()
    if server.force_exit:
        return EXIT_GRACEFUL_TIMEOUT
    if drain_timed_out:
        return EXIT_GRACEFUL_TIMEOUT
    if not server.started:
        return EXIT_LISTENER_FAILURE
    return EXIT_GRACEFUL


def run_runtime(prepared: PreparedEnvironment) -> int:
    """Run exactly one process-local Runtime; no reload or worker discovery."""

    try:
        return asyncio.run(
            _serve(prepared),
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
