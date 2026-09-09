"""One lifecycle implementation for the explicitly owned local environment."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator

from .configuration import ConfigurationViolation, load_effective_config
from .configuration.models import AbsolutePath
from .runtime_errors import RuntimeViolation
from .runtime_process import LocalProcessLock, RuntimeProcessManager
from .semantic_recall_process import SemanticRecallProcessManager


class PostgreSQLControlBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    ownership: Literal["exclusive", "shared"]
    compose_file: AbsolutePath
    environment_file: AbsolutePath
    project_name: str
    service_name: str

    @field_validator("project_name", "service_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        import re

        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) is None:
            raise ValueError("LOCAL-CONTROL-SERVICE-NAME")
        return value


class LocalEnvironmentController:
    def __init__(
        self,
        *,
        environment_root: Path,
        environment_id: str,
        incarnation: int,
        defaults_path: Path,
        postgresql: PostgreSQLControlBinding | None = None,
    ) -> None:
        self.root = environment_root
        self.defaults_path = defaults_path
        self.postgresql = postgresql
        self.runtime = RuntimeProcessManager(
            environment_root, environment_id, incarnation=incarnation
        )

    def _semantic(self) -> SemanticRecallProcessManager:
        config = load_effective_config(
            defaults_path=self.defaults_path,
            environment_path=self.root / "environment.yaml",
            environment=dict(os.environ),
        ).config
        return SemanticRecallProcessManager(
            self.root, enabled=config.model.semantic_recall_enabled
        )

    def database(self, action: Literal["start", "stop", "status"]) -> dict[str, Any]:
        binding = self.postgresql
        if binding is None or binding.ownership == "shared":
            return {
                "ownership": "external" if binding is None else "shared",
                "action": "not_managed",
            }
        command = [
            "docker",
            "compose",
            "--project-name",
            binding.project_name,
            "--file",
            str(binding.compose_file),
            "--env-file",
            str(binding.environment_file),
        ]
        if action == "start":
            command.extend(["up", "--detach", "--wait", binding.service_name])
        elif action == "stop":
            command.extend(["stop", binding.service_name])
        else:
            command.extend(["ps", "--all", "--format", "json", binding.service_name])
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=120,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-UNKNOWN",
                "managed PostgreSQL outcome is unknown; query status before retrying",
            ) from None
        except FileNotFoundError:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-UNAVAILABLE",
                "managed PostgreSQL command is unavailable",
            ) from None
        if result.returncode:
            raise RuntimeViolation(
                "LOCAL-POSTGRESQL-FAILED", "managed PostgreSQL operation failed"
            )
        if action == "status":
            records: list[Any] = [
                json.loads(line)
                for line in result.stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
            if len(records) == 1 and isinstance(records[0], list):
                records = cast(list[Any], records[0])
            if any(not isinstance(item, dict) for item in records):
                raise RuntimeViolation(
                    "LOCAL-POSTGRESQL-RESPONSE", "invalid managed PostgreSQL status"
                )
            return {
                "ownership": "exclusive",
                "containers": [
                    {"state": item.get("State"), "health": item.get("Health")}
                    for item in records
                ],
            }
        return {
            "ownership": "exclusive",
            "status": "started" if action == "start" else "stopped",
        }

    def execute(
        self,
        action: Literal["start", "stop", "restart", "status"],
        *,
        component: Literal[
            "environment", "runtime", "postgresql", "semantic-recall"
        ] = "environment",
    ) -> dict[str, Any]:
        if action == "status":
            return self._execute(action, component=component)
        with LocalProcessLock(self.root / "run" / "environment-control.lock"):
            return self._execute(action, component=component)

    def _execute(
        self,
        action: Literal["start", "stop", "restart", "status"],
        *,
        component: Literal[
            "environment", "runtime", "postgresql", "semantic-recall"
        ] = "environment",
    ) -> dict[str, Any]:
        if component == "postgresql":
            if action == "restart":
                self.database("stop")
                return self.database("start")
            return self.database(action)
        if component == "runtime":
            result = getattr(self.runtime, action)()
            return self._ready(result) if action in {"start", "restart"} else result
        if component == "semantic-recall":
            semantic = self._semantic()
            if action == "restart":
                semantic.stop()
                return semantic.start()
            return getattr(semantic, action)()
        if action == "status":
            return {
                "runtime": self._observe(self.runtime.status),
                "postgresql": self._observe(lambda: self.database("status")),
                "semantic_recall": self._observe(lambda: self._semantic().status()),
            }
        if action == "restart":
            self._execute("stop")
            return self._execute("start")
        if action == "stop":
            runtime = self.runtime.stop()
            semantic = SemanticRecallProcessManager(self.root).stop()
            database = self.database("stop")
            return {
                "runtime": runtime,
                "semantic_recall": semantic,
                "postgresql": database,
            }
        database = self.database("start")
        semantic = self._semantic().start()
        runtime = self.runtime.start()
        status = self._ready(runtime)
        if status.get("status") == "not_ready":
            return {
                "status": "not_ready",
                "runtime": status,
                "semantic_recall": semantic,
                "postgresql": database,
            }
        return {
            "status": "ready",
            "runtime": runtime,
            "semantic_recall": semantic,
            "postgresql": database,
        }

    def _ready(self, started: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 120
        while True:
            status = self.runtime.status()
            if status.get("runtime", {}).get("readiness") == "ready":
                return {**started, "readiness": "ready"}
            if (
                status.get("status") not in {"running", "started"}
                or time.monotonic() >= deadline
            ):
                return {"status": "not_ready", "runtime": status}
            time.sleep(0.25)

    @staticmethod
    def _observe(read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return read()
        except (RuntimeViolation, ConfigurationViolation) as error:
            return {"status": "unavailable", "error_code": error.code}
        except OSError, ValueError, subprocess.TimeoutExpired:
            return {"status": "unavailable", "error_code": "LOCAL-CONTROL-UNAVAILABLE"}


__all__ = ("LocalEnvironmentController", "PostgreSQLControlBinding")
