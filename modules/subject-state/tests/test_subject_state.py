import rfc8785
from armi_kernel.application import CandidateFactClass
from armi_subject_state.api import (
    CandidateSubjectStateDraft,
    SubjectStateKind,
    default_subject_state_cognition,
)


def test_subject_state_owner_draft_round_trip() -> None:
    draft = CandidateSubjectStateDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        SubjectStateKind.MIND,
        1,
        rfc8785.dumps(
            {
                "schema_version": "armi.mind.v2",
                "understanding": [],
                "attention": [],
                "thoughts": [],
                "wishes": [],
                "motivations": [],
            }
        ),
    )
    cognition = default_subject_state_cognition()
    owner = cognition.bind(draft)
    assert owner.owner == "mind"
    assert cognition.decode(owner.canonical_payload) == draft
