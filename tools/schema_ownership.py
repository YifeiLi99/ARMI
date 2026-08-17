"""Single source of truth for ownership of persistent ``armi`` tables."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_TABLE_CHANGE = re.compile(
    r"\b(?P<operation>CREATE|DROP)\s+TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?\s+"
    r"armi\.(?P<table>[a-z][a-z0-9_]*)",
    re.IGNORECASE,
)
_SQL_TABLE_REFERENCE = re.compile(
    r"\b(?P<operation>FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)"
    r"\s+(?:ONLY\s+)?armi\.(?P<table>[a-z][a-z0-9_]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TableOwnership:
    owner: str
    pending_removal: bool = False


@dataclass(frozen=True, order=True, slots=True)
class ForeignTableAccess:
    path: str
    line: int
    source_owner: str
    table: str
    table_owner: str
    operation: str


TABLE_OWNERSHIP: Mapping[str, TableOwnership] = {
    # Runtime/Foundation facts.
    "audit_events": TableOwnership("runtime"),
    "deployment_environments": TableOwnership("runtime"),
    "durable_work": TableOwnership("runtime"),
    "life_generations": TableOwnership("runtime"),
    "runtime_bundle_activations": TableOwnership("runtime"),
    "runtime_instances": TableOwnership("runtime"),
    "runtime_recovery_metrics": TableOwnership("runtime"),
    "runtime_recovery_runs": TableOwnership("runtime"),
    "subject_commits": TableOwnership("runtime"),
    "subjects": TableOwnership("runtime"),
    # Technical artifact catalog.
    "artifacts": TableOwnership("artifact-store"),
    # Interaction.
    "external_channel_bindings": TableOwnership("interaction"),
    "external_message_parts": TableOwnership("interaction"),
    "interaction_scenes": TableOwnership("interaction"),
    "parties": TableOwnership("interaction"),
    "party_input_interactions": TableOwnership("interaction"),
    "scene_participants": TableOwnership("interaction"),
    "scene_timeline_items": TableOwnership("interaction"),
    # Perception and evidence.
    "external_content_recognition_attempts": TableOwnership("perception"),
    "experience_evidence_links": TableOwnership("evidence"),
    "external_evidence": TableOwnership("evidence"),
    # Attention and context.
    "opportunities": TableOwnership("attention"),
    "cognitive_context_items": TableOwnership("context"),
    "context_embedding_attempts": TableOwnership("context"),
    "context_embedding_projections": TableOwnership("context"),
    # Cognition.
    "accepted_experiences": TableOwnership("cognition"),
    "cognitive_attempts": TableOwnership("cognition"),
    "cognitive_branches": TableOwnership("cognition"),
    "cognitive_candidate_applications": TableOwnership("cognition"),
    "cognitive_candidate_basis_links": TableOwnership("cognition"),
    "cognitive_candidate_validation_items": TableOwnership("cognition"),
    "cognitive_candidate_validations": TableOwnership("cognition"),
    "cognitive_episodes": TableOwnership("cognition"),
    "cognitive_dialogue_aggregates": TableOwnership("cognition"),
    "cognition_maintenance_batch_sources": TableOwnership("cognition"),
    "cognition_maintenance_batches": TableOwnership("cognition"),
    "cognition_maintenance_cursors": TableOwnership("cognition"),
    "exact_life_query_intents": TableOwnership("cognition"),
    # Subject-owned components.
    "subject_component_heads": TableOwnership("subject-state"),
    "subject_component_revisions": TableOwnership("subject-state"),
    "prompt_documents": TableOwnership("prompt"),
    "prompt_revisions": TableOwnership("prompt"),
    "mood_heads": TableOwnership("mood"),
    "mood_revisions": TableOwnership("mood"),
    # Life facts.
    "memory_relations": TableOwnership("memory"),
    "subjective_memories": TableOwnership("memory"),
    "subjective_memory_revisions": TableOwnership("memory"),
    "relationship_experience_links": TableOwnership("relationship"),
    "relationship_revisions": TableOwnership("relationship"),
    "relationships": TableOwnership("relationship"),
    "life_material_revisions": TableOwnership("material"),
    "life_materials": TableOwnership("material"),
    "activities": TableOwnership("activity"),
    "activity_decisions": TableOwnership("activity"),
    "activity_revisions": TableOwnership("activity"),
    "maintenance_phase_results": TableOwnership("sleep"),
    "maintenance_session_revisions": TableOwnership("sleep"),
    "maintenance_sessions": TableOwnership("sleep"),
    "sleep_decisions": TableOwnership("sleep"),
    # Expression, capability, and effect lifecycle.
    "action_intent_revisions": TableOwnership("expression"),
    "action_intents": TableOwnership("expression"),
    "dialogue_decisions": TableOwnership("expression"),
    "capabilities": TableOwnership("capability"),
    "capability_request_basis_links": TableOwnership("capability"),
    "capability_request_decisions": TableOwnership("capability"),
    "capability_requests": TableOwnership("capability"),
    "permission_grants": TableOwnership("capability"),
    "policy_decisions": TableOwnership("capability"),
    "effect_attempts": TableOwnership("effect"),
    "effect_observations": TableOwnership("effect"),
    "effect_outbox_items": TableOwnership("effect"),
    "effects": TableOwnership("effect"),
    "local_inbox_deliveries": TableOwnership("effect"),
    # Web, Codex, and Data Rights.
    "observation_attempts": TableOwnership("web-observation"),
    "observation_tool_calls": TableOwnership("web-observation"),
    "web_evidence_sources": TableOwnership("web-observation"),
    "web_observation_requests": TableOwnership("web-observation"),
    "web_research_intents": TableOwnership("web-observation"),
    "codex_result_sources": TableOwnership("codex"),
    "codex_task_sources": TableOwnership("codex"),
    "codex_verification_results": TableOwnership("codex"),
    "creator_exports": TableOwnership("data-rights"),
    "deletion_items": TableOwnership("data-rights"),
    "deletion_orders": TableOwnership("data-rights"),
}


def schema_tables_at_head(schema_root: Path) -> frozenset[str]:
    """Extract the effective table set from frozen baseline and ordered revisions."""

    baseline = schema_root / "baseline"
    revisions = schema_root / "alembic" / "versions"
    sources: Iterable[Path] = (
        *sorted(baseline.glob("*.sql")),
        *sorted(revisions.glob("[0-9][0-9][0-9][0-9]_*.py")),
    )
    tables: set[str] = set()
    for path in sources:
        for match in _TABLE_CHANGE.finditer(path.read_text(encoding="utf-8")):
            table = match.group("table").lower()
            if match.group("operation").upper() == "CREATE":
                tables.add(table)
            else:
                tables.discard(table)
    return frozenset(tables)


def ownership_registry_errors(schema_root: Path) -> tuple[str, ...]:
    schema_tables = schema_tables_at_head(schema_root)
    registered_tables = frozenset(TABLE_OWNERSHIP)
    errors = [
        *(
            f"unregistered table: armi.{table}"
            for table in schema_tables - registered_tables
        ),
        *(
            f"stale registry table: armi.{table}"
            for table in registered_tables - schema_tables
        ),
    ]
    return tuple(sorted(errors))


def source_owner_for_path(path: Path) -> str | None:
    parts = path.as_posix().split("/")
    if (
        path.as_posix()
        == "apps/armi-admin/src/armi_admin/persistence/runtime_foundation.py"
    ):
        return "runtime"
    if len(parts) >= 2 and parts[0] == "modules":
        return parts[1]
    if parts[:2] == ["apps", "armi-runtime"]:
        return "runtime"
    if parts[:2] == ["apps", "armi-admin"]:
        return "admin"
    if parts[:2] == ["packages", "armi-artifact-store"]:
        return "artifact-store"
    return None


def scan_source_foreign_table_accesses(
    source: str,
    *,
    path: str,
    source_owner: str,
) -> tuple[ForeignTableAccess, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    accesses: list[ForeignTableAccess] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for match in _SQL_TABLE_REFERENCE.finditer(node.value):
            table = match.group("table").lower()
            ownership = TABLE_OWNERSHIP.get(table)
            if ownership is None or ownership.owner == source_owner:
                continue
            operation = " ".join(match.group("operation").upper().split())
            accesses.append(
                ForeignTableAccess(
                    path=path,
                    line=node.lineno + node.value[: match.start()].count("\n"),
                    source_owner=source_owner,
                    table=table,
                    table_owner=ownership.owner,
                    operation=operation,
                )
            )
    return tuple(sorted(accesses))


def scan_repository_foreign_table_accesses(
    root: Path,
) -> tuple[ForeignTableAccess, ...]:
    accesses: list[ForeignTableAccess] = []
    for area in ("apps", "modules", "packages"):
        for path in (root / area).glob("*/src/**/*.py"):
            relative = path.relative_to(root)
            source_owner = source_owner_for_path(relative)
            if source_owner is None:
                continue
            accesses.extend(
                scan_source_foreign_table_accesses(
                    path.read_text(encoding="utf-8"),
                    path=relative.as_posix(),
                    source_owner=source_owner,
                )
            )
    return tuple(sorted(accesses))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report cross-owner ARMI table access")
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    schema_root = (
        root / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
    )
    errors = ownership_registry_errors(schema_root)
    if errors:
        for error in errors:
            print(error)
        return 1
    accesses = scan_repository_foreign_table_accesses(root)
    for access in accesses:
        print(
            f"{access.path}:{access.line}: {access.operation} armi.{access.table} "
            f"({access.source_owner} -> {access.table_owner})"
        )
    print(f"foreign-table-accesses: {len(accesses)}")
    return 0


__all__ = (
    "TABLE_OWNERSHIP",
    "ForeignTableAccess",
    "TableOwnership",
    "main",
    "ownership_registry_errors",
    "scan_repository_foreign_table_accesses",
    "scan_source_foreign_table_accesses",
    "schema_tables_at_head",
    "source_owner_for_path",
)


if __name__ == "__main__":
    sys.exit(main())
