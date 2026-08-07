from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_other_human_record_projection_is_not_a_context_dependency() -> None:
    context_sources = (
        ROOT / "apps/armi-runtime/src/armi_runtime/composition/context_compiler.py",
        ROOT / "apps/armi-runtime/src/armi_runtime/composition/context_pipeline.py",
    )
    for source in context_sources:
        value = source.read_text(encoding="utf-8")
        assert "other_human_records" not in value
        assert "OtherHumanRecordQueryPort" not in value
