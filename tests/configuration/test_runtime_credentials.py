import json
from pathlib import Path
from typing import cast
from uuid import uuid7

from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime_credentials import (
    inspect_runtime_credentials,
    runtime_credential_scope,
)


def test_credential_diagnostics_resolve_only_runtime_grants_without_exposing_values(
    tmp_path: Path,
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "secrets").mkdir()
    secret = tmp_path / "secrets" / "runtime"
    secret.write_text("private-fixture-value", encoding="utf-8")
    (tmp_path / "environment.yaml").write_text(
        json.dumps(
            {
                "environment": {
                    "environment_id": str(uuid7()),
                    "data_root": str(tmp_path / "data"),
                },
                "creator": {"port": 43123},
                "secret_locators": {"database.runtime": "file:" + secret.as_posix()},
            }
        ),
        encoding="utf-8",
    )
    prepared = prepare_environment(
        tmp_path, credential_scope=runtime_credential_scope(), environment={}
    )
    result = inspect_runtime_credentials(prepared)
    checks = {item["purpose"]: item for item in cast(list[dict[str, object]], result["checks"])}
    assert checks["database.runtime"]["status"] == "resolvable"
    assert checks["model.request"]["status"] == "missing"
    assert "admin.authorization.sign" not in checks
    assert result["external_effects_dispatched"] is False
    assert "private-fixture-value" not in json.dumps(result)
    restricted = prepare_environment(tmp_path, credential_scope={}, environment={})
    denied = inspect_runtime_credentials(restricted)
    assert (
        next(
            item for item in cast(list[dict[str, object]], denied["checks"]) if item["purpose"] == "database.runtime"
        )["status"]
        == "unavailable"
    )
