"""Autonomy enablement and outlet; timing is deterministic, not model policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    enabled: bool = True
    outlet: Literal["qq", "creator_web"] = "qq"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or self.outlet not in {"qq", "creator_web"}:
            raise ValueError("LIFE-AUTONOMY-CONFIG")

    @property
    def minimum_consideration_seconds(self) -> int:
        return 60


__all__ = ("AutonomyPolicy",)
