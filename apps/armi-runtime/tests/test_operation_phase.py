import pytest
from armi_interaction.api import CreatorOperationPhase
from armi_runtime.application.operation_assembler import _derive_phase


@pytest.mark.parametrize("reconsideration_no", (1, 2, 3))
def test_later_opportunity_stale_conflict_remains_diagnosable(
    reconsideration_no: int,
) -> None:
    assert _derive_phase(
        disposition="resolved",
        reconsideration_no=reconsideration_no,
        episode_status="completed",
        cognition_failure=None,
        application_resolution="stale",
        expression=None,
        effect_status=None,
    ) == (CreatorOperationPhase.STALE_CONFLICT, "CONFLICT_SUBJECT_STATE_STALE")
