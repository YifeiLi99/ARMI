"""Stable owner-participant contracts for data-rights workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactId, ArtifactRef
from armi_runtime_foundation import PostgreSQLTransaction

_TOKEN = re.compile(r"^[a-z][a-z0-9-]{0,63}$", re.ASCII)
_SEGMENT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$", re.ASCII)

DATA_RIGHTS_TARGET_KINDS = frozenset(
    {
        "party",
        "external_binding",
        "scene",
        "interaction",
        "media_recognition",
        "live_voice",
        "evidence",
        "experience",
        "cognition",
        "memory",
        "relationship",
        "activity",
        "material",
        "subject_component",
        "mood",
        "prompt",
        "effect",
        "web_research",
        "codex_task",
        "managed_snapshot",
        "artifact",
    }
)
DATA_RIGHTS_ACTIONS = frozenset(
    {
        "block",
        "restrict",
        "cancel",
        "redact",
        "tombstone",
        "delete",
        "retain",
        "operator_remove",
    }
)
DATA_RIGHTS_RETENTION_REASONS = frozenset(
    {
        "rights_enforcement",
        "shared_reference",
        "objective_history",
        "subject_continuity",
        "operator_managed_snapshot",
    }
)


class DataRightsParticipantViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if not code.startswith("DATA-RIGHTS-PARTICIPANT-"):
            raise ValueError("participant violation code is invalid")
        self.code = code
        super().__init__("data-rights participant failed")


@dataclass(frozen=True, slots=True)
class DataRightsOwnerIdentity:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _TOKEN.fullmatch(self.value) is None:
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-OWNER")


@dataclass(frozen=True, slots=True)
class DataRightsContributionVersion:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-VERSION")


@dataclass(frozen=True, slots=True)
class DataRightsRelatedRef:
    kind: str
    ref: UUID

    def __post_init__(self) -> None:
        if (
            _TOKEN.fullmatch(self.kind) is None
            or type(self.ref) is not UUID
            or self.ref.version != 7
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-RELATED")


@dataclass(frozen=True, slots=True)
class DataRightsTargetRef:
    kind: str
    ref: UUID
    required_action: str
    retention_reason: str | None = None
    responsible_owner: str | None = None

    def __post_init__(self) -> None:
        if (
            self.kind not in DATA_RIGHTS_TARGET_KINDS
            or type(self.ref) is not UUID
            or self.ref.version != 7
            or self.required_action not in DATA_RIGHTS_ACTIONS
            or self.retention_reason not in {None, *DATA_RIGHTS_RETENTION_REASONS}
            or (
                self.responsible_owner is not None
                and _TOKEN.fullmatch(self.responsible_owner) is None
            )
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-TARGET")


@dataclass(frozen=True, slots=True)
class DataRightsArtifactUsage:
    artifact_id: ArtifactId
    total_reference_count: int
    target_party_reference_count: int

    def __post_init__(self) -> None:
        if (
            type(self.artifact_id) is not ArtifactId
            or type(self.total_reference_count) is not int
            or type(self.target_party_reference_count) is not int
            or self.total_reference_count < 0
            or self.target_party_reference_count < 0
            or self.target_party_reference_count > self.total_reference_count
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-ARTIFACT")


@dataclass(frozen=True, slots=True)
class DataRightsDiscoveryRequest:
    order_id: UUID
    party_id: UUID
    related_refs: tuple[DataRightsRelatedRef, ...]
    order_kind: str = "delete_related"

    def __post_init__(self) -> None:
        if (
            type(self.order_id) is not UUID
            or self.order_id.version != 7
            or type(self.party_id) is not UUID
            or self.party_id.version != 7
            or any(type(item) is not DataRightsRelatedRef for item in self.related_refs)
            or self.order_kind not in {"stop_contact", "stop_use", "delete_related"}
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-DISCOVERY")


@dataclass(frozen=True, slots=True)
class DataRightsDiscoveryContribution:
    owner_identity: DataRightsOwnerIdentity
    related_refs: tuple[DataRightsRelatedRef, ...] = ()
    targets: tuple[DataRightsTargetRef, ...] = ()
    artifact_usages: tuple[DataRightsArtifactUsage, ...] = ()


@dataclass(frozen=True, slots=True)
class DataRightsArtifactField:
    table_name: str
    column_name: str
    classification: str

    def __post_init__(self) -> None:
        if (
            _SEGMENT.fullmatch(self.table_name) is None
            or _SEGMENT.fullmatch(self.column_name) is None
            or self.classification not in {"party", "shared", "objective", "continuity"}
        ):
            raise DataRightsParticipantViolation(
                "DATA-RIGHTS-PARTICIPANT-ARTIFACT-FIELD"
            )


@dataclass(frozen=True, slots=True)
class DataRightsContentField:
    table_name: str
    column_name: str
    treatment: str

    def __post_init__(self) -> None:
        if (
            _SEGMENT.fullmatch(self.table_name) is None
            or _SEGMENT.fullmatch(self.column_name) is None
            or self.treatment not in {"redact", "retain_objective", "retain_continuity"}
        ):
            raise DataRightsParticipantViolation(
                "DATA-RIGHTS-PARTICIPANT-CONTENT-FIELD"
            )


@dataclass(frozen=True, slots=True)
class DataRightsOwnerContract:
    owner_identity: DataRightsOwnerIdentity
    consumes: frozenset[str] = frozenset()
    produces: frozenset[str] = frozenset()
    owns: frozenset[str] = frozenset()
    artifact_fields: tuple[DataRightsArtifactField, ...] = ()
    content_fields: tuple[DataRightsContentField, ...] = ()

    def __post_init__(self) -> None:
        if (
            any(
                _TOKEN.fullmatch(value) is None
                for value in self.consumes | self.produces
            )
            or not self.owns.issubset(DATA_RIGHTS_TARGET_KINDS)
            or any(
                type(item) is not DataRightsArtifactField
                for item in self.artifact_fields
            )
            or any(
                type(item) is not DataRightsContentField for item in self.content_fields
            )
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-CONTRACT")


@dataclass(frozen=True, slots=True)
class DataRightsApplyRequest:
    order_id: UUID
    party_id: UUID
    order_kind: str
    related_refs: tuple[DataRightsRelatedRef, ...]
    targets: tuple[DataRightsTargetRef, ...]
    exclusive_artifact_ids: tuple[ArtifactId, ...]

    def __post_init__(self) -> None:
        if self.order_kind not in {"stop_contact", "stop_use", "delete_related"}:
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-APPLY")


@dataclass(frozen=True, slots=True)
class DataRightsApplyContribution:
    owner_identity: DataRightsOwnerIdentity
    targets: tuple[DataRightsTargetRef, ...] = ()


@dataclass(frozen=True, slots=True)
class DataRightsExportScope:
    creator_party_id: UUID


@dataclass(frozen=True, slots=True)
class DataRightsCanonicalRecord:
    value: bytes

    def __post_init__(self) -> None:
        if type(self.value) is not bytes or not self.value.endswith(b"\n"):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-RECORD")


@runtime_checkable
class DataRightsRecordBatchStream(Protocol):
    async def read_batch(self) -> tuple[DataRightsCanonicalRecord, ...]: ...


class DataRightsTupleRecordStream:
    __slots__ = ("_read", "_records")

    def __init__(self, records: tuple[DataRightsCanonicalRecord, ...]) -> None:
        self._records = records
        self._read = False

    async def read_batch(self) -> tuple[DataRightsCanonicalRecord, ...]:
        if self._read:
            return ()
        self._read = True
        return self._records


@dataclass(frozen=True, slots=True)
class DataRightsExportSegment:
    owner_identity: DataRightsOwnerIdentity
    schema_version: DataRightsContributionVersion
    segment_name: str
    media_type: str
    records: DataRightsRecordBatchStream
    artifact_refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        if (
            _SEGMENT.fullmatch(self.segment_name) is None
            or self.media_type != "application/x-ndjson"
        ):
            raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-SEGMENT")


@runtime_checkable
class DataRightsParticipant(Protocol):
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity: ...

    @property
    def schema_version(self) -> DataRightsContributionVersion: ...

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution: ...

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution: ...

    async def export(
        self,
        transaction: PostgreSQLTransaction,
        scope: DataRightsExportScope,
    ) -> tuple[DataRightsExportSegment, ...]: ...


@runtime_checkable
class DataRightsVisibilityPort(Protocol):
    async def party_restrictions(
        self, transaction: PostgreSQLTransaction, party_id: UUID
    ) -> frozenset[str]: ...

    async def hidden_targets(
        self,
        transaction: PostgreSQLTransaction,
        *,
        target_kind: str,
        target_refs: tuple[UUID, ...],
    ) -> frozenset[UUID]: ...


class EmptyDataRightsParticipant:
    __slots__ = ("_contract", "_owner", "_version")

    def __init__(self, owner_identity: str) -> None:
        self._owner = DataRightsOwnerIdentity(owner_identity)
        self._version = DataRightsContributionVersion(1)
        self._contract = DataRightsOwnerContract(self._owner)

    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return self._owner

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return self._version

    @property
    def data_rights_contract(self) -> DataRightsOwnerContract:
        return self._contract

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(self._owner)

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        del transaction
        return DataRightsApplyContribution(
            self._owner,
            tuple(
                target
                for target in request.targets
                if target.responsible_owner == self._owner.value
            ),
        )

    async def export(
        self,
        transaction: PostgreSQLTransaction,
        scope: DataRightsExportScope,
    ) -> tuple[DataRightsExportSegment, ...]:
        del transaction, scope
        return ()


__all__ = (
    "DATA_RIGHTS_ACTIONS",
    "DATA_RIGHTS_RETENTION_REASONS",
    "DATA_RIGHTS_TARGET_KINDS",
    "DataRightsApplyContribution",
    "DataRightsApplyRequest",
    "DataRightsArtifactField",
    "DataRightsArtifactUsage",
    "DataRightsCanonicalRecord",
    "DataRightsContentField",
    "DataRightsContributionVersion",
    "DataRightsDiscoveryContribution",
    "DataRightsDiscoveryRequest",
    "DataRightsExportScope",
    "DataRightsExportSegment",
    "DataRightsOwnerContract",
    "DataRightsOwnerIdentity",
    "DataRightsParticipant",
    "DataRightsParticipantViolation",
    "DataRightsRecordBatchStream",
    "DataRightsRelatedRef",
    "DataRightsTargetRef",
    "DataRightsTupleRecordStream",
    "DataRightsVisibilityPort",
    "EmptyDataRightsParticipant",
)
