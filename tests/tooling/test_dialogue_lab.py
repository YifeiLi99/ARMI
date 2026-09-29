import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tools.dialogue_lab import DialogueLab
from tools.dialogue_lab_support import LabError


def lab_at(tmp_path):
    lab = object.__new__(DialogueLab)
    lab.root = tmp_path
    lab.config = Mock(environment_id="test")
    lab.binding = Mock()
    return lab


def test_stopped_status_does_not_query_offline_database(tmp_path):
    lab = lab_at(tmp_path)
    lab.admin = Mock(return_value={"status": "stopped", "pid": None})
    assert lab.status() == {
        "runtime": {"status": "stopped", "pid": None},
        "autonomy": {"status": "unavailable", "reason": "runtime_stopped"},
    }
    lab.admin.assert_called_once_with("runtime_status")


def test_running_status_preserves_autonomy_failure(tmp_path):
    lab = lab_at(tmp_path)
    lab.admin = Mock(
        side_effect=[{"status": "running", "pid": 123}, LabError("observation failed")]
    )
    with pytest.raises(LabError, match="observation failed"):
        lab.status()


def test_running_status_returns_real_autonomy(tmp_path):
    lab = lab_at(tmp_path)
    lab.admin = Mock(side_effect=[{"status": "running"}, {"enabled": True}])
    assert lab.status()["autonomy"] == {"enabled": True}


def test_capture_preserves_all_attempts_unicode_pages_and_appraisal(
    tmp_path, monkeypatch
):
    lab = lab_at(tmp_path)
    calls = []

    def admin(name, args=None):
        calls.append((name, args))
        if name == "trace_flow":
            return {
                "nodes": [{"kind": "episode", "id": "e"}],
                "cursor": None,
                "diagnostics": None,
            }
        if name == "cognition_read":
            assert args is not None
            if "artifact_id" not in args:
                return {
                    "artifacts": [
                        {"artifact_id": "a", "role": "request", "retained": True},
                        {"artifact_id": "b", "role": "response", "retained": True},
                    ],
                    "attempts": [1, 2],
                }
            return {
                "text": {
                    "content": "你好" if args["offset"] == 0 else "世界",
                    "next_offset": 2 if args["offset"] == 0 else None,
                }
            }
        if name == "database_query":
            return {
                "rows": [{"values": {"provider_calls": {"request": "actual Jev wire"}}}]
            }
        return {}

    monkeypatch.setattr(lab, "admin", admin)
    directory = lab.capture(episode_id="e")
    assert (directory / "request-a.txt").read_text(encoding="utf-8") == "你好世界"
    assert (directory / "response-b.txt").read_text(encoding="utf-8") == "你好世界"
    assert json.loads((directory / "episode-e.json").read_bytes())["attempts"] == [1, 2]
    assert "actual Jev wire" in (directory / "appraisal-e.json").read_text()
    assert (
        json.loads((directory / "capture.json").read_bytes())["status"] == "collected"
    )


def test_capture_failure_leaves_partial_evidence(tmp_path, monkeypatch):
    lab = lab_at(tmp_path)
    monkeypatch.setattr(lab, "admin", Mock(side_effect=LabError("unavailable")))
    with pytest.raises(LabError):
        lab.capture(episode_id="e")
    report = next((tmp_path / "captures").glob("*/capture.json"))
    assert json.loads(report.read_bytes())["status"] == "collecting"


@pytest.mark.asyncio
async def test_message_timeout_keeps_resume_reference_and_never_resends(
    tmp_path, monkeypatch
):
    lab = lab_at(tmp_path)
    client = Mock()
    client.invoke = AsyncMock(
        return_value={
            "transport_status": 202,
            "result": {"details": {"opportunity_id": "op", "interaction_id": "input"}},
        }
    )
    client.wait = AsyncMock(
        return_value={"wait_status": "disconnected", "resume_ref": "op"}
    )
    monkeypatch.setattr("tools.dialogue_lab.InteractionClient", lambda binding: client)
    monkeypatch.setattr(lab, "capture", lambda **kwargs: Path("capture"))
    result = await lab.message("hello", 1)
    assert client.invoke.await_count == 1
    assert result["operation"]["resume_ref"] == "op"
    assert (
        json.loads(next((tmp_path / "turns").glob("*/input.json")).read_bytes())[
            "message"
        ]
        == "hello"
    )


def test_source_lab_refuses_active_environment(tmp_path, monkeypatch):
    config = SimpleNamespace(
        expected=Mock(source_root="source"),
        environment_kind=SimpleNamespace(value="active"),
        test_controls_enabled=False,
        environment_root=tmp_path,
    )
    monkeypatch.setattr(
        "tools.dialogue_lab.load_admin_config", lambda _: (config, None)
    )
    with pytest.raises(LabError, match="SOURCE-TEST"):
        DialogueLab(tmp_path)


def test_watch_captures_each_completed_episode_once(tmp_path, monkeypatch):
    lab = lab_at(tmp_path)
    lab.admin = Mock(
        side_effect=[
            {
                "rows": [
                    {"values": {"cognitive_episode_id": "a"}},
                    {"values": {"cognitive_episode_id": "a"}},
                ],
                "next_offset": None,
            },
            {},
        ]
    )
    lab.capture = Mock(return_value=Path("capture"))
    result = lab.watch(0)
    assert result["captures"] == ["capture"]
    lab.capture.assert_called_once_with(episode_id="a")
