"""Trusted-terminal bootstrap-code issuance over the loopback Runtime route."""

from __future__ import annotations

import http.client
import json

from armi_kernel.application import CredentialPurpose

from armi_runtime.interfaces.browser_sessions import BrowserSessionViolation
from armi_runtime.interfaces.creator_contract import BootstrapCodeResponse

from .configuration import ConfigurationViolation
from .creator_session import (
    CREATOR_BEARER_LOCATOR,
    CREATOR_ISSUE_PURPOSE,
)
from .environment import PreparedEnvironment


def issue_browser_bootstrap(prepared: PreparedEnvironment) -> BootstrapCodeResponse:
    """Issue one code without proxy lookup, bearer arguments, or persistence."""

    locator = prepared.effective.config.secret_locators.get(CREATOR_BEARER_LOCATOR)
    if locator is None:
        raise BrowserSessionViolation("SEC_CREATOR_BEARER_MISSING", status_code=503)
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose(CREATOR_ISSUE_PURPOSE),
        ) as handle:

            def invoke(value: memoryview) -> BootstrapCodeResponse:
                try:
                    bearer = bytes(value).decode("ascii")
                except UnicodeDecodeError:
                    raise BrowserSessionViolation(
                        "SEC_CREATOR_BEARER_FORMAT", status_code=503
                    ) from None
                config = prepared.effective.config.creator
                connection = http.client.HTTPConnection(
                    config.bind_host,
                    config.port,
                    timeout=5,
                )
                try:
                    connection.request(
                        "POST",
                        "/v1/browser-bootstrap-codes",
                        body=b"",
                        headers={
                            "Authorization": f"Bearer {bearer}",
                            "Content-Length": "0",
                        },
                    )
                    response = connection.getresponse()
                    body = response.read(config.request_body_max_bytes + 1)
                except OSError:
                    raise BrowserSessionViolation(
                        "DEPENDENCY_CREATOR_RUNTIME_UNAVAILABLE",
                        status_code=503,
                    ) from None
                finally:
                    connection.close()
                if response.status != 200 or len(body) > config.request_body_max_bytes:
                    code = (
                        "AUTH_RATE_LIMITED"
                        if response.status == 429
                        else "AUTH_CREATOR_REJECTED"
                        if response.status in {401, 403}
                        else "DEPENDENCY_CREATOR_RUNTIME_UNAVAILABLE"
                    )
                    raise BrowserSessionViolation(code, status_code=response.status)
                try:
                    payload = json.loads(body.decode("utf-8"))
                    return BootstrapCodeResponse.model_validate(payload)
                except UnicodeDecodeError, ValueError:
                    raise BrowserSessionViolation(
                        "DEPENDENCY_CREATOR_RUNTIME_INVALID",
                        status_code=503,
                    ) from None

            return handle.consume(invoke)
    except ConfigurationViolation:
        raise BrowserSessionViolation(
            "SEC_CREATOR_BEARER_UNAVAILABLE", status_code=503
        ) from None


__all__ = ("issue_browser_bootstrap",)
