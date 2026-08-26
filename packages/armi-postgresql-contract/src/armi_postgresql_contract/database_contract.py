"""Single read-only proof for an installed ARMI PostgreSQL environment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog_fingerprint import database_catalog_digest
from .schema_resources import (
    BASELINE_IDENTITY,
    EXPECTED_REVISION,
    role_policy_digest,
    schema_resource_digest,
    schema_resource_root,
)

_EXPECTED_EXTENSIONS = (
    ("pg_trgm", "1.6", "armi_extensions"),
    ("vector", "0.8.6", "armi_extensions"),
)


class PostgreSQLContractError(RuntimeError):
    """The live database cannot prove the packaged machine contract."""


@dataclass(frozen=True, slots=True)
class PostgreSQLContractEvidence:
    server_version_num: int
    encoding: str
    timezone: str
    locale_provider: str
    locale: str
    extensions: tuple[tuple[str, str, str], ...]
    revision: str
    baseline_identity: str
    resource_digest: str
    catalog_digest: str
    role_policy_digest: str
    table_count: int


def verify_postgresql_contract(
    connection: Any,
    *,
    resource_root: Path | None = None,
) -> PostgreSQLContractEvidence:
    """Verify the server, extensions, sole revision and every catalog/ACL fact."""

    root = resource_root or schema_resource_root()
    try:
        version_row = connection.execute("SHOW server_version_num").fetchone()
        encoding_row = connection.execute("SHOW server_encoding").fetchone()
        timezone_row = connection.execute("SHOW TimeZone").fetchone()
        locale_row = connection.execute(
            "SELECT datlocprovider,datlocale FROM pg_catalog.pg_database "
            "WHERE datname=current_database()"
        ).fetchone()
        if None in (version_row, encoding_row, timezone_row, locale_row):
            raise ValueError
        version = int(version_row[0])
        encoding = str(encoding_row[0])
        timezone = str(timezone_row[0])
        locale_provider, locale = str(locale_row[0]), str(locale_row[1])
        extension_rows = connection.execute(
            "SELECT extension.extname,extension.extversion,namespace.nspname "
            "FROM pg_catalog.pg_extension AS extension "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid=extension.extnamespace "
            "WHERE extension.extname IN ('pg_trgm','vector') ORDER BY 1"
        ).fetchall()
        extensions = tuple(
            (str(row[0]), str(row[1]), str(row[2])) for row in extension_rows
        )
        revision_rows = connection.execute(
            "SELECT version_num FROM armi.alembic_version"
        ).fetchall()
        identity_rows = connection.execute(
            "SELECT singleton_key,baseline_identity,resource_digest,"
            "installed_catalog_digest,role_policy_digest "
            "FROM armi.schema_baseline_identity"
        ).fetchall()
        table_count_row = connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid=relation.relnamespace "
            "WHERE namespace.nspname='armi' AND relation.relkind IN ('r','p')"
        ).fetchone()
        if table_count_row is None:
            raise ValueError
        current_catalog = database_catalog_digest(connection)
        expected_resource = schema_resource_digest(root)
        expected_role_policy = role_policy_digest(root)
    except (IndexError, TypeError, ValueError) as exc:
        raise PostgreSQLContractError("DB-DATABASE-IDENTITY") from exc
    if version != 180004:
        raise PostgreSQLContractError("DB-PG-VERSION")
    if encoding != "UTF8" or timezone != "UTC":
        raise PostgreSQLContractError("DB-DATABASE-IDENTITY")
    if locale_provider != "b" or locale != "C.UTF-8":
        raise PostgreSQLContractError("DB-DATABASE-IDENTITY")
    if extensions != _EXPECTED_EXTENSIONS:
        raise PostgreSQLContractError("DB-EXTENSION-IDENTITY")
    if revision_rows != [(EXPECTED_REVISION,)]:
        raise PostgreSQLContractError("DB-SCHEMA-REVISION")
    if identity_rows != [
        (
            True,
            BASELINE_IDENTITY,
            expected_resource,
            current_catalog,
            expected_role_policy,
        )
    ]:
        raise PostgreSQLContractError("DB-SCHEMA-CATALOG-DRIFT")
    return PostgreSQLContractEvidence(
        server_version_num=version,
        encoding=encoding,
        timezone=timezone,
        locale_provider=locale_provider,
        locale=locale,
        extensions=extensions,
        revision=EXPECTED_REVISION,
        baseline_identity=BASELINE_IDENTITY,
        resource_digest=expected_resource,
        catalog_digest=current_catalog,
        role_policy_digest=expected_role_policy,
        table_count=int(table_count_row[0]),
    )


__all__ = (
    "PostgreSQLContractError",
    "PostgreSQLContractEvidence",
    "verify_postgresql_contract",
)
