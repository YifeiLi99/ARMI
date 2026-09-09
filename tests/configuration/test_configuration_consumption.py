import hashlib
import json
from pathlib import Path
from typing import cast

from armi_kernel import (
    load_yaml_file,
    observe_configuration_reads,
    read_configuration_bytes,
)
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.configuration_consumption import ConfigurationConsumption


def test_runtime_records_exact_consumed_bytes_and_detects_mixed_versions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configs/model-bindings.yaml"
    path.parent.mkdir()
    path.write_bytes(runtime_config_path("model-bindings.yaml").read_bytes())
    consumed = ConfigurationConsumption(tmp_path)
    before = path.read_bytes()
    with observe_configuration_reads(consumed.record):
        value = load_yaml_file(path)
        loaded = consumed.snapshot()["model-bindings"]
        assert loaded["versions"] == ["sha256:" + hashlib.sha256(before).hexdigest()]
        cast(dict[str, object], value["voice_binding"])["timeout_seconds"] = 25
        path.write_text(json.dumps(value), encoding="utf-8")
        # A saved edit alone does not change what the consumer reports.
        assert consumed.snapshot()["model-bindings"] == loaded
        load_yaml_file(path)
    assert consumed.snapshot()["model-bindings"]["state"] == "mixed_versions"
    assert consumed.snapshot()["qq"]["state"] == "not_loaded"


def test_web_manifest_byte_consumer_is_recorded_without_secret_content(
    tmp_path: Path,
) -> None:
    consumed = ConfigurationConsumption(tmp_path)
    path = runtime_config_path("web-search.yaml", environment_root=tmp_path)
    with observe_configuration_reads(consumed.record):
        raw = read_configuration_bytes(path)
    snapshot = consumed.snapshot()["web-search"]
    assert snapshot["state"] == "loaded"
    assert snapshot["versions"] == ["sha256:" + hashlib.sha256(raw).hexdigest()]
    assert "values" not in snapshot
