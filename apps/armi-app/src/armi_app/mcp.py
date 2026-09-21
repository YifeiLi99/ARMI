"""One local stdio MCP server over independently authorized application services."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

from armi_admin.application import (
    AdminConfigError,
    AdminSecretError,
)
from armi_admin.application.installation import SetupApplication, SetupError, SetupPaths
from armi_admin.application.setup_operations import SetupRequest, dispatch
from armi_admin.composition import bootstrap_setup
from armi_admin.machine import ADMIN_OPERATIONS, AdminSession
from armi_local_control import program_installation_root
from armi_local_control.binding import load_client_binding, read_binding
from armi_local_control.windows_package import package_identity
from armi_runtime.machine import InteractionClient
from jsonschema import Draft202012Validator
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import BaseModel, ConfigDict, ValidationError

from .interaction_tools import InteractionTools

_SETUP_FIELDS = {
    "status": (),
    "check": (),
    "prepare": ("operation_id",),
    "birth": ("personality_anchor",),
    "credential": ("credential",),
    "login_startup": ("enabled",),
    "update": ("update",),
    "uninstall": ("delete_data",),
    "napcat": ("napcat",),
}
_OPTIONAL_SETUP = {"status", "check", "login_startup", "uninstall"}


class MCPBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.mcp-binding.v1"]
    admin_config: str | None = None
    interaction_config: str | None = None


def _result(value: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
        structured_content=value,
        is_error=value.get("status") in {"rejected", "failed", "conflict", "unknown"},
    )


class ARMIMCPServer(MCPServer[Any]):
    def __init__(
        self,
        *,
        admin: AdminSession | None,
        client_path: Path | None,
        setup: SetupApplication | None = None,
    ) -> None:
        super().__init__(
            name="armi",
            title="ARMI",
            version="1.0.0",
            tools=[],
            resources=[],
            extensions=[],
            log_level="ERROR",
            instructions=(
                "One explicitly bound ARMI environment. Tools are grouped by interaction, admin and setup. "
                "Local owner administration needs no separate application approval. "
                "Respect versions and idempotency; reconcile unknown outcomes instead of replaying. "
                "An accepted request is not a completed effect."
            ),
        )
        self.admin = admin
        self.setup = setup
        self.client_path = client_path
        self._client_signature: str | None = None
        self._client: InteractionClient | None = None
        self.interaction = InteractionTools(self.interaction_client)

    def interaction_client(self) -> InteractionClient:
        if self.client_path is None:
            raise ValueError("INTERACTION-NOT-AUTHORIZED")
        binding = load_client_binding(self.client_path)
        if self.admin is not None and self.admin.environment() != (
            str(binding.environment_id),
            binding.environment_root,
        ):
            raise ValueError("INTERACTION-ENVIRONMENT-MISMATCH")
        signature = binding.model_dump_json()
        if self._client is None or signature != self._client_signature:
            self._client = InteractionClient(binding)
            self._client_signature = signature
        return self._client

    async def list_tools(self) -> list[Tool]:
        result: list[Tool] = []
        if self.client_path is not None:
            scopes = {"interaction.read", "interaction.write"}
            if self.setup is None:
                scopes = set(load_client_binding(self.client_path).scopes)
            for tool in await self.interaction.list_tools():
                read_only = tool.name in {"capabilities", "operation_wait"} or (
                    tool.annotations is not None and tool.annotations.read_only_hint
                )
                if ("interaction.read" if read_only else "interaction.write") in scopes:
                    result.append(
                        tool.model_copy(update={"name": "interaction_" + tool.name})
                    )
        if self.admin is not None:
            permitted = (
                None
                if self.setup is not None
                else await asyncio.to_thread(self.admin.permitted_operations)
            )
            for operation in ADMIN_OPERATIONS:
                if (
                    permitted is not None
                    and operation.name not in permitted
                    and not any(
                        item.startswith(operation.name + ".") for item in permitted
                    )
                ):
                    continue
                schema = operation.request.model_json_schema()
                schema["properties"] = {
                    key: value
                    for key, value in schema["properties"].items()
                    if key not in operation.bound_fields
                }
                schema["required"] = [
                    key
                    for key in schema.get("required", [])
                    if key not in operation.bound_fields
                ]
                result.append(
                    Tool(
                        name="admin_" + operation.name,
                        description=operation.description,
                        input_schema=schema,
                        output_schema=operation.result.model_json_schema(),
                        annotations=ToolAnnotations(
                            read_only_hint=operation.read_only,
                            destructive_hint=operation.destructive,
                            idempotent_hint=True,
                            open_world_hint=False,
                        ),
                    )
                )
        if self.setup is not None:
            schema = SetupRequest.model_json_schema()
            for action, fields in _SETUP_FIELDS.items():
                result.append(
                    Tool(
                        name="setup_" + action,
                        description="管理所属本机安装环境: " + action,
                        input_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                key: schema["properties"][key] for key in fields
                            },
                            "required": []
                            if action in _OPTIONAL_SETUP
                            else list(fields),
                            "$defs": schema.get("$defs", {}),
                        },
                        annotations=ToolAnnotations(
                            read_only_hint=action in {"status", "check"},
                            destructive_hint=action == "uninstall",
                            open_world_hint=action
                            in {"credential", "napcat", "update"},
                        ),
                    )
                )
        return result

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult:
        del context
        try:
            tool = next(
                (item for item in await self.list_tools() if item.name == name), None
            )
            if tool is None:
                return _result(
                    {"status": "rejected", "error_code": "MCP-TOOL-NOT-AUTHORIZED"}
                )
            if not Draft202012Validator(tool.input_schema).is_valid(arguments):  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                return _result(
                    {"status": "rejected", "error_code": "MCP-INPUT-INVALID"}
                )
            if name.startswith("interaction_"):
                return await self.interaction.call_tool(
                    name.removeprefix("interaction_"), arguments
                )
            if name.startswith("admin_") and self.admin is not None:
                return _result(
                    await asyncio.to_thread(
                        self.admin.invoke, name.removeprefix("admin_"), arguments
                    )
                )
            if name.startswith("setup_") and self.setup is not None:
                request = SetupRequest.model_validate_json(
                    json.dumps({**arguments, "action": name.removeprefix("setup_")})
                )
                return _result(await asyncio.to_thread(dispatch, self.setup, request))
            return _result(
                {"status": "rejected", "error_code": "MCP-TOOL-NOT-AUTHORIZED"}
            )
        except ValidationError:
            return _result({"status": "rejected", "error_code": "MCP-INPUT-INVALID"})
        except ValueError as error:
            code = str(error)
            return _result(
                {
                    "status": "rejected",
                    "error_code": code
                    if re.fullmatch(r"[A-Z][A-Z0-9-]{1,95}", code)
                    else "MCP-BINDING-INVALID",
                }
            )
        except OSError:
            return _result(
                {"status": "failed", "error_code": "MCP-ENVIRONMENT-UNAVAILABLE"}
            )
        except (
            AdminConfigError,
            AdminSecretError,
            SetupError,
        ):
            return _result(
                {"status": "failed", "error_code": "MCP-BINDING-UNAVAILABLE"}
            )

    def close(self) -> None:
        if self.setup is not None:
            self.setup.close()
        if self.admin is not None:
            self.admin.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ARMI mcp", description="统一的本地 ARMI MCP。默认使用本机拥有者绑定。"
    )
    parser.add_argument("--config", type=Path, help="显式受限 MCP 绑定")
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--installation-root", type=Path)
    args = parser.parse_args(argv)
    server: ARMIMCPServer | None = None
    try:
        if args.config is not None:
            if args.environment_root is not None or args.installation_root is not None:
                raise ValueError("MCP-BINDING-ARGUMENTS")
            binding = MCPBinding.model_validate(read_binding(args.config))
            paths = [
                Path(value)
                for value in (binding.admin_config, binding.interaction_config)
                if value is not None
            ]
            if not paths or any(not path.is_absolute() for path in paths):
                raise ValueError("MCP-BINDING-PATH")
            admin = (
                AdminSession(Path(binding.admin_config))
                if binding.admin_config
                else None
            )
            client_path = (
                Path(binding.interaction_config) if binding.interaction_config else None
            )
            if admin is not None:
                admin.permitted_operations()
            server = ARMIMCPServer(admin=admin, client_path=client_path)
            if client_path is not None:
                server.interaction_client()
        else:
            installation = args.installation_root or Path(
                os.environ["ARMI_INSTALLATION_ROOT"]
            )
            if args.environment_root is None and package_identity() is None:
                raise ValueError("MCP-ENVIRONMENT-ROOT-REQUIRED")
            root = (
                args.environment_root
                or program_installation_root(installation) / "environments/active"
            )
            admin = AdminSession(root / "admin.yaml", local_owner=True)
            setup = bootstrap_setup(
                SetupPaths(environment_root=root, installation_root=installation),
                admin_session=admin,
            )
            server = ARMIMCPServer(
                admin=admin, client_path=root / "client.yaml", setup=setup
            )
        server.run("stdio")
    except (
        ValueError,
        OSError,
        KeyError,
        AdminConfigError,
        AdminSecretError,
        SetupError,
    ):
        print("MCP-STARTUP-BINDING-INVALID", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    finally:
        if server is not None:
            server.close()


__all__ = ("ARMIMCPServer", "MCPBinding", "main")
