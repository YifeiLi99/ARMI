"""Shared local interaction client used by both CLI and MCP."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any, cast

import httpx
from armi_local_control import ConfigurationViolation
from armi_local_control.binding import InteractionClientBinding, binding_secret
from jsonschema import Draft202012Validator

from .interfaces.interaction_catalog import interaction_routes

_STOP_STAGES = frozenset(
    {
        "no_action",
        "no_change",
        "applied",
        "partial",
        "partially_completed",
        "declined",
        "deferred",
        "ended",
        "need_information",
        "awaiting_authorization",
        "confirmation_required",
        "authorization_denied",
        "stale",
        "completed",
        "failed",
        "unknown",
        "cancelled",
        "unavailable",
        "candidate_rejected",
    }
)


def interaction_failure(error: Exception) -> dict[str, Any]:
    """One redacted error contract for both machine transports."""
    if isinstance(error, httpx.HTTPError):
        code, status = "INTERACTION-TRANSPORT-UNAVAILABLE", 503
    elif isinstance(error, ConfigurationViolation):
        code, status = "INTERACTION-CREDENTIAL-UNAVAILABLE", 503
    elif isinstance(error, FileExistsError):
        code, status = "INTERACTION-OUTPUT-EXISTS", 409
    elif isinstance(error, OSError):
        code, status = "INTERACTION-LOCAL-IO", 503
    elif isinstance(error, json.JSONDecodeError):
        code, status = "INTERACTION-RESPONSE-CONTRACT", 503
    else:
        message = str(error)
        code = (
            message
            if re.fullmatch(r"INTERACTION-[A-Z0-9-]{1,96}", message)
            else "INTERACTION-INPUT"
        )
        status = (
            503
            if code.startswith("INTERACTION-RESPONSE-")
            or code == "INTERACTION-ENVIRONMENT-MISMATCH"
            else 400
        )
    return {
        "status": "unavailable" if status >= 500 else "rejected",
        "error_code": code,
        "transport_status": status,
    }


class InteractionClient:
    def __init__(
        self,
        binding: InteractionClientBinding,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.binding = binding
        self._transport = transport
        self._routes = {route.operation.name: route for route in interaction_routes()}

    async def invoke(
        self, operation: str, arguments: dict[str, Any], *, timeout: float = 25
    ) -> dict[str, Any]:
        if operation == "capabilities" and arguments:
            raise ValueError("INTERACTION-ARGUMENTS")
        if operation != "capabilities":
            route = self._routes.get(operation)
            if route is None:
                raise ValueError("INTERACTION-OPERATION-UNKNOWN")
            if not Draft202012Validator(dict(route.operation.input_schema)).is_valid(  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                arguments
            ):
                raise ValueError("INTERACTION-ARGUMENTS")
        credential = binding_secret(self.binding, self.binding.environment_root)
        headers = {
            "authorization": "Bearer " + base64.b64encode(credential).decode("ascii"),
            "x-armi-delegate": str(self.binding.delegate_id),
        }
        async with (
            httpx.AsyncClient(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=timeout,
            ) as client,
            client.stream(
                "POST",
                self.binding.endpoint + "/machine/v1/invoke",
                headers=headers,
                json={"operation": operation, "arguments": arguments},
            ) as response,
        ):
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 32 * 1024 * 1024:
                    raise ValueError("INTERACTION-RESPONSE-SIZE")
            result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("INTERACTION-RESPONSE-CONTRACT")
        result = cast(dict[str, Any], result)
        if response.status_code < 400 and result.get("environment_id") != str(
            self.binding.environment_id
        ):
            raise ValueError("INTERACTION-ENVIRONMENT-MISMATCH")
        result["transport_status"] = response.status_code
        return result

    async def wait(
        self, result_ref: str, *, timeout_seconds: float = 20
    ) -> dict[str, Any]:
        if not 0 < timeout_seconds <= 25:
            raise ValueError("INTERACTION-WAIT-TIMEOUT")
        deadline = time.monotonic() + timeout_seconds
        result: dict[str, Any] = {}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["wait_status"] = "timeout"
                result["resume_ref"] = result_ref
                return result
            try:
                result = await self.invoke(
                    "operation_get",
                    {"result_ref": result_ref},
                    timeout=max(0.1, remaining),
                )
            except httpx.TimeoutException:
                return {**result, "wait_status": "timeout", "resume_ref": result_ref}
            except httpx.TransportError:
                return {
                    **result,
                    "wait_status": "disconnected",
                    "resume_ref": result_ref,
                }
            outcome = result.get("result", {})
            stage = outcome.get("details", {}).get("stage")
            if (
                result["transport_status"] >= 400
                or outcome.get("status")
                in {"completed", "failed", "unknown", "rejected", "unavailable"}
                or stage in _STOP_STAGES
            ):
                result["wait_status"] = "returned"
                return result
            await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))


__all__ = ("InteractionClient", "interaction_failure")
