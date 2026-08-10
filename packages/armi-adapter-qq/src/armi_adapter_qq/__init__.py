"""QQ mapping adapter between ARMI's external-group ports and NapCat."""

from .adapter import (
    QQAdapterConfig,
    QQGroupEffectAdapter,
    QQGroupEgressAdapter,
    QQGroupIngressAdapter,
)
from .binding import (
    QQNapCatBinding,
    QQNapCatBindingViolation,
    create_qq_napcat_binding,
)
from .config import (
    QQ_NAPCAT_CONFIG_SCHEMA,
    QQNapCatBindingConfig,
    load_qq_napcat_config,
)
from .webhook import create_qq_event_app

__all__ = (
    "QQ_NAPCAT_CONFIG_SCHEMA",
    "QQAdapterConfig",
    "QQGroupEffectAdapter",
    "QQGroupEgressAdapter",
    "QQGroupIngressAdapter",
    "QQNapCatBinding",
    "QQNapCatBindingConfig",
    "QQNapCatBindingViolation",
    "create_qq_event_app",
    "create_qq_napcat_binding",
    "load_qq_napcat_config",
)
