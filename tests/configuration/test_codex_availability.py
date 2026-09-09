import json
from pathlib import Path
from uuid import uuid7

import pytest
from armi_codex.api import CodexRunnerViolation
from armi_runtime.composition import runtime_credentials
from armi_runtime.composition.environment import prepare_environment


@pytest.mark.parametrize(
    ("enabled", "credential", "runner_ready", "reason"),
    [
        (False, "absent", True, "CODEX-DISABLED"),
        (True, "absent", True, "CODEX-CREDENTIAL-MISSING"),
        (True, "missing-file", True, "CODEX-CREDENTIAL-UNAVAILABLE"),
        (True, "present", False, "CODEX-UNAVAILABLE"),
        (True, "present", True, None),
    ],
)
def test_codex_reports_actual_local_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    credential: str,
    runner_ready: bool,
    reason: str | None,
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "secrets").mkdir()
    secret = tmp_path / "secrets/auth"
    if credential == "present":
        secret.write_text('{"fixture":"private-value"}', encoding="utf-8")
    document = {
        "environment": {
            "environment_id": str(uuid7()),
            "data_root": str(tmp_path / "data"),
        },
        "creator": {"port": 43123},
        "codex": {"enabled": enabled},
        "secret_locators": {}
        if credential == "absent"
        else {"codex.auth_json": "file:" + secret.as_posix()},
    }
    (tmp_path / "environment.yaml").write_text(json.dumps(document), encoding="utf-8")
    prepared = prepare_environment(
        tmp_path,
        credential_scope=runtime_credentials.runtime_credential_scope(),
        environment={},
    )

    def runner_check() -> None:
        if not runner_ready:
            raise CodexRunnerViolation("CODEX-RUNTIME-UNAVAILABLE")

    monkeypatch.setattr(runtime_credentials, "check_local_runner", runner_check)
    state = runtime_credentials.codex_local_availability(prepared)
    assert state.enabled is enabled
    assert state.available is (reason is None)
    assert state.reason_code == reason
    assert "private-value" not in repr(state)

    document["codex"] = {"enabled": not enabled}
    (tmp_path / "environment.yaml").write_text(json.dumps(document), encoding="utf-8")
    assert runtime_credentials.codex_local_availability(prepared) == state
