"""Versioned administrator changes owned by Relationship."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

from armi_runtime_foundation import (
    AdminContentCommand,
    AdminContentContext,
    AdminContentViolation,
    PostgreSQLAdminTransaction,
)

from ._codec import decode_boundaries, decode_commitments, decode_facts, decode_issues
from .api import RelationshipViolation


class PostgreSQLRelationshipAdmin:
    def apply(
        self,
        tx: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
    ) -> dict[str, Any]:
        values = cast(dict[str, Any], command.values)
        tx.execute(
            "SELECT relationship_revision_id FROM armi.relationship_revisions "
            "WHERE relationship_id=%s AND revision_no=1 FOR UPDATE",
            (command.object_id,),
        )
        row = cast(
            tuple[Any, ...] | None,
            tx.execute(
                "SELECT r.relationship_revision_id,r.revision_no,r.tombstoned_at,r.facts,r.interpretation,r.boundaries,r.commitments,r.open_issues,r.other_party_id,r.subject_party_id,r.scope,r.relationship_created_at FROM armi.relationship_revisions r WHERE r.relationship_id=%s AND r.subject_id=%s AND r.is_current FOR UPDATE OF r",
                (command.object_id, context.subject_id),
            ).fetchone(),
        )
        if command.action == "create":
            if row is not None or command.expected_version != 0:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        elif row is None or row[1] != command.expected_version or row[2] is not None:
            raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        if command.action == "delete":
            if values or row is None:
                raise RelationshipViolation("RELATIONSHIP-ADMIN-PAYLOAD")
            facts, interpretation, boundaries, commitments, issues = row[3:8]
            status = "ended"
            boundaries = [
                item
                for item in boundaries
                if (item["party_role"], item["kind"]) != ("subject", "contact")
            ]
            boundaries.append(
                {
                    "party_role": "subject",
                    "kind": "contact",
                    "action": "end_contact",
                    "summary": "管理员结束此关系",
                }
            )
        else:
            expected = {
                "facts",
                "interpretation",
                "boundaries",
                "commitments",
                "open_issues",
                "status",
            }
            if command.action == "create":
                expected.add("other_party_id")
            if set(values) != expected:
                raise RelationshipViolation("RELATIONSHIP-ADMIN-PAYLOAD")
            facts, interpretation, boundaries, commitments, issues = (
                values["facts"],
                values["interpretation"],
                values["boundaries"],
                values["commitments"],
                values["open_issues"],
            )
            status = values["status"]
            parsed_facts = decode_facts(facts)
            parsed_boundaries = decode_boundaries(boundaries)
            parsed_commitments = decode_commitments(commitments)
            parsed_issues = decode_issues(issues)
            if (
                not 1 <= len(parsed_facts) <= 64
                or len({item.fact_id for item in parsed_facts}) != len(parsed_facts)
                or len(parsed_boundaries) > 16
                or len({(item.party_role, item.kind) for item in parsed_boundaries})
                != len(parsed_boundaries)
                or (status == "ended")
                != any(item.action.value == "end_contact" for item in parsed_boundaries)
                or len(parsed_commitments) > 16
                or len({item.commitment_id for item in parsed_commitments})
                != len(parsed_commitments)
                or len(parsed_issues) > 32
                or len({item.issue_id for item in parsed_issues}) != len(parsed_issues)
                or any(item.status.value != "open" for item in parsed_issues)
                or any(
                    identity not in {item.commitment_id for item in parsed_commitments}
                    for issue in parsed_issues
                    for identity in issue.commitment_ids
                )
                or type(interpretation) is not str
                or not 1 <= len(interpretation) <= 1024
                or "\x00" in interpretation
                or status not in {"active", "ended"}
            ):
                raise RelationshipViolation("RELATIONSHIP-ADMIN-PAYLOAD")
        revision = uuid7()
        version = command.expected_version + 1
        if row is None:
            other = UUID(values["other_party_id"])
            if other == context.subject_party_id:
                raise RelationshipViolation("RELATIONSHIP-ADMIN-PARTY")
            scope = (
                "creator_social"
                if other == context.creator_party_id
                else "other_human_social"
            )
        else:
            other = row[8]
            scope = row[10]
            result = tx.execute(
                "UPDATE armi.relationship_revisions SET is_current=false "
                "WHERE relationship_id=%s AND revision_no=%s "
                "AND relationship_revision_id=%s AND is_current AND tombstoned_at IS NULL",
                (command.object_id, command.expected_version, row[0]),
            )
            if result.rowcount != 1:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
        tx.execute(
            "INSERT INTO armi.relationship_revisions (subject_id,subject_party_id,other_party_id,scope,relationship_created_at,relationship_revision_id,relationship_id,"
            "revision_no,previous_revision_id,admin_change_id,facts,interpretation,boundaries,"
            "commitments,open_issues,relationship_status,mechanism_identity) "
            "VALUES (%s,%s,%s,%s,COALESCE(%s,statement_timestamp()),%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,'armi.relationship.admin-v1')",
            (
                context.subject_id,
                context.subject_party_id if row is None else row[9],
                other,
                scope,
                None if row is None else row[11],
                revision,
                command.object_id,
                version,
                None if row is None else row[0],
                context.change_id,
                json.dumps(facts),
                interpretation,
                json.dumps(boundaries),
                json.dumps(commitments),
                json.dumps(issues),
                status,
            ),
        )
        return {
            "object_id": str(command.object_id),
            "revision_id": str(revision),
            "new_version": version,
            "state": status,
            "history_retained": True,
            "physical_rows_deleted": 0,
        }


__all__ = ("PostgreSQLRelationshipAdmin",)
