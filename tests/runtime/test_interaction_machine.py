"""Behavioral checks for the independently authenticated machine transport."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Never
from uuid import uuid7

import httpx
import pytest
from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputCommand,
    CreatorInteractionId,
    OpportunityId,
)
from armi_kernel.contracts import Digest
from armi_local_control.binding import InteractionClientBinding
from armi_runtime import cli
from armi_runtime.application.creator_contract import Readiness
from armi_runtime.application.interaction_catalog import interaction_routes
from armi_runtime.interaction_client import InteractionClient
from armi_runtime.interfaces.browser_sessions import BrowserSessionStore
from armi_runtime.interfaces.creator_app import create_runtime_app
from armi_runtime.interfaces.static_assets import StaticAssetStore
from armi_runtime.mcp import InteractionMCPServer


async def unused() -> None:
    pass


@pytest.mark.parametrize(
    "stage",
    [
        "no_action",
        "no_change",
        "declined",
        "need_information",
        "failed",
        "unknown",
        "partial",
        "applied",
        "completed",
    ],
)
@pytest.mark.asyncio
async def test_wait_returns_decisions_without_requiring_reply_text(
    tmp_path: Path, stage: str
) -> None:
    _, binding, _ = machine(tmp_path)
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "environment_id": str(binding.environment_id),
                "status": "returned",
                "result": {"status": "accepted", "details": {"stage": stage}},
            },
        )

    client = InteractionClient(binding, transport=httpx.MockTransport(respond))
    result = await client.wait(str(uuid7()), timeout_seconds=1)
    assert result["wait_status"] == "returned"
    assert len(calls) == 1
    assert calls[0]["operation"] == "operation_get"
    assert result["result"]["details"]["stage"] == stage


def unused_provider() -> Never:
    raise AssertionError("This test must not invoke a runtime or channel provider")


def machine(
    tmp_path: Path,
    creator_input=None,
    *,
    writable: bool = False,
    effect_ledger=None,
    browser: bool = False,
):
    environment_id, creator_id, delegate_id = uuid7(), uuid7(), uuid7()
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    secret = secrets / "delegate.key"
    secret.write_text("test-machine-secret-that-is-only-a-fixture", encoding="utf-8")
    delegate = {
        "delegate_id": str(delegate_id),
        "creator_party_id": str(creator_id),
        "credential_locator": "file:" + str(secret),
        "scopes": ["interaction.read"],
    }
    if writable:
        delegate["scopes"].append("interaction.write")
    (tmp_path / "interaction-access.yaml").write_text(
        json.dumps(
            {
                "schema_version": "armi.interaction-access.v1",
                "environment_id": str(environment_id),
                "delegates": [delegate],
            }
        ),
        encoding="utf-8",
    )
    binding = InteractionClientBinding.model_validate(
        {
            **delegate,
            "schema_version": "armi.interaction-client.v1",
            "environment_id": str(environment_id),
            "environment_root": str(tmp_path),
            "endpoint": "http://127.0.0.1:6198",
        }
    )
    app = create_runtime_app(
        readiness=lambda: Readiness.READY,
        runtime_status=unused_provider,
        qq_channel_health=unused_provider,
        assets=StaticAssetStore({}),
        browser_sessions=BrowserSessionStore(
            environment_id=environment_id,
            creator_party_id=creator_id,
            session_ttl_seconds=28800,
        )
        if browser
        else None,
        expected_authority="127.0.0.1:6198",
        request_body_max_bytes=262144,
        on_started=unused,
        on_stopping=unused,
        machine_environment_root=tmp_path,
        machine_environment_id=environment_id,
        machine_creator_party_id=creator_id,
        creator_input=creator_input,
        effect_ledger=effect_ledger,
    )
    return app, binding, secret


@pytest.mark.asyncio
async def test_vision_observation_arguments_reach_shared_application(
    tmp_path: Path, monkeypatch
) -> None:
    app, binding, _ = machine(tmp_path, writable=True)
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    result = await InteractionMCPServer(client).call_tool(
        "vision_observe",
        {"source_kind": "camera", "idempotency_key": "vision-contract"},
    )
    assert result.structured_content is not None
    assert (
        result.structured_content["result"]["error"]["code"]
        == "DEPENDENCY_LIVE_VISION_UNAVAILABLE"
    )
    config = tmp_path / "client.yaml"
    config.write_text(binding.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "InteractionClient", lambda _binding: client)
    arguments = cli.parser().parse_args(
        [
            "--config",
            str(config),
            "vision",
            "observe",
            "--source-kind",
            "camera",
            "--idempotency-key",
            "vision-contract",
        ]
    )
    called = await cli._execute(arguments)
    assert called["result"]["error"]["code"] == "DEPENDENCY_LIVE_VISION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_artifact_chunks_and_cli_output_preserve_governed_content(
    tmp_path: Path, monkeypatch
) -> None:
    from armi_effect.api import EffectArtifactContent, EffectArtifactKind

    content = b"patch\n" * 699050 + b"end\n"
    assert len(content) == 4 * 1024 * 1024
    callers = []
    artifact = EffectArtifactContent(
        EffectArtifactKind.PATCH, "text/plain", content, Digest.from_bytes(content)
    )
    original_sha256 = hashlib.sha256

    def reject_full_rehash(value=b"", **kwargs):
        assert value != content, "transport must reuse the owner-provided digest"
        return original_sha256(value, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", reject_full_rehash)

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            callers.append(creator_party_id)
            return artifact

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger())
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    arguments = {"effect_id": str(uuid7()), "artifact_kind": "patch"}
    first = await InteractionMCPServer(client).call_tool("artifact_read", arguments)
    assert first.structured_content is not None
    assert first.structured_content["result"]["byte_count"] == 65536
    assert first.structured_content["result"]["next_offset"] == 65536
    assert (
        base64.b64decode(first.structured_content["artifact"]["content"])
        == content[:65536]
    )
    config = tmp_path / "client.yaml"
    config.write_text(binding.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "InteractionClient", lambda _binding: client)
    output = tmp_path / "artifact.patch"
    args = cli.parser().parse_args(
        [
            "--config",
            str(config),
            "artifact",
            "read",
            "--effect-id",
            arguments["effect_id"],
            "--artifact-kind",
            "patch",
            "--output",
            str(output),
        ]
    )
    result = await cli._execute(args)
    assert result["artifact"]["size_bytes"] == len(content)
    assert output.read_bytes() == content
    assert set(callers) == {binding.creator_party_id}
    with pytest.raises(FileExistsError):
        await cli._execute(args)
    assert output.read_bytes() == content
    assert not tuple(tmp_path.glob("*.part"))


@pytest.mark.asyncio
async def test_artifact_download_rejects_changed_content_without_publishing(
    tmp_path: Path,
) -> None:
    from armi_effect.api import EffectArtifactContent, EffectArtifactKind

    calls = 0

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            nonlocal calls
            calls += 1
            content = (b"a" if calls == 1 else b"b") * 100000
            return EffectArtifactContent(
                EffectArtifactKind.PATCH,
                "text/plain",
                content,
                Digest.from_bytes(content),
            )

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger())
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    output = tmp_path / "artifact.patch"
    with pytest.raises(ValueError, match="ARTIFACT-CHANGED"):
        await client.download_artifact(
            {"effect_id": str(uuid7()), "artifact_kind": "patch"}, output
        )
    assert not output.exists()
    assert not tuple(tmp_path.glob("*.part"))


@pytest.mark.asyncio
async def test_web_and_machine_return_the_same_projected_final_result(tmp_path):
    from armi_effect.api import EffectArtifactContent, EffectArtifactKind

    content = "实际交付正文\n".encode()
    digest = Digest.from_bytes(content)
    callers = []

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            callers.append(creator_party_id)
            return EffectArtifactContent(kind, "text/plain", content, digest)

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger(), browser=True)
    transport = httpx.ASGITransport(app=app)
    client = InteractionClient(binding, transport=transport)
    args = {
        "effect_id": str(uuid7()),
        "artifact_kind": EffectArtifactKind.FINAL_RESULT.value,
    }
    result = await InteractionMCPServer(client).call_tool("artifact_read", args)
    wire = result.structured_content
    assert wire is not None
    assert base64.b64decode(wire["artifact"]["content"]) == content
    assert wire["result"]["digest"] == digest.value
    headers = {
        "Origin": "http://127.0.0.1:6198",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:6198"
    ) as http:
        session = await http.post("/v1/browser-sessions", headers=headers, content=b"")
        assert session.status_code == 200
        headers["Authorization"] = "Bearer " + session.json()["browser_session_token"]
        response = await http.get(
            f"/v1/effects/{args['effect_id']}/artifacts/final_result", headers=headers
        )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("text/plain")
    assert set(callers) == {binding.creator_party_id}


@pytest.mark.asyncio
async def test_download_rejects_wrong_final_digest_without_publishing(tmp_path):
    from armi_effect.api import EffectArtifactContent

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            return EffectArtifactContent(
                kind, "text/plain", b"delivered", Digest.from_bytes(b"wrong")
            )

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger())
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    output = tmp_path / "artifact.patch"
    with pytest.raises(ValueError, match="ARTIFACT-INTEGRITY"):
        await client.download_artifact(
            {"effect_id": str(uuid7()), "artifact_kind": "patch"}, output
        )
    assert not output.exists()
    assert not tuple(tmp_path.glob("*.part"))


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,length", [(0, 1), (3, 1), (4, 2), (6, 1)])
async def test_artifact_window_preserves_byte_boundaries(tmp_path, offset, length):
    from armi_effect.api import EffectArtifactContent

    content = "你好".encode()

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            return EffectArtifactContent(
                kind, "text/plain", content, Digest.from_bytes(content)
            )

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger())
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    result = await client.invoke(
        "artifact_read",
        {
            "effect_id": str(uuid7()),
            "artifact_kind": "patch",
            "offset": offset,
            "length": length,
        },
    )
    assert (
        base64.b64decode(result["artifact"]["content"])
        == content[offset : offset + length]
    )
    assert result["result"]["next_offset"] == (
        None if offset + length >= len(content) else offset + length
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset,length,local_error",
    [(7, 1, False), (-1, 1, True), (0, 0, True), (0, 1048577, True)],
)
async def test_invalid_artifact_window_is_rejected(
    tmp_path, offset, length, local_error
):
    from armi_effect.api import EffectArtifactContent

    content = b"abcdef"

    class Ledger:
        async def read_artifact(self, effect_id, *, creator_party_id, kind):
            return EffectArtifactContent(
                kind, "text/plain", content, Digest.from_bytes(content)
            )

    app, binding, _ = machine(tmp_path, effect_ledger=Ledger())
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    arguments = {
        "effect_id": str(uuid7()),
        "artifact_kind": "patch",
        "offset": offset,
        "length": length,
    }
    if local_error:
        with pytest.raises(ValueError, match="INTERACTION-ARGUMENTS"):
            await client.invoke("artifact_read", arguments)
        return
    result = await client.invoke("artifact_read", arguments)
    assert result["transport_status"] >= 400


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["argument", "stdin"])
async def test_cli_and_mcp_send_same_bound_creator_command(
    tmp_path: Path, monkeypatch, source: str
) -> None:
    commands = []
    acceptance = CreatorInputAcceptance(
        CreatorInteractionId(uuid7()),
        EvidenceId(uuid7()),
        OpportunityId(uuid7()),
        Digest.from_bytes(b"request"),
        Digest.from_bytes(b"text"),
        True,
    )

    class Intake:
        async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
            commands.append(command)
            return acceptance

    app, binding, _ = machine(tmp_path, Intake(), writable=True)
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    config = tmp_path / "client.yaml"
    config.write_text(binding.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "InteractionClient", lambda _binding: client)
    monkeypatch.setattr("sys.stdin", io.StringIO("代表 Creator 输入"))
    args = cli.parser().parse_args(
        [
            "--config",
            str(config),
            "message",
            "send",
            "--scene-key",
            "default",
            "--message" if source == "argument" else "--message-file",
            "代表 Creator 输入" if source == "argument" else "-",
            "--idempotency-key",
            "same-key",
        ]
    )
    direct = await cli._execute(args)
    mcp = await InteractionMCPServer(client).call_tool(
        "message_send",
        {
            "scene_key": "default",
            "message": "代表 Creator 输入",
            "idempotency_key": "same-key",
        },
    )
    assert direct["transport_status"] == 202
    assert mcp.structured_content is not None
    # Each transport attempt has its own trace/time; the accepted logical result is identical.
    assert {
        key: value
        for key, value in mcp.structured_content["result"].items()
        if key not in {"trace_id", "occurred_at"}
    } == {
        key: value
        for key, value in direct["result"].items()
        if key not in {"trace_id", "occurred_at"}
    }
    assert len(commands) == 2
    assert all(command.delegate_id == binding.delegate_id for command in commands)
    assert commands[0].idempotency_key == commands[1].idempotency_key


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection", "invalid_response"])
async def test_cli_and_mcp_return_identical_transport_failures(
    tmp_path: Path, monkeypatch, capsys, failure: str
) -> None:
    _, binding, _ = machine(tmp_path)
    config = tmp_path / "client.yaml"
    config.write_text(binding.model_dump_json(), encoding="utf-8")

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "connection":
            raise httpx.ConnectError("fixture transport unavailable", request=request)
        return httpx.Response(200, content=b"not a JSON response")

    client = InteractionClient(binding, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(cli, "InteractionClient", lambda _binding: client)
    exit_code = await asyncio.to_thread(
        cli.main, ["--config", str(config), "health", "live"]
    )
    result = json.loads(capsys.readouterr().out)
    called = await InteractionMCPServer(client).call_tool("health_live", {})
    assert exit_code != 0 and called.is_error
    assert called.structured_content == result
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_machine_health_and_mcp_share_client_without_browser_session(
    tmp_path: Path,
) -> None:
    app, binding, _ = machine(tmp_path)
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    result = await client.invoke("health_live", {})
    assert result["result"] == {"status": "alive"}
    server = InteractionMCPServer(client)
    called = await server.call_tool("health_live", {})
    assert called.structured_content["result"] == result["result"]
    assert not called.is_error
    names = {tool.name for tool in await server.list_tools()}
    assert {route.operation.name for route in interaction_routes()} <= names


@pytest.mark.asyncio
async def test_machine_scope_rejects_mutation_before_owner(tmp_path: Path) -> None:
    app, binding, _ = machine(tmp_path)
    client = InteractionClient(binding, transport=httpx.ASGITransport(app=app))
    result = await client.invoke("scene_create", {"scene_key": "example"})
    assert result["transport_status"] == 403
    assert result["result"]["error_code"] == "INTERACTION-SCOPE-REQUIRED"


@pytest.mark.asyncio
async def test_machine_does_not_accept_browser_or_body_identity(tmp_path: Path) -> None:
    app, binding, secret = machine(tmp_path)
    headers = {
        "authorization": "Bearer "
        + base64.b64encode(secret.read_bytes()).decode("ascii"),
        "x-armi-delegate": str(binding.delegate_id),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=binding.endpoint
    ) as client:
        response = await client.post(
            "/machine/v1/invoke",
            headers={**headers, "origin": binding.endpoint},
            json={"operation": "health_live", "arguments": {}},
        )
        assert response.status_code == 403
        response = await client.post(
            "/machine/v1/invoke",
            headers=headers,
            json={
                "operation": "health_live",
                "arguments": {},
                "creator_party_id": str(binding.creator_party_id),
            },
        )
        assert response.status_code == 400
        response = await client.post(
            "/v1/scenes",
            headers=headers,
            json={"contract_version": "1.0", "scene_key": "example"},
        )
        assert response.status_code != 201
