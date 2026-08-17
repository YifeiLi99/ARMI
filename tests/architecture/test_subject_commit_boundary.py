"""Permanent boundaries for the cognition-to-subject-commit vertical slice."""

from __future__ import annotations

import re
from pathlib import Path

from armi_cognition.api import CognitionSubjectCommitPort
from armi_experience.api import ExperienceCommitPort

_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_COMMIT = (
    _ROOT
    / "apps"
    / "armi-runtime"
    / "src"
    / "armi_runtime"
    / "adapters"
    / "persistence"
    / "subject_commit.py"
)
_OWNER_APIS = {
    "activity": "ActivityCommitPort",
    "material": "MaterialCommitPort",
    "memory": "MemoryCommitPort",
    "mood": "MoodCommitPort",
    "prompt": "PromptCommitPort",
    "relationship": "RelationshipCommitPort",
    "sleep": "SleepCommitPort",
    "subject-state": "SubjectStateCommitPort",
}


def test_runtime_subject_commit_contains_only_runtime_owned_business_sql() -> None:
    source = _RUNTIME_COMMIT.read_text(encoding="utf-8")
    forbidden = {
        "accepted_experiences",
        "artifacts",
        "cognitive_candidate_applications",
        "cognitive_candidate_basis_links",
        "cognitive_candidate_validation_items",
        "cognitive_candidate_validations",
        "cognitive_context_items",
        "cognitive_episodes",
        "deletion_orders",
        "exact_life_query_intents",
        "external_evidence",
        "interaction_scenes",
        "opportunities",
        "scene_timeline_items",
    }
    assert not forbidden.intersection(re.findall(r"armi\.([a-z0-9_]+)", source))


def test_owner_commit_protocols_do_not_accept_kernel_owner_drafts() -> None:
    for module, protocol in _OWNER_APIS.items():
        package = module.replace("-", "_")
        source = (
            _ROOT / "modules" / module / "src" / f"armi_{package}" / "api.py"
        ).read_text(encoding="utf-8")
        block = source.split(f"class {protocol}(Protocol):", 1)[1].split(
            "\n\n@runtime_checkable", 1
        )[0]
        assert "CandidateOwnerDraft" not in block, module


def test_commit_consumers_do_not_requery_cognition_validation_tables() -> None:
    paths = (
        _ROOT / "modules" / "activity" / "src" / "armi_activity" / "_commit.py",
        _ROOT / "modules" / "capability" / "src" / "armi_capability" / "_postgresql.py",
        _ROOT / "modules" / "codex" / "src" / "armi_codex" / "_commit.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "cognitive_candidate_validation_items" not in source, path
        assert "cognitive_candidate_basis_links" not in source, path


def test_cognition_subject_commit_port_is_replaceable_by_public_fake() -> None:
    class FakeCognition:
        async def snapshot(self, transaction, *, episode_id):
            raise NotImplementedError

        async def existing_application(self, transaction, *, validation_id):
            return None

        async def note_accepted_experience(
            self,
            transaction,
            *,
            subject_id,
            generation_id,
            experience_id,
        ):
            return None

        async def record_application(self, transaction, draft):
            return None

        async def record_exact_life_query(self, transaction, draft):
            return None

        async def finish_episode(
            self,
            transaction,
            *,
            episode_id,
            status,
            application_status,
            failure_code=None,
        ):
            return None

    fake = FakeCognition()
    assert isinstance(fake, CognitionSubjectCommitPort)


def test_experience_commit_port_is_replaceable_by_public_fake() -> None:
    class FakeExperience:
        async def record(self, transaction, draft):
            return None

    assert isinstance(FakeExperience(), ExperienceCommitPort)
