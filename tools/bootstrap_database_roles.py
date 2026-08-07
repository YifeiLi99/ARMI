"""Check or apply the PostgreSQL 18.4 + pgvector 0.8.6 role topology.

This is a DBA bootstrap entry, not a product command. It accepts only a UUIDv7
environment identity and secret files below one explicit root.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg import sql

CAPABILITY_ROLES: Final = (
    "armi_owner",
    "armi_migrator",
    "armi_runtime",
    "armi_admin",
)
ROLE_CLASSES: Final = ("runtime", "admin", "migrator")
SEARCH_PATH: Final = "pg_catalog, armi"
PGVECTOR_SCHEMA: Final = "armi_extensions"
PGVECTOR_VERSION: Final = "0.8.6"
MAX_SECRET_BYTES: Final = 65_536


class BootstrapFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def physical_role_name(environment_id: UUID, role_class: str) -> str:
    if environment_id.version != 7 or role_class not in ROLE_CLASSES:
        raise BootstrapFailure(
            "DB-ROLE-IDENTITY", "the environment role identity is invalid"
        )
    return f"armi_{environment_id.hex}_{role_class}"


def _absolute_regular_secret(path: Path, *, root: Path) -> bytes:
    if not path.is_absolute() or not root.is_absolute():
        raise BootstrapFailure(
            "DB-ROLE-CREDENTIAL-SCOPE", "secret paths must be absolute"
        )
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise BootstrapFailure(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "a secret file is outside the approved root",
        ) from None
    metadata = resolved.stat(follow_symlinks=False)
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or stat.S_ISREG(metadata.st_mode) is False
        or metadata.st_size > MAX_SECRET_BYTES
        or (
            os.name == "nt"
            and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
    ):
        raise BootstrapFailure(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "a secret input is not an approved regular file",
        )
    value = resolved.read_bytes()
    if value.endswith(b"\r\n"):
        value = value[:-2]
    elif value.endswith(b"\n"):
        value = value[:-1]
    if not value:
        raise BootstrapFailure(
            "DB-ROLE-CREDENTIAL-SCOPE", "a required secret input is empty"
        )
    return value


def _decode(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        raise BootstrapFailure(
            "DB-ROLE-CREDENTIAL-SCOPE", "a secret input is not valid UTF-8"
        ) from None


def _role_exists(connection: psycopg.Connection[Any], role: str) -> bool:
    row = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s)",
        (role,),
    ).fetchone()
    return row == (True,)


def _current_database(connection: psycopg.Connection[Any]) -> str:
    row = connection.execute("SELECT current_database()").fetchone()
    if row is None:
        raise BootstrapFailure(
            "DB-DATABASE-IDENTITY", "the target database identity is unavailable"
        )
    return str(row[0])


def _normalize_role(
    connection: psycopg.Connection[Any],
    *,
    role: str,
    login: bool,
    inherit: bool,
    password: str | None = None,
) -> None:
    identifier = sql.Identifier(role)
    if not _role_exists(connection, role):
        connection.execute(sql.SQL("CREATE ROLE {}").format(identifier))
    attributes = (
        sql.SQL("LOGIN" if login else "NOLOGIN")
        + sql.SQL(" ")
        + sql.SQL("INHERIT" if inherit else "NOINHERIT")
    )
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS"
        ).format(identifier, attributes)
    )
    if password is not None:
        connection.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                identifier,
                sql.Literal(password),
            )
        )


def _set_membership(
    connection: psycopg.Connection[Any],
    *,
    member: str,
    role: str,
    inherit: bool,
    set_option: bool,
) -> None:
    connection.execute(
        sql.SQL("REVOKE {} FROM {}").format(
            sql.Identifier(role), sql.Identifier(member)
        )
    )
    connection.execute(
        sql.SQL("GRANT {} TO {} WITH ADMIN FALSE, INHERIT {}, SET {}").format(
            sql.Identifier(role),
            sql.Identifier(member),
            sql.SQL("TRUE" if inherit else "FALSE"),
            sql.SQL("TRUE" if set_option else "FALSE"),
        )
    )


def apply_policy(
    connection: psycopg.Connection[Any],
    *,
    environment_id: UUID,
    passwords: dict[str, str],
) -> None:
    for role in CAPABILITY_ROLES:
        _normalize_role(connection, role=role, login=False, inherit=False)
    connection.execute("CREATE SCHEMA IF NOT EXISTS armi_extensions")
    connection.execute("REVOKE ALL ON SCHEMA armi_extensions FROM PUBLIC")
    connection.execute(
        "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA armi_extensions"
    )
    extension = connection.execute(
        """
        SELECT extension.extversion, namespace.nspname
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'vector'
        """
    ).fetchone()
    if extension != (PGVECTOR_VERSION, PGVECTOR_SCHEMA):
        raise BootstrapFailure(
            "DB-PGVECTOR-IDENTITY", "pgvector version or schema is incompatible"
        )
    connection.execute(
        "GRANT USAGE ON SCHEMA armi_extensions "
        "TO armi_owner, armi_migrator, armi_runtime, armi_admin"
    )
    physical = {
        role_class: physical_role_name(environment_id, role_class)
        for role_class in ROLE_CLASSES
    }
    for role_class, role in physical.items():
        _normalize_role(
            connection,
            role=role,
            login=True,
            inherit=True,
            password=passwords[role_class],
        )
    for member in physical.values():
        for role in CAPABILITY_ROLES:
            connection.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(role), sql.Identifier(member)
                )
            )
    _set_membership(
        connection,
        member=physical["runtime"],
        role="armi_runtime",
        inherit=True,
        set_option=False,
    )
    _set_membership(
        connection,
        member=physical["admin"],
        role="armi_admin",
        inherit=True,
        set_option=False,
    )
    _set_membership(
        connection,
        member=physical["migrator"],
        role="armi_migrator",
        inherit=True,
        set_option=False,
    )
    _set_membership(
        connection,
        member=physical["migrator"],
        role="armi_owner",
        inherit=False,
        set_option=True,
    )
    database = _current_database(connection)
    connection.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
            sql.Identifier(database)
        )
    )
    connection.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM armi_owner").format(
            sql.Identifier(database)
        )
    )
    connection.execute(
        sql.SQL("GRANT CREATE ON DATABASE {} TO armi_owner").format(
            sql.Identifier(database)
        )
    )
    for role in physical.values():
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL(
                "ALTER ROLE {} IN DATABASE {} SET search_path TO pg_catalog, armi"
            ).format(sql.Identifier(role), sql.Identifier(database))
        )
    schema_exists = connection.execute(
        "SELECT to_regnamespace('armi') IS NOT NULL"
    ).fetchone() == (True,)
    if schema_exists:
        connection.execute("REVOKE ALL ON SCHEMA armi FROM PUBLIC")
        connection.execute("ALTER SCHEMA armi OWNER TO armi_owner")
    connection.commit()


def inspect_policy(
    connection: psycopg.Connection[Any],
    *,
    environment_id: UUID,
) -> dict[str, object]:
    physical = {
        role_class: physical_role_name(environment_id, role_class)
        for role_class in ROLE_CLASSES
    }
    expected_roles = [*CAPABILITY_ROLES, *physical.values()]
    rows = connection.execute(
        """
        SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
               rolcreaterole, rolreplication, rolbypassrls,
               CASE WHEN rolcanlogin
                    THEN rolpassword LIKE 'SCRAM-SHA-256$%%'
                    ELSE rolpassword IS NULL
               END
        FROM pg_catalog.pg_authid
        WHERE rolname = ANY(%s)
        ORDER BY rolname
        """,
        (expected_roles,),
    ).fetchall()
    expected_attributes = {
        role: (False, False, False, False, False, False, False, True)
        for role in CAPABILITY_ROLES
    }
    expected_attributes.update(
        {
            role: (True, True, False, False, False, False, False, True)
            for role in physical.values()
        }
    )
    actual_attributes = {
        str(row[0]): tuple(bool(value) for value in row[1:]) for row in rows
    }
    if actual_attributes != expected_attributes:
        raise BootstrapFailure(
            "DB-ROLE-ATTRIBUTES", "database role attributes have drifted"
        )
    memberships = connection.execute(
        """
        SELECT member_role.rolname, granted_role.rolname,
               membership.admin_option, membership.inherit_option,
               membership.set_option
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE member_role.rolname = ANY(%s)
        ORDER BY member_role.rolname, granted_role.rolname
        """,
        (list(physical.values()),),
    ).fetchall()
    actual_memberships = {
        (str(row[0]), str(row[1])): tuple(bool(value) for value in row[2:])
        for row in memberships
    }
    expected_memberships = {
        (physical["runtime"], "armi_runtime"): (False, True, False),
        (physical["admin"], "armi_admin"): (False, True, False),
        (physical["migrator"], "armi_migrator"): (False, True, False),
        (physical["migrator"], "armi_owner"): (False, False, True),
    }
    if actual_memberships != expected_memberships:
        raise BootstrapFailure(
            "DB-ROLE-MEMBERSHIP", "database role memberships have drifted"
        )
    database = _current_database(connection)
    public = connection.execute(
        """
        SELECT COALESCE(
            array_agg(acl.privilege_type ORDER BY acl.privilege_type)
                FILTER (WHERE acl.grantee = 0),
            ARRAY[]::text[]
        )
        FROM pg_catalog.pg_database AS database_value
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                database_value.datacl,
                pg_catalog.acldefault('d', database_value.datdba)
            )
        ) AS acl
        WHERE database_value.datname = current_database()
        """
    ).fetchone()
    grants = {
        role: connection.execute(
            """
            SELECT has_database_privilege(%s, current_database(), 'CONNECT'),
                   has_database_privilege(%s, current_database(), 'CREATE'),
                   has_database_privilege(%s, current_database(), 'TEMPORARY')
            """,
            (role, role, role),
        ).fetchone()
        for role in physical.values()
    }
    owner = connection.execute(
        """
        SELECT has_database_privilege(
                   'armi_owner', current_database(), 'CONNECT'
               ),
               has_database_privilege(
                   'armi_owner', current_database(), 'CREATE'
               ),
               has_database_privilege(
                   'armi_owner', current_database(), 'TEMPORARY'
               )
        """
    ).fetchone()
    if (
        public != ([],)
        or owner != (False, True, False)
        or any(grant != (True, False, False) for grant in grants.values())
    ):
        raise BootstrapFailure("DB-ROLE-GRANT", "database grants have drifted")
    settings = connection.execute(
        """
        SELECT role_value.rolname, setting
        FROM pg_catalog.pg_db_role_setting AS role_setting
        JOIN pg_catalog.pg_roles AS role_value
          ON role_value.oid = role_setting.setrole
        JOIN LATERAL unnest(role_setting.setconfig) AS setting ON true
        WHERE role_setting.setdatabase = (
                  SELECT oid FROM pg_catalog.pg_database WHERE datname = %s
              )
          AND role_value.rolname = ANY(%s)
        ORDER BY role_value.rolname, setting
        """,
        (database, list(physical.values())),
    ).fetchall()
    expected_settings = sorted(
        (role, f"search_path={SEARCH_PATH}") for role in physical.values()
    )
    if [(str(row[0]), str(row[1])) for row in settings] != expected_settings:
        raise BootstrapFailure(
            "DB-ROLE-SEARCH-PATH", "database role search_path has drifted"
        )
    extension = connection.execute(
        """
        SELECT extension.extversion, namespace.nspname
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'vector'
        """
    ).fetchone()
    extension_usage = connection.execute(
        """
        SELECT role_value.rolname,
               has_schema_privilege(role_value.rolname, 'armi_extensions', 'USAGE')
        FROM pg_catalog.pg_roles AS role_value
        WHERE role_value.rolname = ANY(%s)
        ORDER BY role_value.rolname
        """,
        (list(CAPABILITY_ROLES),),
    ).fetchall()
    if extension != (PGVECTOR_VERSION, PGVECTOR_SCHEMA) or extension_usage != [
        (role, True) for role in sorted(CAPABILITY_ROLES)
    ]:
        raise BootstrapFailure(
            "DB-PGVECTOR-IDENTITY", "pgvector identity or grants have drifted"
        )
    return {
        "status": "pass",
        "schema_version": "armi.database-roles.v2",
        "environment_id": str(environment_id),
        "role_count": len(expected_roles),
        "membership_count": len(expected_memberships),
        "database_grants": "restricted",
        "credential_hashes": "scram-sha-256",
        "pgvector": f"{PGVECTOR_VERSION}@{PGVECTOR_SCHEMA}",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-id", type=UUID, required=True)
    parser.add_argument("--secret-root", type=Path, required=True)
    parser.add_argument("--provisioner-conninfo-file", type=Path, required=True)
    parser.add_argument("--runtime-password-file", type=Path)
    parser.add_argument("--admin-password-file", type=Path)
    parser.add_argument("--migrator-password-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.environment_id.version != 7:
            raise BootstrapFailure(
                "DB-ROLE-IDENTITY", "environment-id must be canonical UUIDv7"
            )
        conninfo = _decode(
            _absolute_regular_secret(
                args.provisioner_conninfo_file, root=args.secret_root
            )
        )
        password_paths = {
            "runtime": args.runtime_password_file,
            "admin": args.admin_password_file,
            "migrator": args.migrator_password_file,
        }
        if args.apply and any(path is None for path in password_paths.values()):
            raise BootstrapFailure(
                "DB-ROLE-CREDENTIAL-SCOPE",
                "apply requires three independent password files",
            )
        passwords = (
            {
                role_class: _decode(
                    _absolute_regular_secret(path, root=args.secret_root)
                )
                for role_class, path in password_paths.items()
                if path is not None
            }
            if args.apply
            else {}
        )
        if args.apply and len(set(passwords.values())) != len(ROLE_CLASSES):
            raise BootstrapFailure(
                "DB-ROLE-CREDENTIAL-SCOPE",
                "database login credentials must be independent",
            )
        with psycopg.connect(
            conninfo,
            autocommit=False,
            connect_timeout=5,
            application_name="armi-dba-role-bootstrap",
        ) as connection:
            if args.apply:
                apply_policy(
                    connection,
                    environment_id=args.environment_id,
                    passwords=passwords,
                )
            result = inspect_policy(
                connection,
                environment_id=args.environment_id,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BootstrapFailure, psycopg.Error, OSError) as error:
        failure = (
            error
            if isinstance(error, BootstrapFailure)
            else BootstrapFailure(
                "DB-CONNECTION-UNAVAILABLE",
                "the database role policy could not be verified",
            )
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": failure.code,
                    "message": failure.message,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
