"""Authorized Creator usage queries over the common read use case."""

from typing import Annotated, Literal

from armi_kernel.application import UsageFilter, UsageQuery
from armi_local_control import UsageCall, UsageCalls, UsageSummary
from fastapi import FastAPI, HTTPException, Query, Request, Security
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from armi_runtime.application.creator_system import CreatorSystem

from .creator_http import BrowserSessionStore, JSONResponse
from .creator_routes_system import authorize_system


class UsageParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str | None = None
    end: str | None = None
    service: str | None = None
    model: str | None = None
    purpose: str | None = None
    outcome: str | None = None
    cost_status: str | None = None
    operation_id: str | None = None

    def filters(self) -> UsageFilter:
        return UsageFilter.from_strings(**self.model_dump())


class UsageListParameters(UsageParameters):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    def filters(self) -> UsageFilter:
        return UsageFilter.from_strings(**self.model_dump(exclude={"limit", "offset"}))


def register_usage_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    browser_sessions: BrowserSessionStore | None,
    system: CreatorSystem,
) -> None:
    async def invoke(
        request: Request,
        mode: Literal["summary", "list", "read"],
        parameters: UsageParameters,
        call_id: str | None = None,
    ) -> JSONResponse:
        denied = authorize_system(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        if system.usage is None:
            raise HTTPException(503, detail="USAGE-QUERY-UNAVAILABLE")
        try:
            query = UsageQuery(
                mode,
                parameters.filters(),
                parameters.limit if isinstance(parameters, UsageListParameters) else 25,
                parameters.offset if isinstance(parameters, UsageListParameters) else 0,
                call_id,
            )
            payload = await system.usage.query(query)
        except ValueError as error:
            code = str(error)
            raise HTTPException(
                404 if code == "USAGE-CALL-NOT-FOUND" else 422,
                detail=code if code.startswith("USAGE-") else "USAGE-QUERY-INVALID",
            ) from None
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get(
        "/v1/usage/summary",
        operation_id="getUsageSummary",
        response_model=UsageSummary,
        dependencies=[Security(bearer)],
    )
    async def summary(
        request: Request, parameters: Annotated[UsageParameters, Query()]
    ) -> JSONResponse:
        return await invoke(request, "summary", parameters)

    @app.get(
        "/v1/usage/calls",
        operation_id="listUsageCalls",
        response_model=UsageCalls,
        dependencies=[Security(bearer)],
    )
    async def calls(
        request: Request, parameters: Annotated[UsageListParameters, Query()]
    ) -> JSONResponse:
        return await invoke(request, "list", parameters)

    @app.get(
        "/v1/usage/calls/{call_id}",
        operation_id="readUsageCall",
        response_model=UsageCall,
        dependencies=[Security(bearer)],
    )
    async def read(request: Request, call_id: str) -> JSONResponse:
        return await invoke(request, "read", UsageParameters(), call_id)

    del summary, calls, read
