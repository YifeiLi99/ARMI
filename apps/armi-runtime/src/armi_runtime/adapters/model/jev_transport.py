"""Jev transport: retry only a connection failure before request transmission."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from armi_kernel.application import MeteredProviderCall, provider_call
from armi_mood.api import JEV_MODEL


@asynccontextmanager
async def jev_request(
    request: httpx.Request, *, timeout_seconds: float
) -> AsyncGenerator[tuple[httpx.Response, MeteredProviderCall]]:
    # Each physical attempt has a durable receipt; cognition keeps one frozen
    # request and one decision. Read/write timeouts and cancellation never retry.
    parent_call_id = None
    for attempt in (1, 2):
        try:
            async with (
                provider_call(
                    provider="typesafe",
                    model=JEV_MODEL,
                    service="generation",
                    parent_call_id=parent_call_id,
                    transport_attempt=attempt,
                    transport_attempt_limit=2,
                ) as call,
                httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout_seconds, connect=3.0),
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
            ):
                parent_call_id = call.receipt.call_id
                try:
                    response = await client.send(request)
                except (httpx.ConnectTimeout, httpx.ConnectError) as error:
                    await call.not_sent(
                        error_code="USAGE-CONNECT-TIMEOUT"
                        if isinstance(error, httpx.ConnectTimeout)
                        else "USAGE-CONNECT-FAILED"
                    )
                    raise
                yield response, call
                return
        except httpx.ConnectTimeout, httpx.ConnectError:
            if attempt == 2:
                raise
            await asyncio.sleep(0.5)
