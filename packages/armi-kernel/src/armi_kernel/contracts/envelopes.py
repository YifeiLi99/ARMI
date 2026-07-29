"""Command transport envelope and actor reference."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Self

from ._codec import (
    CONTRACT_VERSION,
    ContractViolation,
    require_ascii_token,
    require_contract_version,
    require_exact_fields,
    require_mapping,
)
from .ids import ActivityId, CommandId, SceneId, SubjectId, TraceId
from .values import Digest, IdempotencyKey, Instant, Purpose


@dataclass(frozen=True, slots=True)
class ActorRef:
    kind: str
    actor_id: str
    authentication: str

    def __post_init__(self) -> None:
        require_ascii_token(self.kind, path="$.kind", maximum=64, lowercase=True)
        require_ascii_token(
            self.actor_id, path="$.actor_id", maximum=128, lowercase=False
        )
        require_ascii_token(
            self.authentication,
            path="$.authentication",
            maximum=64,
            lowercase=True,
        )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire = require_mapping(value, path=path)
        require_exact_fields(
            wire,
            required=frozenset({"kind", "actor_id", "authentication"}),
            path=path,
        )
        return cls(
            require_ascii_token(
                wire["kind"], path=f"{path}.kind", maximum=64, lowercase=True
            ),
            require_ascii_token(
                wire["actor_id"],
                path=f"{path}.actor_id",
                maximum=128,
                lowercase=False,
            ),
            require_ascii_token(
                wire["authentication"],
                path=f"{path}.authentication",
                maximum=64,
                lowercase=True,
            ),
        )

    def to_wire(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "actor_id": self.actor_id,
            "authentication": self.authentication,
        }


@dataclass(frozen=True, slots=True)
class CommandEnvelope[PayloadT]:
    command_id: CommandId
    idempotency_key: IdempotencyKey
    request_digest: Digest
    actor: ActorRef
    subject_id: SubjectId
    purpose: Purpose
    requested_at: Instant
    trace_id: TraceId
    payload: PayloadT
    scene_id: SceneId | None = None
    activity_id: ActivityId | None = None

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        payload_decoder: Callable[[object], PayloadT],
        path: str = "$",
    ) -> Self:
        wire = require_mapping(value, path=path)
        require_exact_fields(
            wire,
            required=frozenset(
                {
                    "contract_version",
                    "command_id",
                    "idempotency_key",
                    "request_digest",
                    "actor",
                    "subject_id",
                    "purpose",
                    "requested_at",
                    "trace_id",
                    "payload",
                }
            ),
            optional=frozenset({"scene_id", "activity_id"}),
            path=path,
        )
        require_contract_version(
            wire["contract_version"], path=f"{path}.contract_version"
        )
        try:
            payload = payload_decoder(wire["payload"])
        except ContractViolation:
            raise
        except Exception as error:
            raise ContractViolation(
                "CON-PAYLOAD",
                "payload decoder rejected the command body",
                path=f"{path}.payload",
            ) from error
        return cls(
            command_id=CommandId.from_wire(
                wire["command_id"], path=f"{path}.command_id"
            ),
            idempotency_key=IdempotencyKey.from_wire(
                wire["idempotency_key"], path=f"{path}.idempotency_key"
            ),
            request_digest=Digest.from_wire(
                wire["request_digest"], path=f"{path}.request_digest"
            ),
            actor=ActorRef.from_wire(wire["actor"], path=f"{path}.actor"),
            subject_id=SubjectId.from_wire(
                wire["subject_id"], path=f"{path}.subject_id"
            ),
            scene_id=(
                SceneId.from_wire(wire["scene_id"], path=f"{path}.scene_id")
                if "scene_id" in wire
                else None
            ),
            activity_id=(
                ActivityId.from_wire(wire["activity_id"], path=f"{path}.activity_id")
                if "activity_id" in wire
                else None
            ),
            purpose=Purpose.from_wire(wire["purpose"], path=f"{path}.purpose"),
            requested_at=Instant.from_wire(
                wire["requested_at"], path=f"{path}.requested_at"
            ),
            trace_id=TraceId.from_wire(wire["trace_id"], path=f"{path}.trace_id"),
            payload=payload,
        )

    def to_wire(
        self, *, payload_encoder: Callable[[PayloadT], Mapping[str, object]]
    ) -> dict[str, object]:
        payload = require_mapping(payload_encoder(self.payload), path="$.payload")
        wire: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "command_id": self.command_id.to_wire(),
            "idempotency_key": self.idempotency_key.to_wire(),
            "request_digest": self.request_digest.to_wire(),
            "actor": self.actor.to_wire(),
            "subject_id": self.subject_id.to_wire(),
            "purpose": self.purpose.to_wire(),
            "requested_at": self.requested_at.to_wire(),
            "trace_id": self.trace_id.to_wire(),
            "payload": dict(payload),
        }
        if self.scene_id is not None:
            wire["scene_id"] = self.scene_id.to_wire()
        if self.activity_id is not None:
            wire["activity_id"] = self.activity_id.to_wire()
        return wire
