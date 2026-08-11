"""QQ mapping adapter between ARMI's external-message ports and NapCat."""

from .adapter import (
    QQAdapterConfig,
    QQEffectAdapter,
    QQEgressAdapter,
    QQIngressAdapter,
    QQMediaFetchAdapter,
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
    "QQEffectAdapter",
    "QQEgressAdapter",
    "QQIngressAdapter",
    "QQMediaFetchAdapter",
    "QQNapCatBinding",
    "QQNapCatBindingConfig",
    "QQNapCatBindingViolation",
    "create_qq_event_app",
    "create_qq_napcat_binding",
    "load_qq_napcat_config",
)
