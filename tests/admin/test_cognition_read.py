from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid7

import pytest
from armi_admin.application.contracts import CognitionReadRequest
from armi_admin.application.results import CognitionReadPayload
from armi_admin.persistence.observation_gateway import AdminObservationGateway
from armi_artifact_store.api import ArtifactAdminSnapshot
from armi_cognition.api import CognitionAdminAttempt, CognitionAdminEpisodeSnapshot
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactViolation,
)
from armi_local_control.runtime_errors import RuntimeViolation
from pydantic import ValidationError


@pytest.fixture
def read_case():
    active = []

    @contextmanager
    def transaction():
        active.append(True)
        try:
            yield SimpleNamespace(transaction=object())
        finally:
            active.pop()

    ids = [uuid7() for _ in range(5)]
    episode, opportunity, manifest, request, response = ids
    cognition = Mock()
    cognition.episode.return_value = CognitionAdminEpisodeSnapshot(
        episode,
        opportunity,
        "failed",
        "a" * 32,
        datetime.now(UTC),
        manifest,
        None,
        (response,),
    )
    cognition.attempts.return_value = (
        CognitionAdminAttempt(
            uuid7(),
            1,
            "test-model",
            "historical-candidate",
            request,
            response,
            "settled",
            "succeeded",
            None,
        ),
    )
    artifacts = Mock()
    body = '输入中文🙂\n{"raw":"invalid JSON remains evidence"}'
    snapshot = ArtifactAdminSnapshot(
        response,
        "sha256:" + "a" * 64,
        len(body.encode()),
        "application/json",
        "model.response",
        ArtifactPrivacyScope.PRIVATE,
        ArtifactIntegrityStatus.VERIFIED,
    )
    artifacts.snapshot.return_value = snapshot

    def read(_snapshot):
        assert not active, "Storage I/O must be outside the transaction"
        return body.encode()

    artifacts.read_verified_bytes.side_effect = read
    gateway = AdminObservationGateway(
        factory=cast(Any, SimpleNamespace(repeatable_read=transaction)),
        cognition=cognition,
        artifacts=artifacts,
        **{
            name: Mock()
            for name in (
                "runtime",
                "effects",
                "evidence",
                "opportunity",
                "expression",
                "interaction",
                "materials",
                "mood",
                "subject_state",
                "mind",
                "focus",
                "sleep",
            )
        },
    )
    return gateway, artifacts, cognition, episode, response, body


def test_directory_and_lossless_unicode_pages(read_case):
    gateway, artifacts, _, episode, response, body = read_case
    listing = gateway.cognition_read(
        episode_id=str(episode), artifact_id=None, offset=0, length=4
    )
    CognitionReadPayload.model_validate(listing)
    assert listing["attempts"][0]["candidate_contract_kind"] == "historical-candidate"
    assert {item["role"] for item in listing["artifacts"]} == {
        "context_manifest",
        "request",
        "response",
    }
    artifacts.read_verified_bytes.assert_not_called()
    chunks = []
    offset = 0
    while offset is not None:
        result = gateway.cognition_read(
            episode_id=str(episode), artifact_id=str(response), offset=offset, length=4
        )
        CognitionReadPayload.model_validate(result)
        chunks.append(result["text"]["content"])
        offset = result["text"]["next_offset"]
    assert "".join(chunks) == body
    assert all(
        call.kwargs["retained_only"] for call in artifacts.snapshot.call_args_list
    )


@pytest.mark.parametrize(
    "failure",
    [
        "missing_episode",
        "foreign_artifact",
        "retired",
        "retired_during_read",
        "corrupt",
        "encoding",
        "offset",
    ],
)
def test_read_rejects_unavailable_or_unrelated_content(read_case, failure):
    gateway, artifacts, cognition, episode, response, body = read_case
    selected = response
    offset = 0
    if failure == "missing_episode":
        cognition.episode.return_value = None
    elif failure == "foreign_artifact":
        selected = uuid7()
    elif failure == "retired":
        artifacts.snapshot.return_value = None
    elif failure == "retired_during_read":

        def retire(snapshot):
            artifacts.snapshot.return_value = None
            return body.encode()

        artifacts.read_verified_bytes.side_effect = retire
    elif failure == "corrupt":
        artifacts.read_verified_bytes.side_effect = ArtifactViolation("ART-INTEGRITY")
    elif failure == "encoding":
        artifacts.read_verified_bytes.side_effect = lambda _: b"\xff"
    else:
        offset = len(body) + 1
    with pytest.raises(RuntimeViolation):
        gateway.cognition_read(
            episode_id=str(episode), artifact_id=str(selected), offset=offset, length=4
        )
    if failure in {"missing_episode", "foreign_artifact", "retired"}:
        artifacts.read_verified_bytes.assert_not_called()


@pytest.mark.parametrize(
    "patch",
    [
        {"episode_id": "not-an-id"},
        {"artifact_id": "../secret"},
        {"offset": -1},
        {"length": 65537},
        {"length": True},
    ],
)
def test_request_rejects_invalid_identity_and_page(patch):
    with pytest.raises(ValidationError):
        CognitionReadRequest.model_validate({"episode_id": str(uuid7()), **patch})
