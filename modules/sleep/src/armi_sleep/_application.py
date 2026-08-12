"""Sleep cognition boundary implementation."""

from __future__ import annotations

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from . import _codec
from .api import CandidateMaintenanceDecisionDraft, CandidateSleepDecisionDraft


class SleepApplication:
    def bind_sleep(self, value: CandidateSleepDecisionDraft) -> CandidateOwnerDraft:
        return _owner(value, _codec.encode(value))

    def bind_maintenance(
        self, value: CandidateMaintenanceDecisionDraft
    ) -> CandidateOwnerDraft:
        return _owner(value, _codec.encode(value))

    def decode(
        self, payload: bytes
    ) -> CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft:
        return _codec.decode(payload)

    def bind_legacy(self, value: object, *, maintenance: bool) -> CandidateOwnerDraft:
        decoded = _codec.decode_legacy(value, maintenance=maintenance)
        return _owner(decoded, _codec.encode(decoded))


def _owner(
    value: CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft,
    payload: bytes,
) -> CandidateOwnerDraft:
    return CandidateOwnerDraft(
        value.proposal_ref,
        value.atomic_group_ref,
        value.basis_ordinals,
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        "sleep",
        payload,
    )


__all__ = ("SleepApplication",)
