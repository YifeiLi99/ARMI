from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from armi_admin.persistence.observation_gateway import AdminObservationGateway
from armi_admin.persistence.runtime_foundation import (
    RuntimeAdminSubject,
    RuntimeFoundationAdminAdapter,
)
from armi_artifact_store.api import ArtifactAdminPort
from armi_cognition.api import CognitionAdminPort
from armi_effect.api import EffectAdminPort
from armi_expression.api import ExpressionAdminPort
from armi_interaction.api import InteractionAdminPort
from armi_material.api import (
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialAdminItem,
    MaterialAdminReadPort,
    MaterialAdminSnapshot,
    MaterialViolation,
)
from armi_mood.api import MoodAdminComponent
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLAdminUnitOfWork,
    PostgreSQLAdminUnitOfWorkFactory,
)
from armi_subject_state.api import SubjectStateAdminComponent


class _Materials:
    def __init__(self, snapshot: MaterialAdminSnapshot) -> None:
        self._snapshot = snapshot

    def private_snapshot(
        self, transaction: PostgreSQLAdminTransaction, subject_id: UUID
    ) -> MaterialAdminSnapshot:
        del transaction, subject_id
        return self._snapshot


class _BrokenMaterials:
    def private_snapshot(
        self, transaction: PostgreSQLAdminTransaction, subject_id: UUID
    ) -> MaterialAdminSnapshot:
        del transaction, subject_id
        raise MaterialViolation("MATERIAL-OBSERVATION-ARTIFACT")


class _SubjectState:
    def current_components(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]:
        del transaction, private
        return ()


class _Mood:
    def current_component(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MoodAdminComponent | None:
        del transaction, private
        return None


class _Uow:
    transaction = cast(PostgreSQLAdminTransaction, object())

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class _Factory:
    @contextmanager
    def repeatable_read(self):
        yield cast(PostgreSQLAdminUnitOfWork, _Uow())

    @contextmanager
    def serializable(self):
        yield cast(PostgreSQLAdminUnitOfWork, _Uow())


class _Runtime:
    def __init__(self, subject: tuple[Any, ...]) -> None:
        self._subject = subject

    def subject(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        for_update: bool,
        detailed: bool = False,
    ) -> RuntimeAdminSubject:
        del transaction, for_update, detailed
        return RuntimeAdminSubject(
            self._subject[0],
            self._subject[1],
            self._subject[2],
            self._subject[4],
            self._subject[3],
            self._subject[5],
        )


class _Observation(AdminObservationGateway):
    def __init__(
        self,
        *,
        subject: tuple[Any, ...],
        materials: _Materials | _BrokenMaterials,
    ) -> None:
        super().__init__(
            factory=cast(PostgreSQLAdminUnitOfWorkFactory, _Factory()),
            runtime=cast(RuntimeFoundationAdminAdapter, _Runtime(subject)),
            artifacts=cast(ArtifactAdminPort, object()),
            cognition=cast(CognitionAdminPort, object()),
            effects=cast(EffectAdminPort, object()),
            expression=cast(ExpressionAdminPort, object()),
            interaction=cast(InteractionAdminPort, object()),
            materials=cast(MaterialAdminReadPort, materials),
            mood=_Mood(),
            subject_state=_SubjectState(),
        )


def _material(
    *,
    body: str,
    privacy_status: LifeMaterialPrivacyStatus,
    deleted_at: datetime | None,
) -> MaterialAdminItem:
    occurred_at = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    return MaterialAdminItem(
        material_id=uuid7(),
        current_revision_id=uuid7(),
        material_kind=LifeMaterialKind.DIARY,
        head_version=2,
        revision_no=2,
        title="隐藏随记",
        body=body,
        metadata=(("mood", "quiet"),),
        material_status=LifeMaterialStatus.ACTIVE,
        privacy_status=privacy_status,
        artifact_id=uuid7(),
        deleted_at=deleted_at,
        created_at=occurred_at,
        updated_at=occurred_at,
    )


def test_private_subject_snapshot_observes_hidden_and_deleted_materials_only_explicitly() -> (
    None
):
    private_body = "ARMI 标记为 private 的正文"
    deleted_body = "已经 tombstone 的旧正文"
    rows = [
        _material(
            body=private_body,
            privacy_status=LifeMaterialPrivacyStatus.PRIVATE,
            deleted_at=None,
        ),
        _material(
            body=deleted_body,
            privacy_status=LifeMaterialPrivacyStatus.RESTRICTED,
            deleted_at=datetime(2026, 8, 5, 11, 0, tzinfo=UTC),
        ),
    ]
    subject_id = uuid7()
    observation = _Observation(
        subject=(subject_id, 3, 1, "alive", uuid7(), uuid7()),
        materials=_Materials(MaterialAdminSnapshot(tuple(rows), False)),
    )

    summary = observation.subject_snapshot(private=False)
    hidden = observation.subject_snapshot(private=True)

    assert "materials" not in summary
    assert private_body not in str(summary)
    assert hidden["materials_truncated"] is False
    materials = hidden["materials"]
    assert isinstance(materials, list)
    assert {item["body"] for item in materials} == {private_body, deleted_body}
    assert {item["privacy_status"] for item in materials} == {
        "private",
        "restricted",
    }
    assert any(item["deleted_at"] is not None for item in materials)


def test_private_subject_snapshot_propagates_material_owner_failure() -> None:
    observation = _Observation(
        subject=(uuid7(), 3, 1, "alive", uuid7(), uuid7()),
        materials=_BrokenMaterials(),
    )

    with pytest.raises(MaterialViolation, match="MATERIAL-OBSERVATION-ARTIFACT"):
        observation.subject_snapshot(private=True)
