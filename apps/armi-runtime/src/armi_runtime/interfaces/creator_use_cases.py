"""HTTP and machine argument binding for transport-independent Creator use cases."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from armi_runtime.application.creator_calls import (
    CreatorActor,
    CreatorCall,
    CreatorUseCase,
)
from armi_runtime.application.interaction import InteractionResult
from armi_runtime.application.interaction_catalog import (
    InteractionRoute,
    interaction_routes,
)

from .bounded_http import read_bounded_body
from .browser_sessions import BrowserSessionStore, BrowserSessionViolation
from .creator_http import (
    _bearer,
    _browser_boundary,
    _rejected,
    _strict_object_pairs,
    _unavailable,
)
from .interaction_authority import verify_interaction


def _response(result: InteractionResult) -> Response:
    if result.status_code == 204:
        return Response(status_code=204)
    if result.content is not None:
        return Response(
            content=result.content,
            media_type=result.media_type,
            status_code=result.status_code,
        )
    return JSONResponse(content=dict(result.payload), status_code=result.status_code)


async def invoke_creator_use_case(
    route: InteractionRoute,
    use_case: CreatorUseCase,
    arguments: Mapping[str, object],
    actor: CreatorActor,
) -> InteractionResult:
    body = {name: arguments[name] for name in route.body_names if name in arguments}
    if route.body_version is not None:
        body["contract_version"] = route.body_version
    pairs = tuple(
        (
            name,
            str(arguments[name]).lower()
            if isinstance(arguments[name], bool)
            else str(arguments[name]),
        )
        for name in route.query_names
        if arguments.get(name) is not None
    )
    call = CreatorCall(
        actor=actor,
        input=cast(dict[str, Any], body),
        parameters=pairs,
        idempotency_key=None
        if arguments.get("idempotency_key") is None
        else str(arguments["idempotency_key"]),
    )
    return await use_case(
        call=call, **{name: arguments[name] for name in route.path_names}
    )


async def invoke_creator_http(
    request: Request,
    name: str,
    use_case: CreatorUseCase,
    *,
    browser_sessions: BrowserSessionStore | None,
    canonical_origin: str,
    maximum_bytes: int,
) -> Response:
    if browser_sessions is None:
        return JSONResponse(
            status_code=503,
            content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
        )
    if not _browser_boundary(request, canonical_origin=canonical_origin):
        return JSONResponse(status_code=403, content=_rejected("AUTH_BROWSER_BOUNDARY"))
    try:
        authority = verify_interaction(request, browser_sessions, _bearer(request))
    except BrowserSessionViolation as error:
        return JSONResponse(
            status_code=error.status_code, content=_rejected(error.code)
        )
    route = next(item for item in interaction_routes() if item.operation.name == name)
    body = {}
    if route.body_names:
        try:
            if request.headers.get("content-type") != "application/json":
                raise ValueError
            content = await read_bounded_body(
                request,
                maximum_bytes=maximum_bytes,
                timeout_seconds=float(
                    request.scope.get("armi.body_timeout_seconds", 10)
                ),
            )
            body = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_strict_object_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return JSONResponse(status_code=400, content=_rejected("INPUT_BODY"))
    keys = request.headers.getlist("idempotency-key")
    if len(keys) > 1:
        return JSONResponse(status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY"))
    call = CreatorCall(
        actor=CreatorActor(
            authority.creator_party_id, authority.default_scene_key, None
        ),
        input=cast(dict[str, Any], body),
        parameters=tuple(request.query_params.multi_items()),
        idempotency_key=keys[0] if keys else None,
    )
    return _response(
        await use_case(
            call=call, **{key: request.path_params[key] for key in route.path_names}
        )
    )


__all__ = ("invoke_creator_http", "invoke_creator_use_case")
