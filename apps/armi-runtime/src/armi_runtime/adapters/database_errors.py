"""Stable, redacted database boundary failures."""

from __future__ import annotations

from dataclasses import dataclass

KNOWN_DATABASE_CODES = frozenset(
    {
        "DB-CONNECTION-UNAVAILABLE",
        "DB-PG-VERSION",
        "DB-DATABASE-IDENTITY",
        "DB-RUNTIME-ROLE-UNSAFE",
        "DB-SCHEMA-DIRTY",
        "DB-SCHEMA-EXISTS",
        "DB-SCHEMA-INSTALL-FAILED",
        "DB-SCHEMA-MISSING",
        "DB-SCHEMA-INVARIANT",
        "DB-SCHEMA-LOCK",
        "DB-SCHEMA-RESOURCE",
        "DB-ROLE-IDENTITY",
        "DB-ROLE-ATTRIBUTES",
        "DB-ROLE-MEMBERSHIP",
        "DB-ROLE-GRANT",
        "DB-ROLE-OWNER",
        "DB-ROLE-SEARCH-PATH",
        "DB-ROLE-SESSION-DIRTY",
        "DB-ROLE-PUBLIC-PRIVILEGE",
        "DB-ROLE-SECURITY-DEFINER",
        "DB-ROLE-CREDENTIAL-SCOPE",
    }
)


@dataclass(slots=True)
class DatabaseViolation(RuntimeError):
    code: str
    message: str
    status: str = "failed"
    exit_code: int = 4

    def __post_init__(self) -> None:
        if self.code not in KNOWN_DATABASE_CODES:
            raise ValueError("database failure code is not registered")

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


__all__ = ("KNOWN_DATABASE_CODES", "DatabaseViolation")
