"""Owned Runtime tasks and deadline-bounded drain sequencing."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

from armi_kernel.application import RuntimeAuthorityViolation

from .authority import LocalAuthorityState, RuntimeAuthorityController


class RuntimeSupervisor:
    """Retain every controlled task and keep heartbeat until authority release."""

    __slots__ = ("_authority", "_heartbeat", "_on_task_failure", "_tasks")

    def __init__(
        self,
        authority: RuntimeAuthorityController | None,
        *,
        on_task_failure: Callable[[str, BaseException], None] | None = None,
    ) -> None:
        self._authority = authority
        self._heartbeat: asyncio.Task[None] | None = None
        self._on_task_failure = on_task_failure
        self._tasks: set[asyncio.Task[None]] = set()

    def start(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
        heartbeat: bool = False,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        if heartbeat:
            if self._heartbeat is not None:
                task.cancel()
                raise RuntimeError("heartbeat task already exists")
            self._heartbeat = task
        else:
            self._tasks.add(task)
            task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self._on_task_failure is not None:
            self._on_task_failure(task.get_name(), error)

    async def drain(self, *, deadline_seconds: int) -> bool:
        """Stop admission, finish owned work, release authority, then heartbeat."""

        authority = self._authority
        if authority is not None and authority.snapshot().state in {
            LocalAuthorityState.ACTIVE,
            LocalAuthorityState.SUSPENDED,
        }:
            authority.begin_drain()
        try:
            if self._tasks:
                async with asyncio.timeout(deadline_seconds):
                    await asyncio.gather(*tuple(self._tasks))
        except TimeoutError:
            await self._cancel_all()
            return False
        if authority is not None and authority.snapshot().state is (
            LocalAuthorityState.DRAINING
        ):
            try:
                await authority.release()
            except RuntimeAuthorityViolation:
                await self._cancel_all()
                return False
        await self._cancel_heartbeat()
        return True

    async def abort(self) -> None:
        """Cancel owned tasks without pretending authority was released."""

        await self._cancel_all()

    async def _cancel_all(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()
        await self._cancel_heartbeat()

    async def _cancel_heartbeat(self) -> None:
        if self._heartbeat is None:
            return
        self._heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat
        self._heartbeat = None


__all__ = ("RuntimeSupervisor",)
