import json
from datetime import UTC, datetime
from uuid import uuid7

from armi_cognition._event_store import evaluation_targets
from armi_mood.api import MoodEvent


def test_activity_revisions_update_one_grounded_object_and_due_focus_precedes_background():
    activity, concern = str(uuid7()), str(uuid7())
    event = MoodEvent(
        "event:1", uuid7(), uuid7(), uuid7(), 1, datetime.now(UTC), "result"
    )

    def context(revision):
        return {
            "layers": [
                {
                    "items": [
                        {
                            "item_kind": "current_activity",
                            "source": {
                                "kind": "activity_revision",
                                "reference": revision,
                            },
                            "content": json.dumps({"activity_id": activity}),
                        },
                        *(
                            {
                                "item_kind": "current_concern",
                                "source": {
                                    "kind": "cognition_focus",
                                    "reference": str(uuid7()),
                                },
                                "content": json.dumps(
                                    {"consideration_reason": "ongoing_concern"}
                                ),
                            }
                            for _ in range(4)
                        ),
                        {
                            "item_kind": "current_concern",
                            "source": {"kind": "cognition_focus", "reference": concern},
                            "content": json.dumps(
                                {"consideration_reason": "review_time_reached"}
                            ),
                        },
                    ]
                }
            ]
        }

    first, second = str(uuid7()), str(uuid7())
    before, after = (
        evaluation_targets(event, context(first)),
        evaluation_targets(event, context(second)),
    )
    assert len(before) == len(after) == 4
    assert before[0].object == after[0].object
    assert after[0].object.source_ref == activity
    assert first in before[0].basis_refs and second in after[0].basis_refs
    assert after[1].object.source_ref == str(event.source_ref)
    assert after[2].object.source_ref == concern
