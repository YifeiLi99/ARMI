"""Add the appraisal-only successor for fast live-voice turns."""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None

_PURPOSES = (
    "consider_creator_input",
    "consider_creator_voice_appraisal",
    "consider_web_evidence",
    "consider_codex_task",
    "consider_codex_result",
    "consider_autonomous_life",
    "consider_activity_attention",
    "consider_activity_internal_work",
    "consider_sleep",
    "consider_life_query_result",
    "maintain_subjective_memory",
    "perform_subject_self_check",
    "consider_creator_outreach",
    "consider_other_human_input",
    "consider_visual_observation",
)


def _purpose_check(column: str) -> str:
    values = ",".join(f"'{value}'::text" for value in _PURPOSES)
    return f"{column} = ANY (ARRAY[{values}])"


def upgrade() -> None:
    op.drop_constraint(
        "opportunities_purpose_check", "opportunities", schema="armi", type_="check"
    )
    op.create_check_constraint(
        "opportunities_purpose_check",
        "opportunities",
        _purpose_check("purpose"),
        schema="armi",
    )
    op.drop_constraint(
        "cognitive_episodes_purpose_check",
        "cognitive_episodes",
        schema="armi",
        type_="check",
    )
    op.create_check_constraint(
        "cognitive_episodes_purpose_check",
        "cognitive_episodes",
        _purpose_check("purpose"),
        schema="armi",
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
