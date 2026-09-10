"""Structured installer CLI and stdio MCP over the same application service."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from armi_kernel.application import PersonalityAnchor
from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from armi_admin.application.installation import (
    SetupApplication,
    SetupCredentialRequest,
    SetupError,
    SetupPaths,
)
from armi_admin.composition import bootstrap_setup


class SetupAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["armi.personality-anchor.v1"]
    voice_style: str
    traits: list[str] = Field(min_length=1, max_length=8)

    def domain(self) -> PersonalityAnchor:
        return PersonalityAnchor(
            self.schema_version, self.voice_style, tuple(self.traits)
        )


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "status", "check", "prepare", "birth", "credential", "login_startup", "admin"
    ]
    enabled: bool | None = None
    credential: SetupCredentialRequest | None = None
    personality_anchor: SetupAnchor | None = None
    operation_id: str | None = None
    operation: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def dispatch(application: SetupApplication, request: SetupRequest) -> dict[str, Any]:
    try:
        if request.action == "status":
            return application.status()
        if request.action == "check":
            return application.check()
        if request.action == "prepare":
            if request.operation_id is None:
                raise SetupError("SETUP-OPERATION-ID-REQUIRED")
            return application.prepare(operation_id=request.operation_id)
        if request.action == "birth":
            if request.personality_anchor is None:
                raise SetupError("SETUP-PERSONALITY-ANCHOR-REQUIRED")
            return application.birth(request.personality_anchor.domain())
        if request.action == "credential":
            if request.credential is None:
                raise SetupError("SETUP-CREDENTIAL-REQUEST-REQUIRED")
            return application.credential(request.credential)
        if request.action == "login_startup":
            return application.login_startup(request.enabled)
        if request.operation is None:
            raise SetupError("SETUP-ADMIN-OPERATION-REQUIRED")
        return application.invoke(request.operation, request.arguments)
    except SetupError as error:
        return {"status": "failed", "error_code": str(error)}
    except Exception:
        # Pydantic and provider exceptions can contain submitted credentials.
        return {"status": "failed", "error_code": "SETUP-OPERATION-FAILED"}


def application_from_arguments(argv: list[str] | None = None) -> SetupApplication:
    parser = argparse.ArgumentParser(prog="armi-setup")
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--installation-root", type=Path)
    args = parser.parse_args(argv)
    installation = args.installation_root
    if installation is None:
        value = os.environ.get("ARMI_INSTALLATION_ROOT")
        if not value:
            raise SetupError("SETUP-INSTALLATION-ROOT-REQUIRED")
        installation = Path(value)
    return bootstrap_setup(
        SetupPaths(
            environment_root=args.environment_root,
            installation_root=installation,
        )
    )


def main(argv: list[str] | None = None) -> int:
    try:
        application = application_from_arguments(argv)
        payload = sys.stdin.buffer.read(65_537)
        if len(payload) > 65_536:
            raise SetupError("SETUP-INPUT-TOO-LARGE")
        result = dispatch(application, SetupRequest.model_validate_json(payload))
    except Exception:
        result = {"status": "failed", "error_code": "SETUP-INPUT-INVALID"}
    print(json.dumps(result, ensure_ascii=False))
    return (
        1 if result["status"] in {"failed", "incomplete", "reconcile_required"} else 0
    )


def mcp_main(argv: list[str] | None = None) -> None:
    application = application_from_arguments(argv)
    server = MCPServer(
        name="armi_setup",
        version="1.0.0",
        instructions="Configure one explicit local ARMI environment. Use status to recover its operation identity. Never replay an uncertain database installation.",
        tools=[],
        resources=[],
        extensions=[],
        log_level="ERROR",
    )

    def setup(request: SetupRequest) -> dict[str, Any]:
        return dispatch(application, request)

    server.add_tool(setup, name="setup", structured_output=True)
    server.run("stdio")


if __name__ == "__main__":
    raise SystemExit(main())
