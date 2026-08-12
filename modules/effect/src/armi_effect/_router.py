"""Route frozen effects by destination without exposing channel implementations."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .api import (
    ActionAdapterPort,
    EffectAdapterReceipt,
    EffectViolation,
    FrozenEffectRequest,
)


class RoutedActionAdapter(ActionAdapterPort):
    __slots__ = ("_routes",)

    def __init__(self, routes: Mapping[str, ActionAdapterPort]) -> None:
        values = dict(routes)
        if not values:
            raise ValueError("effect adapter route is invalid")
        self._routes = MappingProxyType(values)

    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt:
        return await self._adapter(request).dispatch(request, payload)

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None:
        return await self._adapter(request).observe(request)

    def _adapter(self, request: FrozenEffectRequest) -> ActionAdapterPort:
        adapter = self._routes.get(request.destination_kind)
        if adapter is None:
            raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")
        return adapter


__all__ = ("RoutedActionAdapter",)
