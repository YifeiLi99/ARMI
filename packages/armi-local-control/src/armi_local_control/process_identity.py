"""Exact managed-process identity shared by local Runtime-owned services."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import psutil


class ManagedProcessState(StrEnum):
    MATCHES = "matches"
    ABSENT = "absent"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ManagedProcessIdentity:
    pid: int
    creation_time_microseconds: int
    executable_identity: str
    command_identity: str
    environment_identity: str
    incarnation: int
    runtime_instance_id: str | None = None

    @classmethod
    def capture(
        cls,
        pid: int,
        *,
        environment_identity: str,
        incarnation: int,
        runtime_instance_id: str | None = None,
    ) -> ManagedProcessIdentity:
        process = psutil.Process(pid)
        executable = os.path.normcase(
            os.fspath(Path(process.exe()).resolve(strict=True))
        )
        command = json.dumps(
            process.cmdline(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return cls(
            pid=pid,
            creation_time_microseconds=round(process.create_time() * 1_000_000),
            executable_identity=executable,
            command_identity=f"sha256:{hashlib.sha256(command).hexdigest()}",
            environment_identity=environment_identity,
            incarnation=incarnation,
            runtime_instance_id=runtime_instance_id,
        )

    @classmethod
    def from_wire(cls, value: object) -> ManagedProcessIdentity:
        if type(value) is not dict:
            raise ValueError("managed process identity is invalid")
        data = cast(dict[str, object], value)
        if set(data) != {
            "pid",
            "creation_time_microseconds",
            "executable_identity",
            "command_identity",
            "environment_identity",
            "incarnation",
            "runtime_instance_id",
        }:
            raise ValueError("managed process identity is invalid")
        pid = data["pid"]
        creation_time = data["creation_time_microseconds"]
        executable = data["executable_identity"]
        command = data["command_identity"]
        environment = data["environment_identity"]
        incarnation = data["incarnation"]
        runtime_instance = data["runtime_instance_id"]
        if (
            type(pid) is not int
            or type(creation_time) is not int
            or type(executable) is not str
            or type(command) is not str
            or type(environment) is not str
            or type(incarnation) is not int
            or (runtime_instance is not None and type(runtime_instance) is not str)
        ):
            raise ValueError("managed process identity is invalid")
        identity = cls(
            pid,
            creation_time,
            executable,
            command,
            environment,
            incarnation,
            runtime_instance,
        )
        identity._validate()
        return identity

    def to_wire(self) -> dict[str, object]:
        self._validate()
        return {
            "pid": self.pid,
            "creation_time_microseconds": self.creation_time_microseconds,
            "executable_identity": self.executable_identity,
            "command_identity": self.command_identity,
            "environment_identity": self.environment_identity,
            "incarnation": self.incarnation,
            "runtime_instance_id": self.runtime_instance_id,
        }

    def inspect(self) -> ManagedProcessState:
        try:
            observed = ManagedProcessIdentity.capture(
                self.pid,
                environment_identity=self.environment_identity,
                incarnation=self.incarnation,
                runtime_instance_id=self.runtime_instance_id,
            )
        except psutil.NoSuchProcess:
            return ManagedProcessState.ABSENT
        except psutil.AccessDenied, OSError:
            return ManagedProcessState.UNAVAILABLE
        return (
            ManagedProcessState.MATCHES
            if observed == self
            else ManagedProcessState.MISMATCH
        )

    def _validate(self) -> None:
        if (
            type(self.pid) is not int
            or self.pid < 1
            or type(self.creation_time_microseconds) is not int
            or self.creation_time_microseconds < 1
            or type(self.executable_identity) is not str
            or not self.executable_identity
            or type(self.command_identity) is not str
            or len(self.command_identity) != 71
            or not self.command_identity.startswith("sha256:")
            or type(self.environment_identity) is not str
            or not self.environment_identity
            or type(self.incarnation) is not int
            or self.incarnation < 1
            or (
                self.runtime_instance_id is not None
                and type(self.runtime_instance_id) is not str
            )
        ):
            raise ValueError("managed process identity is invalid")


__all__ = ("ManagedProcessIdentity", "ManagedProcessState")
