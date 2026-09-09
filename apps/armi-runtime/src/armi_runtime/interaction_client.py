"""Shared local interaction client used by both CLI and MCP."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import httpx
from armi_local_control import ConfigurationViolation
from armi_local_control.binding import InteractionClientBinding, binding_secret
from jsonschema import Draft202012Validator

from .application.artifact_transfer import ArtifactChunk
from .application.interaction_catalog import interaction_routes

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
    async def import_media(
        self, path: Path, *, idempotency_key: str, media_type: str | None = None
    ) -> dict[str, Any]:
        import mimetypes

        from .application.media_uploads import UploadDeclaration

        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if not 1 <= size <= 45 * 1024 * 1024:
                raise ValueError("UPLOAD-SIZE")
            digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            declaration = UploadDeclaration(
                file_name=path.name,
                byte_size=size,
                content_digest=digest,
                media_type=media_type
                or mimetypes.guess_file_type(path)[0]
                or "application/octet-stream",
            )
            outcome = await self.invoke(
                "upload_begin",
                {
                    **declaration.model_dump(),
                    "idempotency_key": idempotency_key,
                },
            )
            if outcome.get("transport_status", 200) >= 400:
                return outcome
            record = outcome["result"]
            if record["state"] == "cancelled":
                return outcome
            while record["state"] == "receiving" and record["received_bytes"] < size:
                stream.seek(record["received_bytes"])
                content = stream.read(min(128 * 1024, size - record["received_bytes"]))
                if not content:
                    raise ValueError("UPLOAD-FILE-CHANGED")
                outcome = await self.invoke(
                    "upload_append",
                    {
                        "upload_id": record["upload_id"],
                        "offset": record["received_bytes"],
                        "content": base64.b64encode(content).decode("ascii"),
                    },
                )
                if outcome.get("transport_status", 200) >= 400:
                    return outcome
                record = outcome["result"]
            return await self.invoke(
                "upload_complete", {"upload_id": record["upload_id"]}
            )

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

    async def download_artifact(
        self, arguments: dict[str, Any], output: Path
    ) -> dict[str, Any]:
        if arguments.get("offset", 0) != 0:
            raise ValueError("INTERACTION-ARTIFACT-OUTPUT-RANGE")
        if output.exists():
            raise FileExistsError(output)
        temporary = output.with_name("." + output.name + "." + str(uuid7()) + ".part")
        offset = 0
        expected: tuple[int, str, str] | None = None
        digest = hashlib.sha256()
        try:
            with temporary.open("xb") as stream:
                while True:
                    result = await self.invoke(
                        "artifact_read", {**arguments, "offset": offset}
                    )
                    if result["transport_status"] >= 400:
                        return result
                    metadata = ArtifactChunk.model_validate(result["result"])
                    artifact = result["artifact"]
                    content = base64.b64decode(artifact["content"], validate=True)
                    identity = (
                        metadata.total_bytes,
                        metadata.digest,
                        artifact["media_type"],
                    )
                    if (
                        metadata.offset != offset
                        or metadata.byte_count != len(content)
                        or (expected is not None and expected != identity)
                        or (
                            metadata.next_offset is not None
                            and metadata.next_offset != offset + len(content)
                        )
                        or (metadata.next_offset is not None and not content)
                    ):
                        raise ValueError("INTERACTION-ARTIFACT-CHANGED")
                    expected = identity
                    stream.write(content)
                    digest.update(content)
                    offset += len(content)
                    if metadata.next_offset is None:
                        if (
                            offset != metadata.total_bytes
                            or "sha256:" + digest.hexdigest() != metadata.digest
                        ):
                            raise ValueError("INTERACTION-ARTIFACT-INTEGRITY")
                        break
                stream.flush()
                os.fsync(stream.fileno())
            # Linking publishes the completed file atomically and cannot overwrite.
            os.link(temporary, output)
            result["artifact"] = {
                "path": str(output.resolve()),
                "size_bytes": offset,
                "media_type": expected[2],
            }
            return result
        finally:
            temporary.unlink(missing_ok=True)

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
                in {
                    "completed",
                    "partial",
                    "failed",
                    "unknown",
                    "rejected",
                    "unavailable",
                }
                or stage in _STOP_STAGES
            ):
                result["wait_status"] = "returned"
                return result
            await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))


__all__ = ("InteractionClient", "interaction_failure")
