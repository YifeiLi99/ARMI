"""Authenticated local machine transport over the shared interaction handlers."""

from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from armi_local_control import ConfigurationViolation
from armi_local_control.binding import (
    AuthenticatedDelegate,
    InteractionAccess,
    binding_secret,
    read_binding,
)
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from armi_runtime.application.creator_calls import CreatorActor, CreatorUseCase
from armi_runtime.application.creator_commands import CreatorCommands
from armi_runtime.application.creator_system import CreatorSystem
from armi_runtime.application.interaction import (
    InteractionApplication,
    InteractionInvocation,
    InteractionResult,
)
from armi_runtime.application.interaction_catalog import (
    InteractionRoute,
    interaction_routes,
)
from armi_runtime.application.media_uploads import (
    UPLOAD_REQUESTS,
    MediaUploads,
    invoke_upload,
)

from .bounded_http import read_bounded_body
from .creator_http import _strict_object_pairs
from .creator_use_cases import invoke_creator_use_case
from .machine_commands import COMMAND_NAMES, invoke_command
from .system_commands import SYSTEM_COMMANDS, invoke_system


class MachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: str
    arguments: dict[str, Any]


def _handler(
    route: InteractionRoute,
    commands: CreatorCommands,
    system: CreatorSystem,
    use_cases: Mapping[str, CreatorUseCase],
    uploads: MediaUploads | None,
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
        if call.operation in UPLOAD_REQUESTS:
            return await invoke_upload(uploads, call)
        if call.operation in COMMAND_NAMES:
            return await invoke_command(commands, call)
        if call.operation in SYSTEM_COMMANDS:
            return await invoke_system(system, call.operation, call.arguments)
        if call.operation in use_cases:
            return await invoke_creator_use_case(
                route,
                use_cases[call.operation],
                call.arguments,
                CreatorActor(
                    call.caller.creator_party_id,
                    call.caller.default_scene_key,
                    call.caller.delegate_id,
                ),
            )
        raise ValueError("INTERACTION-APPLICATION-COVERAGE")

    return invoke


def register_machine_api(
    app: FastAPI,
    *,
    commands: CreatorCommands,
    system: CreatorSystem,
    use_cases: Mapping[str, CreatorUseCase],
    environment_root: Path,
    environment_id: UUID,
    creator_party_id: UUID,
    maximum_bytes: int,
    uploads: MediaUploads | None = None,
) -> None:
    application = InteractionApplication()
    routes = interaction_routes()
    implemented = (
        COMMAND_NAMES | SYSTEM_COMMANDS | use_cases.keys() | UPLOAD_REQUESTS.keys()
    )
    if frozenset(route.operation.name for route in routes) != implemented:
        raise ValueError("INTERACTION-APPLICATION-COVERAGE")
    for route in routes:
        application.register(
            route.operation,
            _handler(
                route,
                commands,
                system,
                use_cases,
                uploads,
            ),
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
                            "request_schema": dict(item.input_schema),
                            "result_schema": dict(item.output_schema),
                            "read_only": not item.mutating,
                            "runtime_readiness": system.readiness().value,
                            "configuration_state": "not_checked",
                            "availability": "unavailable"
                            if (
                                "interaction.write"
                                if item.mutating
                                else "interaction.read"
                            )
                            not in caller.scopes
                            else "available"
                            if item.name == "health_live"
                            else "not_verified",
                            "unavailable_reason": "scope_not_granted"
                            if (
                                "interaction.write"
                                if item.mutating
                                else "interaction.read"
                            )
                            not in caller.scopes
                            else None,
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
