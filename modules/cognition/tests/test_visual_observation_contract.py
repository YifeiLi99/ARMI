import pytest
from armi_cognition._visual_observation_contract import (
    parse_visual_observation_candidate,
)
from pydantic import ValidationError


def test_visual_candidate_can_only_ignore_or_form_private_experience() -> None:
    ignored = parse_visual_observation_candidate({"kind": "ignore", "appraisal": None})
    assert ignored.kind == "ignore"
    accepted = parse_visual_observation_candidate(
        {
            "kind": "experience",
            "experience": {
                "first_person_gist": "我通过摄像头看到窗边的光线发生了明显变化。",
                "fact_class": "external_claim",
                "uncertainty": "这是视觉模型的解释。",
            },
            "appraisal": None,
        }
    )
    assert accepted.kind == "experience"


@pytest.mark.parametrize("kind", ["reply", "activity", "relationship", "action"])
def test_visual_candidate_rejects_external_or_social_actions(kind: str) -> None:
    with pytest.raises(ValidationError):
        parse_visual_observation_candidate({"kind": kind, "appraisal": None})
