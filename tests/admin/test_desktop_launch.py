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
