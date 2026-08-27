"""Bounded ASGI request-body reading shared by local HTTP interfaces."""

from __future__ import annotations

import asyncio

from starlette.requests import ClientDisconnect, Request


class BoundedBodyViolation(RuntimeError):
    """The peer exceeded a transport budget before a body was accepted."""

    def __init__(self, code: str, *, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


async def read_bounded_body(
    request: Request,
    *,
    maximum_bytes: int,
    timeout_seconds: float,
) -> bytes:
    """Read an ASGI body once while enforcing size and wall-clock budgets."""

    if maximum_bytes <= 0 or timeout_seconds <= 0:
        raise ValueError("bounded body budgets must be positive")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            raise BoundedBodyViolation(
                "HTTP-CONTENT-LENGTH-INVALID", status_code=400
            ) from None
        if declared_size < 0:
            raise BoundedBodyViolation("HTTP-CONTENT-LENGTH-INVALID", status_code=400)
        if declared_size > maximum_bytes:
            raise BoundedBodyViolation("HTTP-BODY-TOO-LARGE", status_code=413)

    chunks: list[bytes] = []
    total = 0
    try:
        async with asyncio.timeout(timeout_seconds):
            async for chunk in request.stream():
                total += len(chunk)
                if total > maximum_bytes:
                    raise BoundedBodyViolation("HTTP-BODY-TOO-LARGE", status_code=413)
                if chunk:
                    chunks.append(chunk)
    except TimeoutError:
        raise BoundedBodyViolation("HTTP-BODY-TIMEOUT", status_code=408) from None
    except ClientDisconnect:
        raise BoundedBodyViolation("HTTP-BODY-INCOMPLETE", status_code=400) from None
    if declared is not None and total != int(declared):
        raise BoundedBodyViolation("HTTP-BODY-INCOMPLETE", status_code=400)
    return b"".join(chunks)


__all__ = ("BoundedBodyViolation", "read_bounded_body")
