"""Integrated idle intensity; polling never draws random numbers or advances state.

See docs/07-内部算法/03-Attention自主唤醒.md. This is scheduling,
not a psychological fact: unknown needs contribute no extra intensity.
"""

import math
from contextvars import ContextVar
from random import Random, SystemRandom

from pydantic import BaseModel, ConfigDict, Field

from ._autonomy_policy import AutonomyPolicy

_SEED: ContextVar[int | None] = ContextVar("activation_seed", default=None)


def bind_simulation_seed(seed: int) -> None:
    _SEED.set(seed)


class Activation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cycle: int = Field(ge=0)
    threshold: float = Field(gt=0)
    accumulated: float = Field(default=0, ge=0)
    idle_seconds: float = Field(default=0, ge=0)
    anchor_seconds: float = Field(ge=0)
    need: float = Field(default=0, ge=0, le=1)
    idling: bool = False
    weight: float = Field(ge=0, le=100)
    base_rate: float = Field(default=0.5, gt=0)
    growth_factor: float = Field(default=16, ge=1)
    maturation_seconds: float = Field(default=1800, gt=0)
    runtime_ref: str = ""
    retry_after: float = Field(default=0, ge=0)

    @classmethod
    def begin(cls, *, cycle: int, active: float, policy: AutonomyPolicy) -> Activation:
        seed = _SEED.get()
        rng = SystemRandom() if seed is None else Random(f"{seed}:{cycle}")
        return cls(
            cycle=cycle,
            threshold=max(1e-12, -math.log1p(-rng.random())),
            anchor_seconds=active,
            weight=policy.activation_weight,
            base_rate=policy.activation_base_rate,
            growth_factor=policy.activation_growth_factor,
            maturation_seconds=policy.idle_maturation_seconds,
        )

    def project(self, active: float, policy: AutonomyPolicy) -> tuple[float, float]:
        elapsed = max(0.0, active - self.anchor_seconds) if self.idling else 0.0
        idle = self.idle_seconds + elapsed
        maturity = self.maturation_seconds

        def area(seconds: float) -> float:
            return (
                seconds * seconds / (2 * maturity)
                if seconds < maturity
                else seconds - maturity / 2
            )

        rate = self.base_rate * self.growth_factor ** (self.weight / 100) / 3600
        return self.accumulated + rate * (
            (1 + self.need) * elapsed + area(idle) - area(self.idle_seconds)
        ), idle

    def changed(
        self, *, active: float, idling: bool, need: float, policy: AutonomyPolicy
    ) -> Activation:
        if (
            idling,
            need,
            policy.activation_weight,
            policy.activation_base_rate,
            policy.activation_growth_factor,
            policy.idle_maturation_seconds,
        ) == (
            self.idling,
            self.need,
            self.weight,
            self.base_rate,
            self.growth_factor,
            self.maturation_seconds,
        ):
            return self
        amount, idle = self.project(active, policy)
        return self.model_copy(
            update=dict(
                accumulated=amount,
                idle_seconds=idle if idling and self.idling else 0.0,
                anchor_seconds=active,
                idling=idling,
                need=need,
                weight=policy.activation_weight,
                base_rate=policy.activation_base_rate,
                growth_factor=policy.activation_growth_factor,
                maturation_seconds=policy.idle_maturation_seconds,
            )
        )

    def remaining(self, active: float, policy: AutonomyPolicy) -> float:
        if not self.idling:
            return float(policy.maximum_idle_seconds)
        amount, idle = self.project(active, policy)
        quiet = max(0.0, policy.quiet_seconds - idle, self.retry_after - active)
        upper = max(quiet, policy.maximum_idle_seconds - idle)
        if amount >= self.threshold:
            return quiet
        low, high = 0.0, upper
        for _ in range(48):
            middle = (low + high) / 2
            if self.project(active + middle, policy)[0] < self.threshold:
                low = middle
            else:
                high = middle
        return max(quiet, high)
