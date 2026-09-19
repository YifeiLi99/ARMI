"""Strict owner for the optional QQ-to-NapCat binding configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from armi_kernel import load_yaml_file

from .adapter import QQAdapterConfig

QQ_NAPCAT_CONFIG_SCHEMA = "armi.qq-napcat-channel.v4"


@dataclass(frozen=True, slots=True)
class QQNapCatBindingConfig:
    adapter: QQAdapterConfig
    api_base_url: str
    event_port: int
    request_body_max_bytes: int


def load_qq_napcat_config(path: Path) -> QQNapCatBindingConfig | None:
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError("QQ channel configuration is unreadable") from None
    if not path.is_file() or path.is_symlink() or size > 1_048_576:
        raise ValueError("QQ channel configuration must be a regular file")
    try:
        document = load_yaml_file(path)
    except OSError, ValueError:
        raise ValueError("QQ channel configuration is unreadable") from None
    expected = {
        "schema_version",
        "enabled",
        "account_id",
        "creator_user_id",
        "api_base_url",
        "event_port",
        "request_body_max_bytes",
        "private_user_blocklist",
        "allowed_groups",
    }
    if set(document) != expected:
        raise ValueError("QQ channel configuration shape is invalid")
    if document["schema_version"] != QQ_NAPCAT_CONFIG_SCHEMA:
        raise ValueError("QQ channel configuration version is invalid")
    if type(document["enabled"]) is not bool:
        raise ValueError("QQ channel enabled flag is invalid")
    if not document["enabled"]:
        return None
    groups = document["allowed_groups"]
    if type(groups) is not dict:
        raise ValueError("QQ group allowlist is invalid")
    groups = cast(dict[object, object], groups)
    if len(groups) > 1024:
        raise ValueError("QQ group allowlist is invalid")
    if any(
        type(key) is not str
        or not key.isdecimal()
        or key.startswith("0")
        or len(key) > 20
        for key in groups
    ):
        raise ValueError("QQ group allowlist is invalid")
    try:
        allowed_groups = {
            int(cast(str, key)): cast(str, value) for key, value in groups.items()
        }
    except TypeError, ValueError:
        raise ValueError("QQ group allowlist is invalid") from None
    if len(allowed_groups) != len(groups):
        raise ValueError("QQ group allowlist is invalid")
    account_id = document["account_id"]
    creator_user_id = document["creator_user_id"]
    api_base_url = document["api_base_url"]
    event_port = document["event_port"]
    request_body_max_bytes = document["request_body_max_bytes"]
    private_user_blocklist = document["private_user_blocklist"]
    if (
        type(account_id) is not int
        or type(creator_user_id) is not int
        or type(api_base_url) is not str
        or type(event_port) is not int
        or type(request_body_max_bytes) is not int
        or type(private_user_blocklist) is not list
    ):
        raise ValueError("QQ channel configuration values are invalid")
    blocklist_values = cast(list[object], private_user_blocklist)
    if any(type(item) is not int for item in blocklist_values):
        raise ValueError("QQ private blocklist is invalid")
    return QQNapCatBindingConfig(
        QQAdapterConfig(
            account_id,
            creator_user_id,
            allowed_groups,
            frozenset(cast(list[int], blocklist_values)),
        ),
        api_base_url,
        event_port,
        request_body_max_bytes,
    )


__all__ = (
    "QQ_NAPCAT_CONFIG_SCHEMA",
    "QQNapCatBindingConfig",
    "load_qq_napcat_config",
)
