"""Dedicated-thread serial lifecycle and probe operation."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Protocol, TypeVar, cast
from uuid import uuid4

from armi_mood.api import MoodSnapshot

from .api import MoodDisplayConfig, MoodDisplayStatus, MoodDisplayViolation, ProbeResult
from .mapping import map_mood_snapshot
from .wire import decode_frame, encode_ping, encode_pong, encode_state, parse_hello


class SerialPort(Protocol):
    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes: ...
    def write(self, data: bytes, /) -> int | None: ...
    def close(self) -> None: ...


SerialFactory = Callable[[str], SerialPort]
SnapshotProvider = Callable[[], Awaitable[MoodSnapshot]]
ResultT = TypeVar("ResultT")


def _open_serial(port: str) -> SerialPort:
    import serial

    return cast(
        SerialPort,
        serial.Serial(
            port=port,
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=1,
        ),
    )


def _read(port: SerialPort) -> bytes:
    return port.read_until(b"\n", 513)


def _write(port: SerialPort, frame: bytes) -> None:
    if port.write(frame) != len(frame):
        raise MoodDisplayViolation("MOOD-DISPLAY-WRITE")


def probe_device(
    port: str, *, serial_factory: SerialFactory = _open_serial
) -> ProbeResult:
    connection = serial_factory(port)
    try:
        return parse_hello(_read(connection))
    finally:
        connection.close()


class MoodDisplayAdapter:
    """Reconnects independently; device absence never stops the Runtime."""

    __slots__ = (
        "_config",
        "_serial_executor",
        "_serial_factory",
        "_snapshot",
        "_status",
        "_status_lock",
    )

    def __init__(
        self,
        config: MoodDisplayConfig,
        snapshot: SnapshotProvider,
        *,
        serial_factory: SerialFactory = _open_serial,
    ) -> None:
        self._config = config
        self._snapshot = snapshot
        self._serial_factory = serial_factory
        self._serial_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="armi-mood-display"
        )
        self._status = MoodDisplayStatus("unavailable", reason_code="not_connected")
        self._status_lock = Lock()

    @property
    def status(self) -> MoodDisplayStatus:
        with self._status_lock:
            return self._status

    def _set_status(self, value: MoodDisplayStatus) -> None:
        with self._status_lock:
            self._status = value

    async def _serial_call(
        self, operation: Callable[..., ResultT], /, *args: object
    ) -> ResultT:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._serial_executor, operation, *args)

    async def run(self) -> None:
        backoffs = (1, 2, 5, 10, 30)
        attempt = 0
        try:
            while True:
                connection: SerialPort | None = None
                connected_at: float | None = None
                try:
                    connection = await self._serial_call(
                        self._serial_factory, self._config.port
                    )
                    hello = parse_hello(await self._serial_call(_read, connection))
                    if hello.device_id != self._config.expected_device_id:
                        raise MoodDisplayViolation("MOOD-DISPLAY-DEVICE-ID")
                    self._set_status(MoodDisplayStatus("available", hello.device_id))
                    connected_at = time.monotonic()
                    await self._session(connection)
                except asyncio.CancelledError:
                    raise
                except OSError, MoodDisplayViolation:
                    if (
                        connected_at is not None
                        and time.monotonic() - connected_at >= 30
                    ):
                        attempt = 0
                    self._set_status(
                        MoodDisplayStatus(
                            "unavailable", reason_code="connection_failed"
                        )
                    )
                finally:
                    if connection is not None:
                        with contextlib.suppress(OSError):
                            await self._serial_call(connection.close)
                delay = backoffs[min(attempt, len(backoffs) - 1)]
                attempt += 1
                await asyncio.sleep(delay)
        finally:
            self._serial_executor.shutdown(wait=True)

    async def _session(self, connection: SerialPort) -> None:
        last_state = None
        last_ping = time.monotonic()
        while True:
            snapshot = await self._snapshot()
            state = map_mood_snapshot(snapshot)
            if state != last_state:
                state_id = str(uuid4())
                frame = encode_state(state_id, state)
                await self._send_with_ack(connection, frame, state_id)
                last_state = state
            if time.monotonic() - last_ping >= 10:
                await self._heartbeat(connection)
                last_ping = time.monotonic()
            await asyncio.sleep(1)

    async def _heartbeat(self, connection: SerialPort) -> None:
        ping_id = str(uuid4())
        await self._serial_call(_write, connection, encode_ping(ping_id))
        value = decode_frame(await self._serial_call(_read, connection))
        if (
            set(value) != {"type", "protocol_version", "ping_id"}
            or value.get("type") != "pong"
            or value.get("ping_id") != ping_id
        ):
            raise MoodDisplayViolation("MOOD-DISPLAY-PONG")

    async def _send_with_ack(
        self, connection: SerialPort, frame: bytes, state_id: str
    ) -> None:
        for _ in range(2):
            await self._serial_call(_write, connection, frame)
            incoming = await self._serial_call(_read, connection)
            if not incoming:
                continue
            value = decode_frame(incoming)
            if value.get("type") == "ping" and isinstance(value.get("ping_id"), str):
                await self._serial_call(
                    _write, connection, encode_pong(value["ping_id"])
                )
                continue
            if (
                set(value) == {"type", "protocol_version", "state_id", "status"}
                and value.get("type") == "ack"
                and value.get("state_id") == state_id
                and value.get("status") == "applied"
            ):
                return
            raise MoodDisplayViolation("MOOD-DISPLAY-ACK")
        raise MoodDisplayViolation("MOOD-DISPLAY-ACK-TIMEOUT")


__all__ = ("MoodDisplayAdapter", "probe_device")
