from __future__ import annotations

import pytest
from armi_runtime.adapters.artifacts.life_material_codec import (
    build_life_material_artifact,
    parse_life_material_artifact,
)


def test_life_material_artifact_round_trips_canonical_utf8_body() -> None:
    body = "这是 ARMI 自己写下的完整正文。".encode()
    artifact = build_life_material_artifact(body)

    assert parse_life_material_artifact(artifact) == body
    assert artifact.startswith(b'{"body":')


@pytest.mark.parametrize(
    "artifact",
    (
        b'{"schema_version":"armi.life-material-content.v1","body":"x"}',
        b'{"body":"x","schema_version":"armi.life-material-content.v1"}\n',
        b'{"body":"x","extra":true,"schema_version":"armi.life-material-content.v1"}',
        b'{"body":"x","schema_version":"armi.life-material-content.v0"}',
    ),
)
def test_life_material_artifact_rejects_noncanonical_or_corrupt_content(
    artifact: bytes,
) -> None:
    with pytest.raises(ValueError, match="life material artifact is invalid"):
        parse_life_material_artifact(artifact)
