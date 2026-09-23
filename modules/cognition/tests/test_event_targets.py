from datetime import UTC, datetime
from uuid import uuid7

from armi_cognition._event_store import evaluation_targets
from armi_cognition.api import EventAppraisalRequest
from armi_mood.api import MoodEvent


def test_input_and_tool_result_each_appraise_only_their_own_event():
    now = datetime.now(UTC)
    source_refs = (uuid7(), uuid7())
    for index, source_ref in enumerate(source_refs):
        event = MoodEvent(
            f"event:{index}", uuid7(), uuid7(), source_ref, 1, now, "event content"
        )
        targets = evaluation_targets(event)
        request = EventAppraisalRequest(
            event.event_key, str(source_ref), now, (), targets
        )
        assert len(request.questions()) == 43
        assert len(targets) == 1
        assert targets[0].object.source_kind == "event"
        assert targets[0].object.source_ref == str(source_ref)
        assert targets[0].basis_refs == (str(source_ref),)
