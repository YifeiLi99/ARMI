"""Data-rights contribution owned by local real-time voice."""

from __future__ import annotations

from typing import LiteralString

from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
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
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "live_voice_turns",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_voice_turns AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLLiveVoiceDataRightsParticipant:
    owner_identity = _OWNER

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT session_id FROM armi.live_voice_turns
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
                """UPDATE armi.live_voice_turns
                   SET registered_response_text=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE session_id=ANY(%s::uuid[])
                     AND data_rights_redacted_at IS NULL""",
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
                    name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(result)


__all__ = ("PostgreSQLLiveVoiceDataRightsParticipant",)
