"""Small collaborator implementations kept private to the interaction module."""

from __future__ import annotations


class NullInteractionWakeup:
    __slots__ = ()

    def notify(self, _channel: str) -> None:
        return None


__all__ = ("NullInteractionWakeup",)
