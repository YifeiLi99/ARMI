"""Frozen, explicitly wired Runtime composition manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, cast

import rfc8785

from .runtime_errors import RuntimeViolation

COMPOSITION_SCHEMA_VERSION: Final = "armi.runtime-composition.v1"
_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_CREATOR_PACKAGE = "armi_runtime.interfaces.creator_web_resources"
_SEAMS: Final = (
    ("M0-SEAM-CONTEXT", ("M0-S023",)),
    ("M0-SEAM-MODEL", ("M0-S024",)),
    ("M0-SEAM-COGNITIVE-CANDIDATE", ("M0-S025", "M0-S026")),
    ("M0-SEAM-WORK-SELECTION", ("M0-S023",)),
    ("M0-SEAM-POLICY", ("M0-S027—M0-S029",)),
    ("M0-SEAM-EFFECT", ("M0-S030",)),
    ("M0-SEAM-WEB", ("M0-S032—M0-S034",)),
    ("M0-SEAM-CODEX", ("M0-S038", "M0-S039")),
    (
        "M0-SEAM-CREATOR-PROJECTION",
        ("M0-S019", "M0-S020", "M0-S021", "M0-S030", "M0-S031"),
    ),
    (
        "M0-SEAM-CREATOR-UI",
        ("M0-S007", "M0-S020", "M0-S022", "M0-S031", "M0-S043"),
    ),
)
_CONFIG_FILES: Final = (
    "runtime.defaults.toml",
    "runtime.schema.json",
    "runtime-config-manifest.json",
)
_BIRTH_CONTRACT_FILE: Final = "birth-contract.manifest.json"
_CONTEXT_POLICY_FILE: Final = "context-policy.manifest.json"
_MODEL_BINDING_FILE: Final = "model-bindings.manifest.json"
_WEB_SEARCH_BINDING_FILE: Final = "web-search-binding.manifest.json"
_WEB_SEARCH_CUSTODY_FILE: Final = "web-search-custody.manifest.json"
_CANDIDATE_POLICY_FILE: Final = "candidate-validation-policy.manifest.json"
_SUBJECT_COMMIT_POLICY_FILE: Final = "subject-commit-policy.manifest.json"
_CAPABILITY_CATALOG_FILE: Final = "capability-catalog.manifest.json"
_CREATOR_GRANT_POLICY_FILE: Final = "creator-grant-policy.manifest.json"
_RESPONSE_ADMISSION_POLICY_FILE: Final = "response-admission-policy.manifest.json"
_CODEX_RUNNER_FILE: Final = "codex-runner.manifest.json"
_SCHEMA_FILES: Final = (
    "checks/invariants.sql",
    "manifests/database-role-manifest.json",
    "manifests/schema-manifest.json",
    "migrations/0001_m0_baseline.sql",
    "migrations/0002_database_permissions.sql",
    "migrations/0003_content_addressed_artifacts.sql",
    "migrations/0004_normal_audit_foundation.sql",
    "migrations/0005_durable_work_and_outbox.sql",
    "migrations/0006_unique_birth.sql",
    "migrations/0007_runtime_authority.sql",
    "migrations/0008_runtime_recovery.sql",
    "migrations/0009_scene_timeline_query.sql",
    "migrations/0010_creator_input_acceptance.sql",
    "migrations/0011_context_snapshot_and_compilation.sql",
    "migrations/0012_real_model_attempts.sql",
    "migrations/0013_cognition_candidate_validation.sql",
    "migrations/0014_t03_subject_commit.sql",
    "migrations/0015_minimal_capability_grants.sql",
    "migrations/0016_response_and_formal_no_action.sql",
    "migrations/0017_effect_intent_and_ledger.sql",
    "migrations/0018_effect_dispatch_observation_settlement.sql",
    "migrations/0019_readonly_web_search_custody.sql",
    "migrations/0020_web_search_evidence_closure.sql",
    "migrations/0021_admin_observation_and_environment.sql",
    "migrations/0022_t07_admin_correction.sql",
    "migrations/0023_codex_runner_activation.sql",
    "migrations/0024_codex_delegation_acceptance.sql",
    "migrations/0025_creator_codex_task_intake.sql",
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def build_composition_manifest(
    *,
    config_resources: dict[str, bytes],
    creator_manifest: bytes,
    creator_openapi: bytes,
    birth_contract: bytes,
    context_policy: bytes,
    model_binding: bytes,
    web_search_binding: bytes,
    web_search_custody: bytes,
    candidate_policy: bytes,
    subject_commit_policy: bytes,
    capability_catalog: bytes,
    creator_grant_policy: bytes,
    response_admission_policy: bytes,
    codex_runner: bytes,
    schema_resources: dict[str, bytes],
) -> dict[str, object]:
    """Return the only allowed S008 composition declaration."""

    if set(config_resources) != set(_CONFIG_FILES):
        raise RuntimeViolation(
            "CMP-RESOURCE-SET",
            "the packaged configuration resource set is incomplete",
        )
    if set(schema_resources) != set(_SCHEMA_FILES):
        raise RuntimeViolation(
            "CMP-RESOURCE-SET",
            "the packaged schema resource set is incomplete",
        )
    seams: list[dict[str, object]] = []
    for seam_id, activation_steps in _SEAMS:
        active = (
            "armi.creator-workbench.v1"
            if seam_id == "M0-SEAM-CREATOR-UI"
            else "armi.creator-projection-workbench.v1"
            if seam_id == "M0-SEAM-CREATOR-PROJECTION"
            else "armi.context-compiler.deterministic-v1"
            if seam_id == "M0-SEAM-CONTEXT"
            else "armi.model-adapter.volcengine-ark-responses-v1"
            if seam_id == "M0-SEAM-MODEL"
            else "armi.candidate-validator.deterministic-v1"
            if seam_id == "M0-SEAM-COGNITIVE-CANDIDATE"
            else "armi.opportunity-selector.creator-fifo-v1"
            if seam_id == "M0-SEAM-WORK-SELECTION"
            else "armi.policy-engine.deterministic-v1"
            if seam_id == "M0-SEAM-POLICY"
            else "armi.creator-response-adapter.postgresql-inbox-v1"
            if seam_id == "M0-SEAM-EFFECT"
            else "armi.codex-runner.openai-python-sdk-v1"
            if seam_id == "M0-SEAM-CODEX"
            else None
        )
        seams.append(
            {
                "seam_id": seam_id,
                "active_binding": active,
                "activation_steps": list(activation_steps),
                "runtime_discovery": False,
            }
        )
    return {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "entry_point": "armi",
        "runtime_discovery": False,
        "seams": seams,
        "readiness_blockers": [],
        "resources": {
            **{
                f"config/{name}": _sha256(value)
                for name, value in sorted(config_resources.items())
            },
            "creator/manifest.json": _sha256(creator_manifest),
            "creator/openapi.json": _sha256(creator_openapi),
            f"bootstrap/{_BIRTH_CONTRACT_FILE}": _sha256(birth_contract),
            f"context/{_CONTEXT_POLICY_FILE}": _sha256(context_policy),
            f"model/{_MODEL_BINDING_FILE}": _sha256(model_binding),
            f"model/{_WEB_SEARCH_BINDING_FILE}": _sha256(web_search_binding),
            f"model/{_WEB_SEARCH_CUSTODY_FILE}": _sha256(web_search_custody),
            f"candidate/{_CANDIDATE_POLICY_FILE}": _sha256(candidate_policy),
            f"subject-commit/{_SUBJECT_COMMIT_POLICY_FILE}": _sha256(
                subject_commit_policy
            ),
            f"capability/{_CAPABILITY_CATALOG_FILE}": _sha256(capability_catalog),
            f"policy/{_CREATOR_GRANT_POLICY_FILE}": _sha256(creator_grant_policy),
            f"response/{_RESPONSE_ADMISSION_POLICY_FILE}": _sha256(
                response_admission_policy
            ),
            f"codex/{_CODEX_RUNNER_FILE}": _sha256(codex_runner),
            **{
                f"schema/{name}": _sha256(value)
                for name, value in sorted(schema_resources.items())
            },
        },
        "runtime_business_contract": True,
    }


def canonical_manifest_bytes(value: dict[str, object]) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


@dataclass(frozen=True, slots=True)
class VerifiedComposition:
    schema_version: str
    active_bindings: tuple[tuple[str, str | None], ...]
    readiness_blockers: tuple[str, ...]
    digest: str


def verify_packaged_composition() -> VerifiedComposition:
    """Verify the package copies and the explicit seam set before listening."""

    resources = files(_RESOURCE_PACKAGE)
    schema = resources.joinpath("schema")
    creator = files(_CREATOR_PACKAGE)
    try:
        config_resources = {
            name: resources.joinpath(name).read_bytes() for name in _CONFIG_FILES
        }
        creator_manifest = creator.joinpath("manifest.json").read_bytes()
        creator_openapi = creator.joinpath("openapi.json").read_bytes()
        birth_contract = resources.joinpath(_BIRTH_CONTRACT_FILE).read_bytes()
        context_policy = resources.joinpath(_CONTEXT_POLICY_FILE).read_bytes()
        model_binding = resources.joinpath(_MODEL_BINDING_FILE).read_bytes()
        web_search_binding = resources.joinpath(_WEB_SEARCH_BINDING_FILE).read_bytes()
        web_search_custody = resources.joinpath(_WEB_SEARCH_CUSTODY_FILE).read_bytes()
        candidate_policy = resources.joinpath(_CANDIDATE_POLICY_FILE).read_bytes()
        subject_commit_policy = resources.joinpath(
            _SUBJECT_COMMIT_POLICY_FILE
        ).read_bytes()
        capability_catalog = resources.joinpath(_CAPABILITY_CATALOG_FILE).read_bytes()
        creator_grant_policy = resources.joinpath(
            _CREATOR_GRANT_POLICY_FILE
        ).read_bytes()
        response_admission_policy = resources.joinpath(
            _RESPONSE_ADMISSION_POLICY_FILE
        ).read_bytes()
        codex_runner = resources.joinpath(_CODEX_RUNNER_FILE).read_bytes()
        committed = resources.joinpath("runtime-composition.manifest.json").read_bytes()
        schema_resources = {
            name: schema.joinpath(name).read_bytes() for name in _SCHEMA_FILES
        }
    except OSError:
        raise RuntimeViolation(
            "CMP-RESOURCE-MISSING",
            "a required packaged Runtime resource is unavailable",
        ) from None
    expected = build_composition_manifest(
        config_resources=config_resources,
        creator_manifest=creator_manifest,
        creator_openapi=creator_openapi,
        birth_contract=birth_contract,
        context_policy=context_policy,
        model_binding=model_binding,
        web_search_binding=web_search_binding,
        web_search_custody=web_search_custody,
        candidate_policy=candidate_policy,
        subject_commit_policy=subject_commit_policy,
        capability_catalog=capability_catalog,
        creator_grant_policy=creator_grant_policy,
        response_admission_policy=response_admission_policy,
        codex_runner=codex_runner,
        schema_resources=schema_resources,
    )
    expected_bytes = canonical_manifest_bytes(expected)
    if committed != expected_bytes:
        raise RuntimeViolation(
            "CMP-MANIFEST-DRIFT",
            "the packaged Runtime composition manifest has drifted",
        )
    try:
        parsed = json.loads(committed)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise RuntimeViolation(
            "CMP-MANIFEST-FORMAT",
            "the packaged Runtime composition manifest is malformed",
        ) from None
    seams = parsed["seams"]
    blockers = parsed["readiness_blockers"]
    return VerifiedComposition(
        schema_version=COMPOSITION_SCHEMA_VERSION,
        active_bindings=tuple(
            (entry["seam_id"], entry["active_binding"]) for entry in seams
        ),
        readiness_blockers=tuple(entry["reason_code"] for entry in blockers),
        digest=_sha256(committed),
    )


__all__ = (
    "COMPOSITION_SCHEMA_VERSION",
    "VerifiedComposition",
    "build_composition_manifest",
    "canonical_manifest_bytes",
    "verify_packaged_composition",
)
