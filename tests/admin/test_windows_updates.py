import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from armi_admin.application import updates
from armi_admin.application.distribution import BundleDatabase
from armi_local_control.windows_package import WindowsPackageError


@pytest.fixture
def updater(tmp_path, monkeypatch):
    program = tmp_path / "program"
    (program / "resources").mkdir(parents=True)
    (program / "resources/windows-release.yaml").write_text(
        "repository: YifeiLi99/ARMI\n", encoding="utf-8"
    )
    root = tmp_path / "data"
    database = BundleDatabase(
        postgresql="18.4",
        vector="0.8.6",
        pg_trgm="1.6",
        baseline="0000",
        schema_digest="schema",
        role_policy_digest="roles",
    )
    identity = SimpleNamespace(
        name="YifeiLi99.ARMI.Acceptance",
        publisher="CN=Acceptance",
        program_root=program,
    )
    actual = {"version": "1.0.0.0", "deployment_in_progress": False}
    payload = b"signed-package-test-boundary"
    candidate = {
        "schema_version": "armi.update.v1",
        "name": identity.name,
        "publisher": identity.publisher,
        "version": "1.0.0.1",
        "architecture": "x64",
        "url": "https://github.com/YifeiLi99/ARMI/releases/download/v1/app.msix",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "database": database.model_dump(),
    }
    monkeypatch.setattr(updates, "package_identity", lambda: identity)
    monkeypatch.setattr(updates, "data_root", lambda: root)
    monkeypatch.setattr(updates, "deployment_status", lambda: actual.copy())
    monkeypatch.setattr(
        updates.ProgramBundle, "read", lambda _: SimpleNamespace(database=database)
    )
    monkeypatch.setattr(
        updates, "private_directory", lambda p: p.mkdir(parents=True, exist_ok=True)
    )
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(
            200,
            content=json.dumps(candidate).encode()
            if request.url.path.endswith(".json")
            else payload,
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        updates.httpx,
        "Client",
        lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw),
    )
    inspect = Mock(
        side_effect=lambda _: {
            "version": candidate["version"],
            "database": candidate["database"],
        }
    )
    defer = Mock(return_value={"status": "registration_deferred"})
    restart = Mock(return_value={"status": "deployment_requested"})
    stop = Mock()
    monkeypatch.setattr(updates, "inspect_candidate", inspect)
    monkeypatch.setattr(updates, "defer_update", defer)
    monkeypatch.setattr(updates, "restart_update", restart)
    return SimpleNamespace(
        app=updates.UpdateApplication(stop),
        root=root,
        actual=actual,
        candidate=candidate,
        requested=requested,
        inspect=inspect,
        defer=defer,
        restart=restart,
        stop=stop,
    )


def test_update_defers_once_and_confirms_only_observed_version(updater):
    u = updater
    assert u.app.execute("status")["status"] == "idle"
    assert u.requested == []
    assert u.app.execute("check")["status"] == "available"
    prepared = u.app.execute("prepare")
    assert prepared["status"] == "registration_deferred"
    assert prepared["deployment_verified"] is False
    u.app.execute("prepare")
    assert u.defer.call_count == 1
    count = len(u.requested)
    u.app.execute("check")
    assert len(u.requested) == count
    assert (u.root / "tmp/update/1.0.0.1.msix").exists()
    u.actual["version"] = "1.0.0.1"
    assert u.app.execute("status")["deployment_verified"] is True
    assert not (u.root / "tmp/update/1.0.0.1.msix").exists()


@pytest.mark.parametrize(
    "fault", ["publisher", "schema", "older", "digest", "signature"]
)
def test_update_rejects_incompatible_or_untrusted_candidates(updater, fault):
    u = updater
    if fault == "publisher":
        u.candidate["publisher"] = "CN=Other"
    elif fault == "schema":
        u.candidate["database"]["schema_digest"] = "incompatible"
    elif fault == "older":
        u.candidate["version"] = "0.9.0.0"
    elif fault == "digest":
        u.candidate["sha256"] = "0" * 64
    else:
        u.inspect.side_effect = WindowsPackageError("MSIX-WINDOWS-800B0109")
    u.app.execute("check")
    result = u.app.execute("prepare")
    assert not result["deployment_verified"]
    u.defer.assert_not_called()
    u.restart.assert_not_called()
    u.stop.assert_not_called()


def test_uncertain_deployment_is_not_replayed(updater):
    u = updater
    u.app.execute("check")
    u.defer.side_effect = WindowsPackageError("MSIX-WINDOWS-80004005")
    assert u.app.execute("prepare")["status"] == "deployment_requested"
    assert u.app.execute("prepare")["error_code"] == "UPDATE-DEPLOYMENT-OUTCOME-UNKNOWN"
    assert u.defer.call_count == 1


def test_restart_update_never_deploys_when_admin_stop_fails(updater):
    u = updater
    u.app.execute("check")
    u.app.execute("prepare")
    u.stop.side_effect = RuntimeError("private diagnostic")
    result = u.app.execute("apply")
    assert result["error_code"] == "UPDATE-OPERATION-FAILED"
    assert "private diagnostic" not in str(result)
    u.restart.assert_not_called()


def test_automatic_setting_survives_new_service_instance_without_network(updater):
    u = updater
    assert u.app.execute("automatic", False)["automatic"] is False
    assert updates.UpdateApplication(u.stop).execute("status")["automatic"] is False
    assert u.requested == []


def test_offline_check_preserves_installed_version(updater, monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(updates.httpx, "Client", offline)
    result = updater.app.execute("check")
    assert result["error_code"] == "UPDATE-NETWORK-FAILED"
    assert result["installed_version"] == "1.0.0.0"
    assert not result["deployment_verified"]
    updater.defer.assert_not_called()


def test_composed_update_stops_each_registered_environment_through_admin(
    tmp_path, monkeypatch
):
    from armi_admin import composition
    from armi_admin.application import deployment
    from armi_admin.application.installation import SetupPaths

    paths = SetupPaths(
        installation_root=tmp_path,
        environment_root=tmp_path / "environments/active",
    )
    environments = [paths.environment_root, tmp_path / "environments/acceptance"]
    monkeypatch.setattr(deployment, "installed_root", lambda _: tmp_path)
    monkeypatch.setattr(deployment, "registered_environments", lambda _: environments)
    factory = Mock(return_value=Mock())
    monkeypatch.setattr(updates, "UpdateApplication", factory)
    composition.bootstrap_setup(paths)
    stop_environments = factory.call_args.args[0]
    service = Mock()
    service.invoke.return_value = {"status": "succeeded"}
    bootstrap = Mock(return_value=service)
    monkeypatch.setattr(composition, "bootstrap_setup", bootstrap)
    stop_environments()
    assert [
        call.args[0].environment_root for call in bootstrap.call_args_list
    ] == environments
    assert all(
        call.args[0] == "environment_stop" for call in service.invoke.call_args_list
    )
    assert (
        len({call.args[1]["idempotency_key"] for call in service.invoke.call_args_list})
        == 2
    )
