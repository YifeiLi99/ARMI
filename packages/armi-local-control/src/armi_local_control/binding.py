"""Explicit Creator-delegate bindings for local machine interaction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self, cast
from urllib.parse import urlsplit
from uuid import UUID

from armi_kernel import load_yaml_mapping
from armi_kernel.application import CredentialPurpose
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .configuration import EnvironmentFileCredentialPort
from .configuration.models import AbsolutePath, LocatorValue, Uuid7
from .configuration.paths import has_reparse_point


class DelegateBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delegate_id: Uuid7
    creator_party_id: Uuid7
    credential_locator: LocatorValue
    scopes: tuple[Literal["interaction.read", "interaction.write"], ...]

    @field_validator("scopes", mode="before")
    @classmethod
    def parse_scopes(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if not self.scopes or len(self.scopes) != len(set(self.scopes)):
            raise ValueError("INTERACTION-BINDING-SCOPES")
        if self.credential_locator.scheme not in {"file", "env"}:
            raise ValueError("INTERACTION-BINDING-CREDENTIAL")
        return self


class InteractionAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["armi.interaction-access.v1"]
    environment_id: Uuid7
    delegates: tuple[DelegateBinding, ...] = Field(min_length=1)

    @field_validator("delegates", mode="before")
    @classmethod
    def parse_delegates(cls, value: object) -> object:
        return tuple(cast(list[object], value)) if isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_delegates(self) -> Self:
        if len({item.delegate_id for item in self.delegates}) != len(self.delegates):
            raise ValueError("INTERACTION-BINDING-DUPLICATE")
        return self


class InteractionClientBinding(DelegateBinding):
    schema_version: Literal["armi.interaction-client.v1"]
    environment_id: Uuid7
    environment_root: AbsolutePath
    endpoint: str

    @field_validator("endpoint")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username is not None
            or url.password is not None
            or url.port is None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("INTERACTION-BINDING-ENDPOINT")
        return value.rstrip("/")


def read_binding(path: Path) -> dict[str, object]:
    if (
        not path.is_absolute()
        or not path.is_file()
        or has_reparse_point(path, root=path.parent)
        or path.stat().st_size > 65_536
    ):
        raise ValueError("INTERACTION-BINDING-FILE")
    return load_yaml_mapping(path.read_bytes())


def load_client_binding(path: Path | None = None) -> InteractionClientBinding:
    configured = os.environ.get("ARMI_CLIENT_CONFIG")
    if path is None and not configured:
        raise ValueError("INTERACTION-CLIENT-CONFIG-REQUIRED")
    return InteractionClientBinding.model_validate(
        read_binding(path if path is not None else Path(str(configured)))
    )


def binding_secret(binding: DelegateBinding, environment_root: Path) -> bytes:
    credentials = EnvironmentFileCredentialPort(
        environment=dict(os.environ), secret_roots=(environment_root / "secrets",)
    )
    with credentials.resolve(
        binding.credential_locator, CredentialPurpose("interaction.authenticate")
    ) as handle:
        return handle.consume(bytes)


class AuthenticatedDelegate(BaseModel):
    """Server-created provenance; never deserialized from a request body."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment_id: UUID
    creator_party_id: UUID
    delegate_id: UUID
    scopes: tuple[str, ...]
    default_scene_key: str = "default"


__all__ = (
    "AuthenticatedDelegate",
    "DelegateBinding",
    "InteractionAccess",
    "InteractionClientBinding",
    "binding_secret",
    "load_client_binding",
    "read_binding",
)
