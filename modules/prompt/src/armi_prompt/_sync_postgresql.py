"""Small synchronous Prompt probes used before Runtime async composition."""

from __future__ import annotations

from uuid import UUID

import psycopg

from .api import PromptContinuityCounts, PromptViolation


def probe_prompt_continuity(
    conninfo: str, *, subject_id: UUID | None
) -> PromptContinuityCounts:
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            if subject_id is None:
                row = connection.execute(
                    """SELECT (SELECT count(*) FROM armi.prompt_documents),
                              (SELECT count(*) FROM armi.prompt_revisions)"""
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM armi.prompt_documents
                         WHERE subject_id = %s),
                        (SELECT count(*)
                         FROM armi.prompt_revisions AS revision
                         JOIN armi.prompt_documents AS document
                           ON document.prompt_document_id = revision.prompt_document_id
                         WHERE document.subject_id = %s)
                    """,
                    (subject_id, subject_id),
                ).fetchone()
    except psycopg.Error:
        raise PromptViolation("PROMPT-CONTINUITY-DATABASE") from None
    if row is None:
        raise PromptViolation("PROMPT-CONTINUITY-INTEGRITY")
    return PromptContinuityCounts(int(row[0]), int(row[1]))


__all__ = ("probe_prompt_continuity",)
