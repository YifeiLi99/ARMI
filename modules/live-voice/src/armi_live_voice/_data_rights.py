"""Data-rights contribution owned by local real-time voice."""

from __future__ import annotations

from typing import LiteralString

from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("live-voice")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "live_voice_sessions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_sessions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_voice_turns",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_turns AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_voice_text_fragments",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_text_fragments AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_voice_provider_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_provider_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_voice_playback_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_playback_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLLiveVoiceDataRightsParticipant:
    owner_identity = _OWNER
    schema_version = _VERSION

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        rows = await (
            await transaction.execute(
                """SELECT session_id FROM armi.live_voice_sessions
                   WHERE creator_party_id=%s ORDER BY session_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("live-voice", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef("live_voice", row[0], "redact") for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        sessions = tuple(
            item.ref for item in request.related_refs if item.kind == "live-voice"
        )
        if request.order_kind == "delete_related" and sessions:
            await transaction.execute(
                """UPDATE armi.live_voice_text_fragments AS fragment
                   SET body=NULL,data_rights_redacted_at=statement_timestamp()
                   FROM armi.live_voice_turns AS turn
                   WHERE fragment.turn_id=turn.turn_id
                     AND turn.session_id=ANY(%s::uuid[])
                     AND fragment.data_rights_redacted_at IS NULL""",
                (list(sessions),),
            )
            await transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET final_transcript=NULL,registered_response_text=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE session_id=ANY(%s::uuid[])
                     AND data_rights_redacted_at IS NULL""",
                (list(sessions),),
            )
            await transaction.execute(
                """UPDATE armi.live_voice_sessions
                   SET state='unavailable',ended_at=COALESCE(ended_at,statement_timestamp()),
                       error_code=COALESCE(error_code,'VOICE-DATA-RIGHTS-CANCELLED')
                   WHERE session_id=ANY(%s::uuid[])
                     AND state NOT IN ('stopped','failed','unavailable')""",
                (list(sessions),),
            )
        return DataRightsApplyContribution(
            _OWNER,
            tuple(
                target
                for target in request.targets
                if target.responsible_owner == _OWNER.value
            ),
        )

    async def export(
        self,
        transaction: PostgreSQLTransaction,
        scope: DataRightsExportScope,
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        result: list[DataRightsExportSegment] = []
        for name, statement in _SEGMENTS:
            rows = await (await transaction.execute(statement)).fetchall()
            records = tuple(DataRightsCanonicalRecord(bytes(row[0])) for row in rows)
            result.append(
                DataRightsExportSegment(
                    _OWNER,
                    _VERSION,
                    name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(result)


__all__ = ("PostgreSQLLiveVoiceDataRightsParticipant",)
