"""Optional composition seam for the separately packaged QQ and NapCat layers."""

from __future__ import annotations

from armi_adapter_qq import (
    QQNapCatBinding,
    QQNapCatBindingViolation,
    create_qq_napcat_binding,
    load_qq_napcat_config,
)
from armi_kernel.application import (
    CredentialPurpose,
    EffectViolation,
    ExternalGroupInputPort,
)

from .configuration import ConfigurationViolation
from .configuration.paths import has_reparse_point, require_within_roots
from .environment import PreparedEnvironment

QQ_NAPCAT_ACCESS_TOKEN_LOCATOR = "channel.qq.napcat_access_token"
QQ_NAPCAT_ACCESS_TOKEN_PURPOSE = "channel.qq.napcat.api"
QQ_NAPCAT_EVENT_SECRET_LOCATOR = "channel.qq.napcat_event_secret"
QQ_NAPCAT_EVENT_SECRET_PURPOSE = "channel.qq.napcat.events"


QQChannelBinding = QQNapCatBinding


def compose_qq_channel(
    prepared: PreparedEnvironment,
    *,
    input_port: ExternalGroupInputPort,
) -> QQChannelBinding | None:
    path = prepared.root / "channels" / "qq-napcat.toml"
    if not path.exists():
        return None
    try:
        resolved, root = require_within_roots(
            path,
            (prepared.root,),
            code="CFG-QQ-CHANNEL",
        )
    except ConfigurationViolation:
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE") from None
    if has_reparse_point(resolved, root=root):
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")
    try:
        binding = load_qq_napcat_config(resolved)
    except ValueError:
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE") from None
    if binding is None:
        return None
    if binding.event_port == prepared.effective.config.creator.port:
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")
    access_token_locator = prepared.effective.config.secret_locators.get(
        QQ_NAPCAT_ACCESS_TOKEN_LOCATOR
    )
    event_secret_locator = prepared.effective.config.secret_locators.get(
        QQ_NAPCAT_EVENT_SECRET_LOCATOR
    )
    if access_token_locator is None or event_secret_locator is None:
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")
    try:
        with (
            prepared.credential_port.resolve(
                access_token_locator,
                CredentialPurpose(QQ_NAPCAT_ACCESS_TOKEN_PURPOSE),
            ) as access_token_handle,
            prepared.credential_port.resolve(
                event_secret_locator,
                CredentialPurpose(QQ_NAPCAT_EVENT_SECRET_PURPOSE),
            ) as event_secret_handle,
        ):

            def consume_access_token(
                access_token_view: memoryview,
            ) -> QQChannelBinding:
                def consume_event_secret(
                    event_secret_view: memoryview,
                ) -> QQChannelBinding:
                    try:
                        return create_qq_napcat_binding(
                            config=binding,
                            input_port=input_port,
                            access_token=access_token_view.tobytes(),
                            event_signing_secret=event_secret_view.tobytes(),
                        )
                    except QQNapCatBindingViolation:
                        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE") from None

                return event_secret_handle.consume(consume_event_secret)

            return access_token_handle.consume(consume_access_token)
    except ConfigurationViolation:
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE") from None


__all__ = (
    "QQ_NAPCAT_ACCESS_TOKEN_LOCATOR",
    "QQ_NAPCAT_ACCESS_TOKEN_PURPOSE",
    "QQ_NAPCAT_EVENT_SECRET_LOCATOR",
    "QQ_NAPCAT_EVENT_SECRET_PURPOSE",
    "QQChannelBinding",
    "compose_qq_channel",
)
