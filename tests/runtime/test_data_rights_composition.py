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
from armi_runtime.composition.data_rights_contracts import DATA_RIGHTS_OWNER_CONTRACTS
from armi_runtime.composition.database import compose_mind_module as bootstrap_mind
from armi_runtime.composition.owner_roster import (
    RuntimeOwnerRoster,
    compose_runtime_owner_roster,
)
from armi_subject_state.api import SubjectStateReadPort


def _roster(data_rights: DataRightsParticipant) -> RuntimeOwnerRoster:
    return compose_runtime_owner_roster(
        data_rights=data_rights,
        mood_read=cast(MoodReadPort, object()),
        prompt_read=cast(PromptReadPort, object()),
        subject_state_read=cast(SubjectStateReadPort, object()),
        mind_read=bootstrap_mind().read,
    )


class DataRightsCompositionTests(unittest.TestCase):
    def test_owner_projections_reuse_constructed_participants(self) -> None:
        data_rights = EmptyDataRightsParticipant("data-rights")
        roster = _roster(data_rights)
        owners = {item.owner: item for item in roster.owners}
        self.assertEqual(len(owners), len(roster.owners))
        self.assertIs(owners["data-rights"].data_rights, data_rights)
        for first, second in zip(roster.data_rights, roster.data_rights, strict=True):
            self.assertIs(first, second)
            self.assertIs(first, owners[first.owner_identity.value].data_rights)
        self.assertEqual(len(roster.recovery), len(owners))
        for expected, first, second in zip(
            roster.expected_recovery_owners,
            roster.recovery,
            roster.recovery,
            strict=True,
        ):
            self.assertEqual(first.owner_identity, expected)
            self.assertIs(first, second)
            self.assertIs(first, owners[expected.value].recovery)

    def test_fixed_roster_contains_twenty_three_business_and_two_technical_owners(
        self,
    ) -> None:
        participants = compose_data_rights_participants(
            business=_roster(EmptyDataRightsParticipant("data-rights")).data_rights,
            catalog=cast(ArtifactCatalogPort, object()),
        )

        self.assertEqual(len(participants), 25)
        self.assertEqual(
            {item.owner_identity.value for item in participants},
            {item.owner_identity.value for item in DATA_RIGHTS_OWNER_CONTRACTS},
        )
        self.assertEqual(
            tuple(item.owner_identity.value for item in participants),
            (
                "interaction",
                "perception",
                "live-voice",
                "live-vision",
                "evidence",
                "opportunity",
                "experience",
                "cognition",
                "memory",
                "relationship",
                "activity",
                "material",
                "subject-state",
                "mind",
                "mood",
                "prompt",
                "sleep",
                "expression",
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
                business=_roster(EmptyDataRightsParticipant("wrong-owner")).data_rights,
                catalog=cast(ArtifactCatalogPort, object()),
            )
        self.assertEqual(raised.exception.code, "DATA-RIGHTS-PARTICIPANT-ROSTER")


if __name__ == "__main__":
    unittest.main()
