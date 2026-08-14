"""Scene reply routing preserves the channel that admitted the conversation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

from armi_interaction._action_postgresql import PostgreSQLInteractionActionOwner


class _Cursor:
    def __init__(self, row: tuple[object, ...]) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...]:
        return self._row


def _route_row(*, external_binding: bool) -> tuple[object, ...]:
    return (
        uuid7(),
        "creator-scene",
        "creator_dialogue",
        uuid7(),
        "creator",
        None,
        None,
        None,
        None,
        uuid7() if external_binding else None,
        "qq" if external_binding else None,
        "1479926305" if external_binding else None,
        "2153844284" if external_binding else None,
    )


def _resolve(row: tuple[object, ...], intended: str | None = None):
    transaction = SimpleNamespace(execute=AsyncMock(return_value=_Cursor(row)))
    return asyncio.run(
        PostgreSQLInteractionActionOwner().effect_route(
            cast(Any, transaction),
            scene_id=cast(Any, row[0]),
            context_party_id=cast(Any, row[3]),
            intended_destination_kind=intended,
        )
    )


def test_creator_reply_uses_external_private_route_when_scene_has_binding() -> None:
    row = _route_row(external_binding=True)

    route = _resolve(row)

    assert route.destination_kind == "external_private"
    assert route.destination_binding_id == row[9]
    assert route.external_channel == "qq"
    assert route.external_account_key == "1479926305"
    assert route.external_conversation_key == "2153844284"


def test_creator_reply_uses_local_inbox_without_external_binding() -> None:
    route = _resolve(_route_row(external_binding=False))

    assert route.destination_kind == "creator_inbox"
    assert route.destination_binding_id is None


def test_existing_local_effect_keeps_its_frozen_local_route() -> None:
    route = _resolve(_route_row(external_binding=True), "creator_inbox")

    assert route.destination_kind == "creator_inbox"
    assert route.destination_binding_id is None
