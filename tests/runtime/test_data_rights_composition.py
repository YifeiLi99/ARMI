from __future__ import annotations

import unittest
from typing import cast

from armi_artifact_store.api import ArtifactCatalogPort
from armi_data_rights.api import (
    DataRightsParticipant,
    DataRightsParticipantViolation,
    EmptyDataRightsParticipant,
)
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_runtime.composition.data_rights import compose_data_rights_participants
from armi_runtime.composition.owner_roster import compose_runtime_owner_roster
from armi_subject_state.api import SubjectStateReadPort


def _business(data_rights: DataRightsParticipant) -> tuple[DataRightsParticipant, ...]:
    return compose_runtime_owner_roster(
        data_rights=data_rights,
        mood_read=cast(MoodReadPort, object()),
        prompt_read=cast(PromptReadPort, object()),
        subject_state_read=cast(SubjectStateReadPort, object()),
    ).data_rights


class DataRightsCompositionTests(unittest.TestCase):
    def test_fixed_roster_contains_twenty_two_business_and_two_technical_owners(
        self,
    ) -> None:
        participants = compose_data_rights_participants(
            business=_business(EmptyDataRightsParticipant("data-rights")),
            catalog=cast(ArtifactCatalogPort, object()),
        )

        self.assertEqual(len(participants), 24)
        self.assertEqual(
            tuple(item.owner_identity.value for item in participants),
            (
                "interaction",
                "perception",
                "live-voice",
                "evidence",
                "opportunity",
                "experience",
                "cognition",
                "memory",
                "relationship",
                "activity",
                "material",
                "subject-state",
                "mood",
                "prompt",
                "sleep",
                "expression",
                "capability",
                "effect",
                "web-observation",
                "codex",
                "context",
                "data-rights",
                "runtime",
                "artifact-store",
            ),
        )
        self.assertTrue(
            all(isinstance(item, DataRightsParticipant) for item in participants)
        )

    def test_identity_mismatch_is_rejected_before_database_work(self) -> None:
        with self.assertRaises(DataRightsParticipantViolation) as raised:
            compose_data_rights_participants(
                business=_business(EmptyDataRightsParticipant("wrong-owner")),
                catalog=cast(ArtifactCatalogPort, object()),
            )
        self.assertEqual(raised.exception.code, "DATA-RIGHTS-PARTICIPANT-ROSTER")


if __name__ == "__main__":
    unittest.main()
