"""Authorized autonomous plan and history queries."""

from typing import Annotated, Literal

from armi_local_control import AutonomyHistory, AutonomyStatus
from fastapi import FastAPI, HTTPException, Query, Request, Security
from fastapi.security import HTTPBearer

from armi_runtime.application.creator_system import CreatorSystem

from .creator_http import BrowserSessionStore, JSONResponse
from .creator_routes_system import authorize_system


def register_autonomy_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    browser_sessions: BrowserSessionStore | None,
    system: CreatorSystem,
) -> None:
    async def invoke(
        request: Request,
        mode: Literal["status", "history"],
        limit: int = 25,
        offset: int = 0,
    ) -> JSONResponse:
        denied = authorize_system(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        if system.autonomy is None:
            raise HTTPException(503, detail="LIFE-AUTONOMY-QUERY-UNAVAILABLE")
        return JSONResponse(
            await system.autonomy.query(mode, limit, offset),
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/v1/autonomy/status",
        operation_id="getAutonomyStatus",
        response_model=AutonomyStatus,
        dependencies=[Security(bearer)],
    )
    async def status(request: Request) -> JSONResponse:
        return await invoke(request, "status")

    @app.get(
        "/v1/autonomy/history",
        operation_id="listAutonomyHistory",
        response_model=AutonomyHistory,
        dependencies=[Security(bearer)],
    )
    async def history(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JSONResponse:
        return await invoke(request, "history", limit, offset)

    del status, history
