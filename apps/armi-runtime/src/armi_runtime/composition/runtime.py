"""Explicit S008 Runtime composition root and Uvicorn process ownership."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import threading
from collections.abc import Generator
from uuid import uuid4

import uvicorn

from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.static_assets import AssetViolation, StaticAssetStore

from .database import runtime_database_reason
from .diagnostics import StructuredDiagnosticLog
from .environment import PreparedEnvironment
from .lifecycle import RUNTIME_BLOCKING_REASONS, LifecycleController
from .runtime_errors import RuntimeViolation

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
    instance_id = str(uuid4())
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
    database_reasons = runtime_database_reason(prepared)

    async def started() -> None:
        lifecycle.start()
        if diagnostic.status.reason_code is not None:
            lifecycle.add_degradation(diagnostic.status.reason_code)
        diagnostic.emit("runtime.lifecycle.starting", result_code="LIFE_STARTING")
        snapshot = lifecycle.complete_startup(
            (*RUNTIME_BLOCKING_REASONS, *database_reasons)
        )
        diagnostic.emit(
            "runtime.lifecycle.blocked",
            level=logging.WARNING,
            result_code="LIFE_BLOCKED",
            reason_codes=snapshot.reason_codes,
        )

    async def stopping() -> None:
        lifecycle.drain()
        diagnostic.emit("runtime.lifecycle.draining", result_code="LIFE_DRAINING")
        lifecycle.stop()
        diagnostic.emit("runtime.lifecycle.stopped", result_code="LIFE_STOPPED")
        diagnostic.close()

    app = create_runtime_app(
        readiness=lambda: lifecycle.snapshot().readiness,
        assets=assets,
        expected_authority=f"{config.creator.bind_host}:{config.creator.port}",
        request_body_max_bytes=config.creator.request_body_max_bytes,
        on_started=started,
        on_stopping=stopping,
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
    if server.force_exit:
        return EXIT_GRACEFUL_TIMEOUT
    if not server.started:
        return EXIT_LISTENER_FAILURE
    return EXIT_GRACEFUL


def run_runtime(prepared: PreparedEnvironment) -> int:
    """Run exactly one process-local Runtime; no reload or worker discovery."""

    try:
        return asyncio.run(_serve(prepared))
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
