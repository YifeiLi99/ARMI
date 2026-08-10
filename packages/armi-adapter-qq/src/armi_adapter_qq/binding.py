"""Compose the QQ adapter with the separately packaged NapCat driver."""

from __future__ import annotations

from dataclasses import dataclass

from armi_channel_napcat import NapCatHttpClient, NapCatViolation
from armi_kernel.application import ActionAdapterPort, ExternalGroupInputPort
from fastapi import FastAPI

from .adapter import QQGroupEffectAdapter, QQGroupEgressAdapter, QQGroupIngressAdapter
from .config import QQNapCatBindingConfig
from .webhook import create_qq_event_app


class QQNapCatBindingViolation(RuntimeError):
    """The concrete QQ/NapCat binding could not be constructed safely."""


@dataclass(frozen=True, slots=True)
class QQNapCatBinding:
    effect_adapter: ActionAdapterPort
    event_app: FastAPI
    event_port: int
    _gateway: NapCatHttpClient

    async def close(self) -> None:
        await self._gateway.close()


def create_qq_napcat_binding(
    *,
    config: QQNapCatBindingConfig,
    input_port: ExternalGroupInputPort,
    access_token: bytes,
    event_signing_secret: bytes,
) -> QQNapCatBinding:
    try:
        token = access_token.decode("utf-8", errors="strict")
        ingress = QQGroupIngressAdapter(
            config=config.adapter,
            input_port=input_port,
        )
        event_app = create_qq_event_app(
            config=config.adapter,
            ingress=ingress,
            signing_secret=event_signing_secret,
            request_body_max_bytes=config.request_body_max_bytes,
        )
        gateway = NapCatHttpClient(
            base_url=config.api_base_url,
            access_token=token,
        )
    except NapCatViolation, UnicodeDecodeError, ValueError:
        raise QQNapCatBindingViolation from None
    egress = QQGroupEgressAdapter(config=config.adapter, gateway=gateway)
    return QQNapCatBinding(
        QQGroupEffectAdapter(egress),
        event_app,
        config.event_port,
        gateway,
    )


__all__ = (
    "QQNapCatBinding",
    "QQNapCatBindingViolation",
    "create_qq_napcat_binding",
)
