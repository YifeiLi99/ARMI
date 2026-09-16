"""Shared autonomous observation port for authenticated Creator transports."""

from typing import Literal, Protocol


class AutonomyQueryPort(Protocol):
    async def query(
        self,
        mode: Literal["status", "history"],
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, object]: ...
