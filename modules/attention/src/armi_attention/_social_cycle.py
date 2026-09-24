"""One persisted threshold per social consideration cycle; read operations are pure."""

from collections.abc import Callable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SocialCycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    threshold: float = Field(ge=0.4, le=0.6)
    phase: Literal[
        "considering", "cognition", "delivery", "waiting", "deferred", "released"
    ] = "considering"
    review_at: float = Field(default=0.0, ge=0)
    unanswered: int = Field(default=0, ge=0)
    input_ref: str | None = None
    target_ref: str | None = None
    episode_ref: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def delivery_has_episode(self) -> Self:
        if self.phase == "delivery" and self.episode_ref is None:
            raise ValueError("LIFE-SOCIAL-DELIVERY-SOURCE")
        return self

    @classmethod
    def begin(
        cls,
        draw: Callable[[], float],
        *,
        input_ref: str | None = None,
        unanswered: int = 0,
        target_ref: str | None = None,
    ) -> Self:
        return cls(
            threshold=0.4 + 0.2 * draw(),
            input_ref=input_ref,
            unanswered=unanswered,
            target_ref=target_ref,
        )

    def ready(self, *, drive: float, active_seconds: float, focused: bool) -> bool:
        return (
            self.phase not in {"cognition", "delivery"}
            and active_seconds >= self.review_at
            and drive * (0.75 if focused else 1.0) >= self.threshold
        )

    def decided(
        self,
        *,
        outcome: Literal["express", "defer", "release"],
        reason: str,
        episode_ref: str,
        active_seconds: float,
    ) -> Self:
        if self.phase != "cognition" or not reason.strip():
            raise ValueError("LIFE-SOCIAL-DECISION")
        return self.model_copy(
            update={
                "phase": {
                    "express": "delivery",
                    "defer": "deferred",
                    "release": "released",
                }[outcome],
                "review_at": active_seconds
                + (
                    3600 if outcome == "defer" else 14400 if outcome == "release" else 0
                ),
                "episode_ref": episode_ref,
                "reason": reason,
            }
        )

    def delivered(self, *, active_seconds: float) -> Self:
        if self.phase != "delivery":
            raise ValueError("LIFE-SOCIAL-DELIVERY-STATE")
        delay = (2, 4, 8, 16, 24)[min(self.unanswered, 4)] * 3600
        return self.model_copy(
            update={
                "phase": "waiting",
                "review_at": active_seconds + delay,
                "unanswered": self.unanswered + 1,
                "reason": "awaiting_response",
            }
        )

    def interrupted(self, *, active_seconds: float, reason: str) -> Self:
        return self.model_copy(
            update={
                "phase": "deferred",
                "review_at": active_seconds + 3600,
                "reason": reason,
            }
        )
