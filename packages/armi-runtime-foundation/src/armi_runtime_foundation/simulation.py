"""Owner read ports used by the isolated Runtime clock under its fence lock."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .transactions import PostgreSQLTransaction


@dataclass(frozen=True)
class SimulationState:
    busy: bool
    next_at: datetime | None = None


class SimulationReadPort(Protocol):
    async def read(self, transaction: PostgreSQLTransaction) -> SimulationState: ...
