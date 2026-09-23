"""The real Jev binding fits the shared attempt ledger without invented IDs."""

import os
from typing import Any, cast

import psycopg
import pytest
from armi_runtime.adapters.model.jev_autonomy import JevAutonomyCheck

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.test_group("cognition", "attention", "model"),
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


def test_jev_attempt_preserves_absent_provider_request_id():
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()

    async def probe(fixture, born, ids, fence, lease):
        binding = JevAutonomyCheck(
            credentials=cast(Any, None), locator=None, timeout_seconds=20
        ).binding
        with psycopg.connect(fixture.provisioner_dsn) as db:
            # The shared fixture supplies real episode, work and retained Artifact FKs.
            db.execute(
                "UPDATE armi.cognitive_attempts SET provider=%s,model_id=%s,version_policy=%s,"
                "profile=%s,candidate_contract_kind=%s,credential_identity=%s,"
                "provider_model_id=%s,provider_request_id=NULL WHERE model_attempt_id=%s",
                (
                    binding.provider,
                    binding.model_id,
                    binding.version_policy,
                    binding.profile,
                    binding.response_contract_kind,
                    binding.credential_identity,
                    binding.model_id,
                    ids["model_attempt"],
                ),
            )
            assert db.execute(
                "SELECT provider,profile,result_status,provider_request_id FROM armi.cognitive_attempts WHERE model_attempt_id=%s",
                (ids["model_attempt"],),
            ).fetchone() == ("typesafe", "autonomy_check", "succeeded", None)
            with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
                db.execute(
                    "UPDATE armi.cognitive_attempts SET provider='deepseek' WHERE model_attempt_id=%s",
                    (ids["model_attempt"],),
                )

    try:
        case._exercise_creator_reply(mood_probe=probe)
    finally:
        case.tearDownClass()
