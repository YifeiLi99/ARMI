"""Transport-independent setup requests and application dispatch."""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Literal

from armi_kernel.application import PersonalityAnchor
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.windows_package import WindowsPackageError
from pydantic import BaseModel, ConfigDict, Field

from .installation import (
    SetupApplication,
    SetupCredentialRequest,
    SetupError,
    SetupNapcatRequest,
)
from .updates import UpdateAction


class SetupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: UpdateAction
    enabled: bool | None = None


class SetupAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["armi.personality-anchor.v1"]
    voice_style: str
    traits: list[str] = Field(min_length=1, max_length=8)

    def domain(self) -> PersonalityAnchor:
        return PersonalityAnchor(
            self.schema_version, self.voice_style, tuple(self.traits)
        )


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "status",
        "check",
        "prepare",
        "birth",
        "credential",
        "login_startup",
        "admin",
        "update",
        "uninstall",
        "napcat",
    ]
    enabled: bool | None = None
    delete_data: bool = False
    update: SetupUpdateRequest | None = None
    napcat: SetupNapcatRequest | None = None
    credential: SetupCredentialRequest | None = None
    personality_anchor: SetupAnchor | None = None
    operation_id: str | None = None
    operation: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def _diagnostic(error: Exception) -> dict[str, Any]:
    """Code locations and OS numbers are safe; messages and locals are not."""
    cause = error.__context__
    return {
        "type": type(error).__name__,
        "winerror": getattr(cause if cause is not None else error, "winerror", None),
        "frames": [
            {
                "file": Path(frame.filename).name,
                "line": frame.lineno,
                "function": frame.name,
            }
            for frame in traceback.extract_tb(
                (cause if cause is not None else error).__traceback__
            )
        ],
    }


def dispatch(application: SetupApplication, request: SetupRequest) -> dict[str, Any]:
    try:
        if request.action == "status":
            return application.status()
        if request.action == "check":
            return application.check()
        if request.action == "prepare":
            if request.operation_id is None:
                raise SetupError("SETUP-OPERATION-ID-REQUIRED")
            return application.prepare(operation_id=request.operation_id)
        if request.action == "birth":
            if request.personality_anchor is None:
                raise SetupError("SETUP-PERSONALITY-ANCHOR-REQUIRED")
            return application.birth(request.personality_anchor.domain())
        if request.action == "credential":
            if request.credential is None:
                raise SetupError("SETUP-CREDENTIAL-REQUEST-REQUIRED")
            return application.credential(request.credential)
        if request.action == "login_startup":
            return application.login_startup(request.enabled)
        if request.action == "update":
            if request.update is None:
                raise SetupError("UPDATE-REQUEST-REQUIRED")
            return application.update(request.update.action, request.update.enabled)
        if request.action == "uninstall":
            return application.uninstall(delete_data=request.delete_data)
        if request.action == "napcat":
            if request.napcat is None:
                raise SetupError("NAPCAT-REQUEST-REQUIRED")
            return application.napcat(request.napcat)
        if request.operation is None:
            raise SetupError("SETUP-ADMIN-OPERATION-REQUIRED")
        return application.invoke(request.operation, request.arguments)
    except SetupError as error:
        return {"status": "failed", "error_code": str(error)}
    except WindowsPackageError as error:
        return {"status": "failed", "error_code": str(error)}
    except RuntimeViolation as error:
        return {
            "status": "failed",
            "error_code": error.code,
            "diagnostic": _diagnostic(error),
        }
    except Exception as error:
        # Pydantic and provider exceptions can contain submitted credentials.
        # Report code locations only, never exception messages or local values.
        return {
            "status": "failed",
            "error_code": "SETUP-OPERATION-FAILED",
            "diagnostic": _diagnostic(error),
        }


__all__ = ("SetupAnchor", "SetupRequest", "SetupUpdateRequest", "dispatch")
