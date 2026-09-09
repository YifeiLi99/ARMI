"""The actual Runtime credential grants and their effect-free diagnostics."""

from armi_kernel.application import CredentialPurpose
from armi_local_control.configuration import ConfigurationViolation

from .creator_session import (
    CREATOR_BEARER_LOCATOR,
    CREATOR_CURSOR_PURPOSE,
    CREATOR_VERIFY_PURPOSE,
)
from .environment import PreparedEnvironment
from .qq_channel import (
    QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
    QQ_NAPCAT_ACCESS_TOKEN_PURPOSE,
    QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    QQ_NAPCAT_EVENT_SECRET_PURPOSE,
)


def runtime_credential_scope() -> dict[str, str]:
    return {
        "database.runtime": "database.runtime",
        CREATOR_VERIFY_PURPOSE: CREATOR_BEARER_LOCATOR,
        CREATOR_CURSOR_PURPOSE: CREATOR_BEARER_LOCATOR,
        "data_rights.identity_token": "data_rights.identity_token_key",
        "model.request": "model.ark_api_key",
        "speech.recognition": "speech.volc_credentials",
        "web.search": "model.ark_api_key",
        "codex.runner.auth": "codex.auth_json",
        QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
        QQ_NAPCAT_EVENT_SECRET_PURPOSE: QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    }


def inspect_runtime_credentials(prepared: PreparedEnvironment) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for purpose, name in runtime_credential_scope().items():
        locator = prepared.effective.config.secret_locators.get(name)
        item: dict[str, object] = {
            "purpose": purpose,
            "name": name,
            "locator": None if locator is None else locator.identity(),
        }
        if locator is None:
            item.update(status="missing", error_code="SEC-SECRET-NOT-CONFIGURED")
        else:
            try:
                handle = prepared.credential_port.resolve(
                    locator, CredentialPurpose(purpose)
                )
                handle.close()
                item.update(status="resolvable", error_code=None)
            except ConfigurationViolation as error:
                item.update(status="unavailable", error_code=error.code)
        checks.append(item)
    return {"checks": checks, "external_effects_dispatched": False}


__all__ = ("inspect_runtime_credentials", "runtime_credential_scope")
