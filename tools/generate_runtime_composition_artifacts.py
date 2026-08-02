"""Generate or verify packaged S008 Runtime composition resources."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from armi_runtime.composition.manifest import (
    build_composition_manifest,
    canonical_manifest_bytes,
)

_TARGET = Path("apps/armi-runtime/src/armi_runtime/composition/runtime_resources")
_CONFIG = {
    "runtime.defaults.toml": Path("config/runtime.defaults.toml"),
    "runtime.schema.json": Path("config/runtime.schema.json"),
    "runtime-config-manifest.json": Path("config/runtime-config-manifest.json"),
}
_CREATOR = Path("apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources")
_SCHEMA = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
_SCHEMA_FILES = (
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
)
_CONTEXT_POLICY = Path("context/context-policy.manifest.json")
_MODEL_BINDING = Path("model/model-bindings.manifest.json")
_WEB_SEARCH_BINDING = Path("model/web-search-binding.manifest.json")
_WEB_SEARCH_CUSTODY = Path("model/web-search-custody.manifest.json")
_CANDIDATE_POLICY = Path("model/candidate-validation-policy.manifest.json")
_SUBJECT_COMMIT_POLICY = Path("model/subject-commit-policy.manifest.json")
_CAPABILITY_CATALOG = Path("model/capability-catalog.manifest.json")
_CREATOR_GRANT_POLICY = Path("model/creator-grant-policy.manifest.json")
_RESPONSE_ADMISSION_POLICY = Path("model/response-admission-policy.manifest.json")


def _generate(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    config_resources: dict[str, bytes] = {}
    for target_name, source_relative in _CONFIG.items():
        value = (root / source_relative).read_bytes()
        config_resources[target_name] = value
        (output / target_name).write_bytes(value)
    creator_manifest = (root / _CREATOR / "manifest.json").read_bytes()
    creator_openapi = (root / _CREATOR / "openapi.json").read_bytes()
    birth_contract = (root / _TARGET / "birth-contract.manifest.json").read_bytes()
    (output / "birth-contract.manifest.json").write_bytes(birth_contract)
    context_policy = (root / _CONTEXT_POLICY).read_bytes()
    (output / "context-policy.manifest.json").write_bytes(context_policy)
    model_binding = (root / _MODEL_BINDING).read_bytes()
    (output / "model-bindings.manifest.json").write_bytes(model_binding)
    web_search_binding = (root / _WEB_SEARCH_BINDING).read_bytes()
    (output / "web-search-binding.manifest.json").write_bytes(web_search_binding)
    web_search_custody = (root / _WEB_SEARCH_CUSTODY).read_bytes()
    (output / "web-search-custody.manifest.json").write_bytes(web_search_custody)
    candidate_policy = (root / _CANDIDATE_POLICY).read_bytes()
    (output / "candidate-validation-policy.manifest.json").write_bytes(candidate_policy)
    subject_commit_policy = (root / _SUBJECT_COMMIT_POLICY).read_bytes()
    (output / "subject-commit-policy.manifest.json").write_bytes(subject_commit_policy)
    capability_catalog = (root / _CAPABILITY_CATALOG).read_bytes()
    (output / "capability-catalog.manifest.json").write_bytes(capability_catalog)
    creator_grant_policy = (root / _CREATOR_GRANT_POLICY).read_bytes()
    (output / "creator-grant-policy.manifest.json").write_bytes(creator_grant_policy)
    response_admission_policy = (root / _RESPONSE_ADMISSION_POLICY).read_bytes()
    (output / "response-admission-policy.manifest.json").write_bytes(
        response_admission_policy
    )
    schema_resources = {
        name: (root / _SCHEMA / name).read_bytes() for name in _SCHEMA_FILES
    }
    manifest = build_composition_manifest(
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
        schema_resources=schema_resources,
    )
    (output / "runtime-composition.manifest.json").write_bytes(
        canonical_manifest_bytes(manifest)
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        name: (root / name).read_bytes()
        for name in (
            *_CONFIG,
            "birth-contract.manifest.json",
            "context-policy.manifest.json",
            "model-bindings.manifest.json",
            "web-search-binding.manifest.json",
            "web-search-custody.manifest.json",
            "candidate-validation-policy.manifest.json",
            "subject-commit-policy.manifest.json",
            "capability-catalog.manifest.json",
            "creator-grant-policy.manifest.json",
            "response-admission-policy.manifest.json",
            "runtime-composition.manifest.json",
        )
        if (root / name).is_file()
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="runtime-composition-",
            dir=temporary_root,
        ) as temporary:
            generated = Path(temporary)
            _generate(root, generated)
            target = root / _TARGET
            if args.write:
                target.mkdir(parents=True, exist_ok=True)
                for name, value in _files(generated).items():
                    destination = target / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(value)
            elif _files(generated) != _files(target):
                print(
                    "CMP-MANIFEST-DRIFT: packaged composition resources drifted",
                    file=sys.stderr,
                )
                return 1
        print(
            "runtime-composition: written"
            if args.write
            else "runtime-composition: verified"
        )
        return 0
    except OSError:
        print(
            "CMP-RESOURCE-MISSING: a composition input is unavailable",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
