"""Operator-only bootstrap composition; never invoked by Runtime startup."""

from __future__ import annotations

import asyncio
import selectors

from armi_kernel.application import (
    BirthResult,
    BirthViolation,
    CredentialPurpose,
)

from .birth import execute_birth_with_conninfo
from .birth_manifest import load_birth_manifest
from .configuration import ConfigurationViolation
from .environment import PreparedEnvironment


def execute_birth(prepared: PreparedEnvironment) -> BirthResult:
    manifest = load_birth_manifest(
        prepared.root,
        expected_environment_id=(prepared.effective.config.environment.environment_id),
    )
    locator = prepared.effective.config.secret_locators.get("database.runtime")
    if locator is None:
        raise BirthViolation("BIRTH-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.birth"),
        ) as handle:

            def invoke(value: memoryview) -> BirthResult:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise BirthViolation("BIRTH-DATABASE") from None
                return asyncio.run(
                    execute_birth_with_conninfo(prepared, manifest, conninfo),
                    loop_factory=lambda: asyncio.SelectorEventLoop(
                        selectors.SelectSelector()
                    ),
                )

            return handle.consume(invoke)
    except ConfigurationViolation:
        raise BirthViolation("BIRTH-CREDENTIAL-SCOPE") from None


__all__ = ("execute_birth",)
