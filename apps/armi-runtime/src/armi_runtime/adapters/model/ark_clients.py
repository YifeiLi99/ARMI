"""Runtime-owned official Ark clients and content-free transport diagnostics."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from time import monotonic

import httpx

# Official SDK 0.8.0 has inline annotations but does not ship py.typed.
from arkruntime import AsyncArk  # pyright: ignore[reportMissingTypeStubs]
from armi_kernel.application import ModelBinding, ModelViolation

ArkDiagnostic = Callable[[str, int, tuple[str, ...]], None]


class ArkClients(AbstractAsyncContextManager["ArkClients"]):
    """Share connections across per-context adapters; close after workers stop."""

    def __init__(self, diagnostic: ArkDiagnostic | None = None) -> None:
        self._clients: dict[tuple[str, float, bytes], AsyncArk] = {}
        self._diagnostic = diagnostic
        self._closed = False

    def get(self, api_key: memoryview, binding: ModelBinding) -> AsyncArk:
        if self._closed:
            raise ModelViolation("MODEL-CLIENT-CLOSED")
        try:
            key = bytes(api_key).decode("utf-8")
        except UnicodeDecodeError:
            raise ModelViolation("MODEL-CREDENTIAL") from None
        identity = (
            binding.api_base,
            binding.timeout_seconds,
            hashlib.sha256(api_key).digest(),
        )
        if identity not in self._clients:
            # Official SDK recommends one reusable client. See DESIGN.md.
            # Credential changes select a new client without changing in-flight auth.
            self._clients[identity] = AsyncArk(
                api_key=key,
                base_url=binding.api_base,
                timeout=binding.timeout_seconds,
                # Cognition owns retry budgets; never replay generation invisibly.
                max_retries=0,
                http_client=httpx.AsyncClient(
                    trust_env=False,
                    event_hooks={
                        "request": [self._on_request],
                        "response": [self._on_response],
                    },
                ),
            )
        return self._clients[identity]

    async def close(self) -> None:
        self._closed = True
        try:
            for client in self._clients.values():
                await client.close()
        finally:
            self._clients.clear()

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _on_request(self, request: httpx.Request) -> None:
        started = monotonic()
        service = (
            "tokenization"
            if request.url.path.endswith("/tokenization")
            else "generation"
        )
        request.extensions["armi_started"] = started
        request.extensions["armi_service"] = service

        async def trace(event: str, info: dict[str, object]) -> None:
            if self._diagnostic is None:
                return
            # Only fixed transport phases and exception class names. Never log
            # exception messages, request headers, prompts or response bodies.
            if event not in {
                "connection.connect_tcp.complete",
                "connection.connect_tcp.failed",
                "connection.start_tls.complete",
                "connection.start_tls.failed",
                "http11.receive_response_headers.failed",
                "http11.receive_response_body.failed",
            }:
                return
            self._diagnostic(
                f"model.ark.{service}.{event}",
                round((monotonic() - started) * 1000),
                _exception_codes(info.get("exception")),
            )

        request.extensions["trace"] = trace

    async def _on_response(self, response: httpx.Response) -> None:
        if self._diagnostic is not None:
            self._diagnostic(
                f"model.ark.{response.request.extensions['armi_service']}.response",
                round(
                    (monotonic() - response.request.extensions["armi_started"]) * 1000
                ),
                (f"HTTP-{response.status_code}",),
            )


def _exception_codes(error: object) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[int] = set()
    while isinstance(error, BaseException) and id(error) not in seen and len(codes) < 8:
        seen.add(id(error))
        name = type(error).__name__.upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", name):
            codes.append(f"EXCEPTION-{name}")
        error = error.__cause__ or error.__context__
    return tuple(codes)
