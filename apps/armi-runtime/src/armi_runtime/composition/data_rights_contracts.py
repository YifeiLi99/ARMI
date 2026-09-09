"""Frozen owner declarations checked against the installed v5 schema."""

from armi_data_rights.api import (
    DataRightsArtifactField,
    DataRightsOwnerContract,
    DataRightsOwnerIdentity,
)


def _contract(
    owner: str,
    owns: tuple[str, ...],
    fields: tuple[tuple[str, str, str], ...],
) -> DataRightsOwnerContract:
    return DataRightsOwnerContract(
        DataRightsOwnerIdentity(owner),
        owns=frozenset(owns),
        artifact_fields=tuple(DataRightsArtifactField(*item) for item in fields),
    )


DATA_RIGHTS_OWNER_CONTRACTS = (
    _contract("activity", ("activity",), ()),
    _contract("artifact-store", ("artifact",), ()),
    _contract(
        "expression",
        ("effect",),
        (("action_intent_revisions", "response_artifact_id", "objective"),),
    ),
    _contract(
        "codex",
        ("codex_task",),
        tuple(
            (table, column, "party")
            for table, column in (
                ("codex_result_sources", "evidence_artifact_id"),
                ("codex_task_sources", "source_bundle_artifact_id"),
                ("codex_task_sources", "task_manifest_artifact_id"),
                ("codex_verification_results", "diagnostics_artifact_id"),
                ("codex_verification_results", "event_transcript_artifact_id"),
                ("codex_verification_results", "final_result_artifact_id"),
                ("codex_verification_results", "patch_artifact_id"),
                ("codex_verification_results", "result_bundle_artifact_id"),
                ("codex_verification_results", "validation_report_artifact_id"),
            )
        ),
    ),
    _contract(
        "cognition",
        ("cognition",),
        tuple(
            (table, column, "party")
            for table, column in (
                ("cognitive_attempts", "request_artifact_id"),
                ("cognitive_attempts", "response_artifact_id"),
                ("cognitive_candidate_validations", "change_set_artifact_id"),
                ("cognitive_episodes", "compiled_context_artifact_id"),
                ("cognitive_episodes", "context_manifest_artifact_id"),
                ("exact_life_query_intents", "result_artifact_id"),
            )
        ),
    ),
    _contract("context", (), ()),
    _contract("data-rights", ("managed_snapshot",), ()),
    _contract(
        "effect",
        ("effect",),
        (
            ("effects", "payload_artifact_id", "objective"),
            ("local_inbox_deliveries", "payload_artifact_id", "objective"),
        ),
    ),
    _contract(
        "evidence", ("evidence",), (("external_evidence", "artifact_id", "party"),)
    ),
    _contract(
        "interaction",
        ("interaction", "scene", "external_binding", "party"),
        (
            ("external_message_parts", "interpretation_artifact_id", "party"),
            ("external_message_parts", "raw_artifact_id", "party"),
        ),
    ),
    _contract("experience", ("experience",), ()),
    _contract("live-voice", ("live_voice",), ()),
    _contract(
        "material",
        ("material",),
        (("life_material_revisions", "artifact_id", "party"),),
    ),
    _contract(
        "live-vision",
        ("media_recognition",),
        (("live_vision_observation_frames", "artifact_id", "shared"),),
    ),
    _contract("memory", ("memory",), ()),
    _contract("mood", ("mood",), ()),
    _contract("opportunity", (), ()),
    _contract(
        "perception",
        ("media_recognition",),
        (
            ("external_content_recognition_attempts", "request_artifact_id", "party"),
            ("external_content_recognition_attempts", "response_artifact_id", "party"),
            ("visual_recognition_attempts", "request_artifact_id", "shared"),
            ("visual_recognition_attempts", "response_artifact_id", "shared"),
        ),
    ),
    _contract(
        "prompt", ("prompt",), (("prompt_revisions", "content_artifact_id", "party"),)
    ),
    _contract("relationship", ("relationship",), ()),
    _contract("runtime", (), ()),
    _contract("sleep", (), ()),
    _contract("subject-state", ("subject_component",), ()),
    _contract(
        "web-observation",
        ("web_research",),
        (
            ("observation_attempts", "result_artifact_id", "party"),
            ("web_evidence_sources", "source_artifact_id", "party"),
            ("web_observation_requests", "request_artifact_id", "party"),
            ("web_observation_requests", "result_artifact_id", "party"),
            ("web_research_intents", "query_artifact_id", "party"),
        ),
    ),
)

__all__ = ("DATA_RIGHTS_OWNER_CONTRACTS",)
