"""Compose the QQ adapter with the separately packaged NapCat driver."""

from __future__ import annotations

from dataclasses import dataclass

from armi_channel_napcat import (
    NapCatHealthSnapshot,
    NapCatHttpClient,
    NapCatViolation,
)
from armi_effect.api import ActionAdapterPort
from armi_interaction.api import ExternalMessageInputPort
from armi_perception.api import ExternalMediaFetchPort
from fastapi import FastAPI

from .adapter import (
    QQEffectAdapter,
    QQEgressAdapter,
    QQIngressAdapter,
    QQMediaFetchAdapter,
)
from .config import QQNapCatBindingConfig
from .webhook import create_qq_event_app


class QQNapCatBindingViolation(RuntimeError):
    """The concrete QQ/NapCat binding could not be constructed safely."""


@dataclass(frozen=True, slots=True)
class QQNapCatBinding:
    effect_adapter: ActionAdapterPort
    media_fetch: ExternalMediaFetchPort
    event_app: FastAPI
    event_port: int
    account_id: int
    _gateway: NapCatHttpClient

    async def close(self) -> None:
        await self._gateway.close()

    async def inspect_health(self, *, expected_account_id: int) -> NapCatHealthSnapshot:
        return await self._gateway.inspect_health(
            expected_account_id=expected_account_id
        )


def create_qq_napcat_binding(
    *,
    config: QQNapCatBindingConfig,
    input_port: ExternalMessageInputPort,
    access_token: bytes,
    event_signing_secret: bytes,
) -> QQNapCatBinding:
    try:
        token = access_token.decode("utf-8", errors="strict")
        gateway = NapCatHttpClient(
            base_url=config.api_base_url,
            access_token=token,
        )
        ingress = QQIngressAdapter(
            config=config.adapter,
            input_port=input_port,
            gateway=gateway,
        )
        event_app = create_qq_event_app(
            config=config.adapter,
            ingress=ingress,
            signing_secret=event_signing_secret,
            request_body_max_bytes=config.request_body_max_bytes,
        )
    except NapCatViolation, UnicodeDecodeError, ValueError:
        raise QQNapCatBindingViolation from None
    egress = QQEgressAdapter(config=config.adapter, gateway=gateway)
    return QQNapCatBinding(
        QQEffectAdapter(egress),
        QQMediaFetchAdapter(config=config.adapter, gateway=gateway),
        event_app,
        config.event_port,
        config.adapter.account_id,
        gateway,
    )


__all__ = (
    "QQNapCatBinding",
    "QQNapCatBindingViolation",
    "create_qq_napcat_binding",
)
