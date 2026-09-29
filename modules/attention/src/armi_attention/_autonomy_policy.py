"""Autonomy enablement and outlet; timing is deterministic, not model policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    enabled: bool = True
    outlet: Literal["qq", "creator_web"] = "qq"
    activation_weight: float = 50
    activation_base_rate: float = 0.5
    activation_growth_factor: float = 16
    idle_maturation_seconds: int = 1800
    maximum_idle_seconds: int = 7200
    quiet_seconds: int = 60

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or self.outlet not in {"qq", "creator_web"}:
            raise ValueError("LIFE-AUTONOMY-CONFIG")
        if not 0 <= self.activation_weight <= 100 or not (
            self.activation_base_rate > 0
            and self.activation_growth_factor >= 1
            and 0
            < self.quiet_seconds
            <= self.idle_maturation_seconds
            <= self.maximum_idle_seconds
        ):
            raise ValueError("LIFE-AUTONOMY-CONFIG")

    @property
    def minimum_consideration_seconds(self) -> int:
        return self.quiet_seconds


__all__ = ("AutonomyPolicy",)
