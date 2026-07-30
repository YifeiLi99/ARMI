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
    CreatorInputViolation,
    RecoveryStatus,
    RecoveryViolation,
    RuntimeAuthorityViolation,
    RuntimeInstanceId,
    SceneQueryViolation,
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
    compose_creator_input,
    compose_runtime_authority,
    compose_runtime_recovery,
    compose_scene_timeline_query,
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
        except BrowserSessionViolation, CreatorInputViolation, SceneQueryViolation:
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
        released = await supervisor.drain(
            deadline_seconds=config.lifecycle.graceful_shutdown_seconds,
        )
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
