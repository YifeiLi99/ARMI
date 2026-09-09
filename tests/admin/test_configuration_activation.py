from armi_admin.application.configuration_activation import (
    asset_activation,
    runtime_activation,
)


def test_stopped_or_unverified_runtime_does_not_recommend_restart() -> None:
    desired = {"desired_digest": "new", "effective_on_next_start": {}}
    for status, expected in (
        ("stopped", "not_running"),
        ("unavailable", "not_verified"),
    ):
        result = runtime_activation({"status": status}, desired)
        assert result["activation"] == expected
        assert result["restart_required"] is False


def test_unrelated_environment_override_does_not_hide_a_saved_change() -> None:
    runtime = {
        "status": "running",
        "runtime": {
            "runtime_configuration_digest": "old",
            "configuration_sources": ["explicit-environment"],
            "configuration_overrides": [
                {
                    "variable": "ARMI_DB_POOL_MIN",
                    "path": ["database", "pool_min"],
                    "value": 2,
                }
            ],
        },
    }
    desired = {
        "desired_digest": "new",
        "effective_on_next_start": {"database": {"pool_min": 2}},
    }
    result = runtime_activation(runtime, desired)
    assert result["activation"] == "restart_required"
    assert result["blocking_overrides"] == []
    desired["effective_on_next_start"]["database"]["pool_min"] = 3
    result = runtime_activation(runtime, desired)
    assert result["activation"] == "environment_override"
    assert result["blocking_overrides"][0]["variable"] == "ARMI_DB_POOL_MIN"
    assert result["restart_required"] is False


def test_partial_adoption_requires_an_actual_matching_consumer() -> None:
    runtime = {
        "status": "running",
        "runtime": {
            "configuration_assets": {
                "model-bindings": {"versions": ["a", "b"], "state": "mixed_versions"}
            }
        },
    }
    assert (
        asset_activation(runtime, "model-bindings", "b")["activation"]
        == "partially_effective"
    )
    assert (
        asset_activation(runtime, "model-bindings", "c")["activation"]
        == "restart_required"
    )
    assert asset_activation(runtime, "qq", "b")["activation"] == "not_verified"
