"""Non-Store updates: discover on GitHub, verify locally, deploy with Windows."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from armi_kernel import load_yaml_mapping
from armi_kernel.application import record_diagnostic
from armi_local_control import private_directory, write_control
from armi_local_control.runtime_process import LocalProcessLock
from armi_local_control.windows_package import (
    data_root,
    defer_update,
    deployment_status,
    inspect_candidate,
    package_identity,
    restart_update,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .distribution import BundleDatabase, ProgramBundle

UpdateAction = Literal["status", "check", "prepare", "apply", "automatic"]


class UpdateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_kind: Literal["armi.update"]
    name: str
    publisher: str
    version: str
    architecture: Literal["x64"]
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0, le=4 * 1024**3)
    database: BundleDatabase

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        version_parts(value)
        return value

    @field_validator("url")
    @classmethod
    def _origin(cls, value: str) -> str:
        uri = urlsplit(value)
        if (
            uri.scheme != "https"
            or uri.netloc != "github.com"
            or uri.query
            or uri.fragment
            or not uri.path.startswith("/YifeiLi99/ARMI/releases/download/")
            or not uri.path.endswith(".msix")
        ):
            raise ValueError("UPDATE-DOWNLOAD-ORIGIN")
        return value


class UpdateState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_kind: Literal["armi.update-state"] = "armi.update-state"
    automatic: bool = True
    checked_at: float | None = None
    phase: Literal[
        "idle",
        "available",
        "incompatible",
        "downloaded",
        "deployment_requested",
        "registration_deferred",
        "deployed",
        "failed",
    ] = "idle"
    candidate: UpdateManifest | None = None
    error_code: str | None = None


def version_parts(value: str) -> tuple[int, ...]:
    parts = value.split(".")
    if len(parts) != 4 or any(
        not part.isascii()
        or not part.isdecimal()
        or str(int(part)) != part
        or int(part) > 65535
        for part in parts
    ):
        raise ValueError("UPDATE-VERSION")
    return tuple(int(part) for part in parts)


class UpdateApplication:
    def __init__(self, stop_environments: Callable[[], None]) -> None:
        self.stop_environments = stop_environments

    def execute(
        self, action: UpdateAction, enabled: bool | None = None
    ) -> dict[str, Any]:
        identity = package_identity()
        root = data_root()
        if identity is None or root is None:
            return {"status": "unavailable", "error_code": "UPDATE-MSIX-REQUIRED"}
        control = root / "control/update"
        private_directory(control)
        state_path = control / "state.json"
        with LocalProcessLock(control / "update.lock"):
            state = (
                UpdateState.model_validate_json(state_path.read_bytes())
                if state_path.exists()
                else UpdateState()
            )
            actual = deployment_status()
            current = actual["version"]
            previous_phase = state.phase
            if state.candidate and version_parts(current) >= version_parts(
                state.candidate.version
            ):
                state.phase = "deployed"
                state.error_code = None
                self._discard_download(root, state.candidate.version)
            try:
                if action == "automatic":
                    if enabled is None:
                        raise ValueError("UPDATE-AUTOMATIC-VALUE-REQUIRED")
                    state.automatic = enabled
                elif action == "check":
                    # An unresolved deployment must first be reconciled against Windows.
                    if state.phase not in {
                        "deployment_requested",
                        "registration_deferred",
                    }:
                        state.checked_at = time.time()
                        release = load_yaml_mapping(
                            (
                                identity.program_root / "resources/windows-release.yaml"
                            ).read_bytes()
                        )
                        repository = release["repository"]
                        if repository != "YifeiLi99/ARMI":
                            raise ValueError("UPDATE-RELEASE-ORIGIN")
                        with (
                            httpx.Client(timeout=30, follow_redirects=True) as client,
                            client.stream(
                                "GET",
                                f"https://github.com/{repository}/releases/latest/download/armi-update.json",
                            ) as response,
                        ):
                            response.raise_for_status()
                            raw = bytearray()
                            for block in response.iter_bytes():
                                raw.extend(block)
                                if len(raw) > 65536:
                                    raise ValueError("UPDATE-MANIFEST-SIZE")
                        candidate = UpdateManifest.model_validate_json(bytes(raw))
                        if (
                            candidate.name != identity.name
                            or candidate.publisher != identity.publisher
                        ):
                            raise ValueError("UPDATE-PACKAGE-IDENTITY")
                        if (
                            state.candidate
                            and state.candidate.version != candidate.version
                        ):
                            self._discard_download(root, state.candidate.version)
                        state.candidate = candidate
                        if version_parts(candidate.version) <= version_parts(current):
                            state.phase = "idle"
                        elif (
                            candidate.database
                            != ProgramBundle.read(identity.program_root).database
                        ):
                            state.phase = "incompatible"
                        else:
                            state.phase = "available"
                        state.error_code = None
                elif action in {"prepare", "apply"}:
                    candidate = state.candidate
                    if candidate is None or state.phase in {
                        "idle",
                        "incompatible",
                        "deployed",
                    }:
                        raise ValueError("UPDATE-COMPATIBLE-CANDIDATE-REQUIRED")
                    if state.phase == "deployment_requested":
                        raise ValueError("UPDATE-DEPLOYMENT-OUTCOME-UNKNOWN")
                    destination = root / "tmp/update" / (candidate.version + ".msix")
                    private_directory(destination.parent)
                    if state.phase not in {"downloaded", "registration_deferred"}:
                        self._download(candidate, destination)
                        state.phase = "downloaded"
                        write_control(state_path, state.model_dump(mode="json"))
                    verified = inspect_candidate(destination)
                    if (
                        verified["version"] != candidate.version
                        or BundleDatabase.model_validate(verified["database"])
                        != candidate.database
                    ):
                        raise ValueError("UPDATE-SIGNED-CONTRACT-MISMATCH")
                    if action == "apply":
                        self.stop_environments()
                    elif state.phase == "registration_deferred":
                        return self._result(state, actual)
                    state.phase = "deployment_requested"
                    write_control(state_path, state.model_dump(mode="json"))
                    result = (
                        restart_update(destination)
                        if action == "apply"
                        else defer_update(destination)
                    )
                    state.phase = result["status"]
                    state.error_code = None
            except httpx.HTTPError as error:
                record_diagnostic(
                    "update.failed",
                    component="setup",
                    level=logging.ERROR,
                    error=error,
                    action=action,
                )
                state.error_code = "UPDATE-NETWORK-FAILED"
                if state.phase not in {"deployment_requested", "registration_deferred"}:
                    state.phase = "failed"
            except (OSError, ValueError, RuntimeError) as error:
                record_diagnostic(
                    "update.failed",
                    component="setup",
                    level=logging.ERROR,
                    error=error,
                    action=action,
                )
                state.error_code = (
                    str(error)
                    if str(error).startswith(("UPDATE-", "MSIX-"))
                    else "UPDATE-OPERATION-FAILED"
                )
                if state.phase not in {"deployment_requested", "registration_deferred"}:
                    state.phase = "failed"
            write_control(state_path, state.model_dump(mode="json"))
            if state.phase == "deployed" and previous_phase != "deployed":
                record_diagnostic(
                    "update.deployed",
                    component="setup",
                    version=current,
                    phase="deployed",
                )
            record_diagnostic(
                "update.phase.completed",
                component="setup",
                action=action,
                phase=state.phase,
                version=current,
                result_code=state.error_code,
            )
            return self._result(state, actual)

    @staticmethod
    def _discard_download(root: Path, version: str) -> None:
        # The version comes from the validated state, not a path supplied by a server.
        directory = root / "tmp/update"
        for suffix in (".msix", ".partial"):
            (directory / (version + suffix)).unlink(missing_ok=True)

    @staticmethod
    def _result(state: UpdateState, actual: dict[str, Any]) -> dict[str, Any]:
        return {
            **state.model_dump(mode="json"),
            "status": state.phase,
            "installed_version": actual["version"],
            "deployment_in_progress": actual["deployment_in_progress"],
            "deployment_verified": state.phase == "deployed",
        }

    @staticmethod
    def _download(candidate: UpdateManifest, destination: Path) -> None:
        pending = destination.with_suffix(".partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with (
                httpx.Client(timeout=60, follow_redirects=True) as client,
                client.stream("GET", candidate.url) as response,
                pending.open("wb") as output,
            ):
                response.raise_for_status()
                for block in response.iter_bytes(1024 * 1024):
                    size += len(block)
                    if size > candidate.size:
                        raise ValueError("UPDATE-DOWNLOAD-SIZE")
                    digest.update(block)
                    output.write(block)
            if size != candidate.size or digest.hexdigest() != candidate.sha256:
                raise ValueError("UPDATE-DOWNLOAD-DIGEST")
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
