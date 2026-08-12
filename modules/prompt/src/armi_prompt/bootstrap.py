"""Prompt module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import PromptApplication
from ._creator import CreatorPromptService
from ._creator_postgresql import CreatorPromptRepository
from ._postgresql import PostgreSQLPromptAdmin, PostgreSQLPromptOwner
from .api import (
    CreatorPromptPort,
    PromptAdminReferencePort,
    PromptBirthPort,
    PromptCognitionPort,
    PromptCommitPort,
    PromptReadPort,
)


@dataclass(frozen=True, slots=True)
class PromptModule:
    read: PromptReadPort
    cognition: PromptCognitionPort
    commit: PromptCommitPort
    birth: PromptBirthPort
    creator: CreatorPromptPort | None
    _owner: PostgreSQLPromptOwner
    _creator_service: CreatorPromptService | None

    async def open(self) -> None:
        await self._owner.open()
        if self._creator_service is not None:
            await self._creator_service.open()

    async def close(self) -> None:
        if self._creator_service is not None:
            await self._creator_service.close()
        await self._owner.close()


def bootstrap_prompt(
    *,
    creator_party_id: UUID | None = None,
    storage: Any = None,
    catalog: Any = None,
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory | None = None,
) -> PromptModule:
    application = PromptApplication()
    owner = PostgreSQLPromptOwner(application)
    provided = (
        creator_party_id is not None,
        storage is not None,
        catalog is not None,
        unit_of_work_factory is not None,
    )
    if any(provided) and not all(provided):
        raise ValueError("Creator Prompt dependencies must be supplied together")
    creator: CreatorPromptService | None = None
    if (
        creator_party_id is not None
        and storage is not None
        and catalog is not None
        and unit_of_work_factory is not None
    ):
        creator = CreatorPromptService(
            creator_party_id=creator_party_id,
            storage=storage,
            catalog=catalog,
            repository=CreatorPromptRepository(catalog),
            unit_of_work_factory=unit_of_work_factory,
        )
    return PromptModule(owner, application, owner, owner, creator, owner, creator)


def bootstrap_prompt_admin_reference() -> PromptAdminReferencePort:
    return PostgreSQLPromptAdmin()


__all__ = (
    "PromptModule",
    "bootstrap_prompt",
    "bootstrap_prompt_admin_reference",
)
