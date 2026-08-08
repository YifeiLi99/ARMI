"""Freeze the modular v1 baseline catalog digest from isolated PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from collections.abc import Sequence

import psycopg
from armi_postgresql_contract.catalog_fingerprint import (
    database_catalog_digest,
)
from generate_schema_manifests import (
    BASELINE_DOCUMENTS,
    BASELINE_ROOT,
)
from generate_schema_manifests import (
    main as generate_schema_manifests,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def _target_conninfo(admin_dsn: str, database: str) -> str:
    values = conninfo_to_dict(admin_dsn)
    values["dbname"] = database
    return make_conninfo(**values)


def _write_catalog_digest(value: str) -> None:
    path = BASELINE_ROOT / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["catalog_sha256"] = value
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def freeze(admin_dsn: str) -> str:
    if generate_schema_manifests() != 0:
        raise RuntimeError("SCHEMA-CATALOG-MANIFEST")
    database = f"armi_catalog_{secrets.token_hex(6)}"
    roles = ("armi_owner", "armi_runtime", "armi_admin", "armi_migrator")
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        existing = admin.execute(
            "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
            (list(roles),),
        ).fetchall()
        if existing:
            raise RuntimeError("SCHEMA-CATALOG-ROLE-COLLISION")
        for role in roles:
            admin.execute(
                sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT").format(
                    sql.Identifier(role)
                )
            )
        admin.execute(
            sql.SQL(
                "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' "
                "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8'"
            ).format(sql.Identifier(database))
        )
        admin.execute(
            sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO armi_owner").format(
                sql.Identifier(database)
            )
        )
    try:
        with psycopg.connect(_target_conninfo(admin_dsn, database)) as connection:
            connection.execute("CREATE SCHEMA armi_extensions")
            connection.execute("REVOKE ALL ON SCHEMA armi_extensions FROM PUBLIC")
            connection.execute("CREATE EXTENSION vector WITH SCHEMA armi_extensions")
            connection.execute("CREATE EXTENSION pg_trgm WITH SCHEMA armi_extensions")
            connection.execute(
                "GRANT USAGE ON SCHEMA armi_extensions "
                "TO armi_owner, armi_migrator, armi_runtime, armi_admin"
            )
            connection.execute("SET ROLE armi_owner")
            for name in BASELINE_DOCUMENTS:
                connection.execute((BASELINE_ROOT / name).read_text(encoding="utf-8"))
            connection.execute("RESET ROLE")
            digest = database_catalog_digest(connection)
        _write_catalog_digest(digest)
        if generate_schema_manifests() != 0:
            raise RuntimeError("SCHEMA-CATALOG-MANIFEST")
        return digest
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )
            for role in reversed(roles):
                admin.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn-env", default="S009_ADMIN_DSN")
    args = parser.parse_args(argv)
    admin_dsn = os.environ.get(args.admin_dsn_env)
    if not admin_dsn:
        raise RuntimeError("SCHEMA-CATALOG-ADMIN-DSN")
    print(freeze(admin_dsn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
