from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

from armi_admin.desktop import Desktop


def desktop(state="ready", result=None):
    instance = object.__new__(Desktop)
    instance.application = Mock()
    instance.application.status.return_value = {
        "status": state,
        "creator_url": "http://127.0.0.1:9000/ui/",
    }
    instance.root = Mock()
    instance.busy = False
    instance.hide = Mock()
    instance.admin = Mock(
        side_effect=lambda _operation, _arguments, callback: callback(
            result or {"status": "succeeded"}
        )
    )
    return instance


def test_normal_open_waits_for_success_before_opening_creator():
    instance = desktop()
    with patch("armi_admin.desktop.webbrowser.open") as open_browser:
        instance.start_on_launch(False)
    open_browser.assert_called_once_with("http://127.0.0.1:9000/ui/")
    cast(Mock, instance.hide).assert_called_once()


def test_jev_credential_uses_key_input_and_saves_without_paid_verification():
    instance = desktop()
    for name in (
        "secret",
        "codex_import",
        "credential_name",
        "credential_save_button",
        "credential_verify_button",
        "credential_help",
        "credential_status",
        "credential_actions",
    ):
        setattr(instance, name, Mock())
    cast(
        Mock, instance.credential_name.get
    ).return_value = "Jev API Key（必需的事件与心情评价）"  # noqa: RUF001 -- exact Chinese UI label
    instance.credential = Mock()
    instance._credential_selected()
    cast(Mock, instance.secret.pack).assert_called_once()
    cast(Mock, instance.codex_import.pack).assert_not_called()
    cast(Mock, instance.credential_verify_button.configure).assert_called_once_with(
        state="disabled"
    )
    configuration = cast(
        Mock, instance.credential_save_button.configure
    ).call_args.kwargs
    assert configuration["text"] == "保存 Key"
    configuration["command"]()
    cast(Mock, instance.credential).assert_called_once_with("put")


def test_first_use_and_failed_start_show_settings_without_opening_browser():
    for instance in (desktop("not_configured"), desktop(result={"status": "failed"})):
        with patch("armi_admin.desktop.webbrowser.open") as open_browser:
            instance.start_on_launch(False)
        open_browser.assert_not_called()
        cast(Mock, instance.root.deiconify).assert_called_once()
        cast(Mock, instance.hide).assert_not_called()


def test_login_start_does_not_open_browser():
    instance = desktop()
    with patch("armi_admin.desktop.webbrowser.open") as open_browser:
        instance.start_on_launch(True)
    open_browser.assert_not_called()
    cast(Mock, instance.hide).assert_called_once()


def test_exit_tray_does_not_stop_environment():
    instance = desktop()
    instance._close = Mock()
    instance.action("quit")
    cast(Mock, instance._close).assert_called_once()
    cast(Mock, instance.admin).assert_not_called()


def test_stop_and_exit_waits_for_confirmed_stop(tmp_path):
    for status in ("succeeded", "failed"):
        instance = desktop(result={"status": status})
        instance.environment = Path(tmp_path)
        (tmp_path / "postgresql").mkdir(exist_ok=True)
        (tmp_path / "postgresql/cluster.json").touch()
        instance._close = Mock()
        instance.action("stop_quit")
        assert cast(Mock, instance.admin).call_args.args[0] == "environment_stop"
        assert cast(Mock, instance._close).call_count == int(status == "succeeded")
        assert cast(Mock, instance.root.deiconify).call_count == int(status == "failed")


def test_exit_during_operation_keeps_desktop_alive():
    instance = desktop()
    instance.busy = True
    instance.status = Mock()
    instance._close = Mock()
    instance.action("quit")
    cast(Mock, instance._close).assert_not_called()
    cast(Mock, instance.admin).assert_not_called()


def test_runtime_status_is_not_inferred_from_database_or_old_success():
    instance = desktop()
    instance.runtime_status = Mock()
    instance.tray = Mock()
    for state, expected in (("ready", "运行中"), ("stopped", "已停止")):
        instance._runtime_status_result(
            {
                "status": "succeeded",
                "result": {
                    "runtime": {"status": state},
                    "postgresql": {"status": "ready"},
                },
            }
        )
        instance.tray.set_status.assert_called_with(
            expected, running=state == "ready", error=False
        )
    instance._runtime_status_result({"status": "failed", "error_code": "UNREACHABLE"})
    instance.tray.set_status.assert_called_with(
        "无法确认 / UNREACHABLE", running=False, error=True
    )
