"""Authenticated local machine transport over the shared interaction handlers."""

from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlencode
from uuid import UUID

from armi_local_control import ConfigurationViolation
from armi_local_control.binding import (
    AuthenticatedDelegate,
    InteractionAccess,
    binding_secret,
    read_binding,
)
from fastapi import FastAPI
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from armi_runtime.application.creator_commands import CreatorCommands
from armi_runtime.application.interaction import (
    InteractionApplication,
    InteractionInvocation,
    InteractionResult,
)

from .bounded_http import read_bounded_body
from .creator_http import _strict_object_pairs
from .interaction_catalog import InteractionRoute, interaction_routes
from .machine_commands import COMMAND_NAMES, invoke_command


class MachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: str
    arguments: dict[str, Any]


def _handler(
    route: InteractionRoute,
    endpoint: Callable[..., Awaitable[Response]],
    authority: str,
    commands: CreatorCommands,
) -> Callable[[InteractionInvocation], Awaitable[InteractionResult]]:
    validator = Draft202012Validator(dict(route.operation.input_schema))

    async def invoke(call: InteractionInvocation) -> InteractionResult:
        arguments: dict[str, Any] = dict(call.arguments)
        try:
            if not validator.is_valid(arguments):  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                raise SchemaValidationError("INTERACTION-ARGUMENTS")
        except SchemaValidationError:
            return InteractionResult(
                "rejected", {"error_code": "INTERACTION-ARGUMENTS"}, 400
            )
        if call.operation in COMMAND_NAMES:
            return await invoke_command(commands, call)
        path_values = {name: arguments[name] for name in route.path_names}
        body = {name: arguments[name] for name in route.body_names if name in arguments}
        if route.body_version is not None:
            body["contract_version"] = route.body_version
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"host", authority.encode("ascii")),
        ]
        for name, header in route.header_names:
            if name in arguments:
                headers.append(
                    (header.encode("ascii"), str(arguments[name]).encode("ascii"))
                )
        pairs: list[tuple[str, str]] = []
        for name in route.query_names:
            if name in arguments and arguments[name] is not None:
                value = arguments[name]
                items = cast(list[Any], value) if isinstance(value, list) else [value]
                pairs.extend(
                    (name, str(item).lower() if isinstance(item, bool) else str(item))
                    for item in items
                )
        sent = False

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": encoded, "more_body": False}

        # This is an in-process request adapter, not a browser session. No
        # browser token, Origin or Fetch Metadata is generated or accepted.
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": route.method,
                "scheme": "http",
                "path": route.path.format(**path_values),
                "query_string": urlencode(pairs).encode("ascii"),
                "headers": headers,
                "server": ("127.0.0.1", int(authority.rsplit(":", 1)[1])),
                "armi.authenticated_delegate": call.caller,
            },
            receive=receive,
        )
        response = (
            await endpoint()
            if route.operation_id in {"getHealthLive", "getHealthReady"}
            else await endpoint(**path_values, request=request)
        )
        if isinstance(response, BaseModel):
            return InteractionResult("returned", response.model_dump(mode="json"))
        content = bytes(response.body)
        media_type = response.media_type or "application/octet-stream"
        status: Literal["returned", "rejected", "unavailable"] = (
            "returned"
            if response.status_code < 400
            else "rejected"
            if response.status_code < 500
            else "unavailable"
        )
        if media_type == "application/json":
            return InteractionResult(status, json.loads(content), response.status_code)
        return InteractionResult(status, {}, response.status_code, content, media_type)

    return invoke


def register_machine_api(
    app: FastAPI,
    *,
    commands: CreatorCommands,
    environment_root: Path,
    environment_id: UUID,
    creator_party_id: UUID,
    authority: str,
    maximum_bytes: int,
) -> None:
    application = InteractionApplication()
    endpoints = {
        route.operation_id: route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
    }
    for route in interaction_routes():
        application.register(
            route.operation,
            _handler(route, endpoints[route.operation_id], authority, commands),
        )

    def authenticate(request: Request) -> AuthenticatedDelegate:
        if any(
            name in request.headers
            for name in (
                "origin",
                "cookie",
                "sec-fetch-site",
                "sec-fetch-mode",
                "sec-fetch-dest",
            )
        ):
            raise ValueError("INTERACTION-MACHINE-BOUNDARY")
        access = InteractionAccess.model_validate(
            read_binding(environment_root / "interaction-access.yaml")
        )
        if access.environment_id != environment_id:
            raise ValueError("INTERACTION-ENVIRONMENT-MISMATCH")
        selected = UUID(request.headers.get("x-armi-delegate", ""))
        binding = next(
            (item for item in access.delegates if item.delegate_id == selected), None
        )
        if binding is None or binding.creator_party_id != creator_party_id:
            raise ValueError("INTERACTION-DELEGATE-REJECTED")
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise ValueError("INTERACTION-CREDENTIAL-REQUIRED")
        supplied = base64.b64decode(authorization[7:], validate=True)
        if not hmac.compare_digest(supplied, binding_secret(binding, environment_root)):
            raise ValueError("INTERACTION-CREDENTIAL-REJECTED")
        return AuthenticatedDelegate(
            environment_id=environment_id,
            creator_party_id=creator_party_id,
            delegate_id=selected,
            scopes=binding.scopes,
        )

    @app.post("/machine/v1/invoke", include_in_schema=False)
    async def invoke_machine(request: Request) -> JSONResponse:
        try:
            caller = authenticate(request)
        except ValueError, OSError, ValidationError, ConfigurationViolation:
            return JSONResponse(
                {"status": "rejected", "error_code": "INTERACTION-AUTH-REJECTED"},
                status_code=403,
            )
        raw = await read_bounded_body(
            request, maximum_bytes=maximum_bytes, timeout_seconds=10
        )
        try:
            call = MachineRequest.model_validate(
                json.loads(raw, object_pairs_hook=_strict_object_pairs)
            )
        except ValueError, ValidationError:
            return JSONResponse(
                {"status": "rejected", "error_code": "INTERACTION-REQUEST"},
                status_code=400,
            )
        if call.operation == "capabilities":
            if call.arguments:
                return JSONResponse(
                    {"status": "rejected", "error_code": "INTERACTION-ARGUMENTS"},
                    status_code=400,
                )
            return JSONResponse(
                {
                    "environment_id": str(environment_id),
                    "delegate_id": str(caller.delegate_id),
                    "operations": [
                        {
                            "name": item.name,
                            "required_scope": "interaction.write"
                            if item.mutating
                            else "interaction.read",
                            "authorized": (
                                "interaction.write"
                                if item.mutating
                                else "interaction.read"
                            )
                            in caller.scopes,
                        }
                        for item in application.operations()
                    ],
                }
            )
        result = await application.invoke(
            InteractionInvocation(call.operation, call.arguments, caller)
        )
        payload: dict[str, Any] = {
            "environment_id": str(environment_id),
            "status": result.status,
            "result": dict(result.payload),
        }
        if result.content is not None:
            payload["artifact"] = {
                "media_type": result.media_type,
                "encoding": "base64",
                "content": base64.b64encode(result.content).decode("ascii"),
            }
        return JSONResponse(payload, status_code=result.status_code)

    del invoke_machine


__all__ = ("register_machine_api",)
