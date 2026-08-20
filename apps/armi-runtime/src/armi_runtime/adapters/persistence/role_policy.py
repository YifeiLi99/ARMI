"""PostgreSQL role-policy verification and role-bound connection reset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg

from armi_runtime.adapters.database_errors import DatabaseViolation

_ROLE_CLASSES: Final = frozenset({"runtime", "admin", "migrator"})
_SEARCH_PATH: Final = "pg_catalog, armi"
_CAPABILITY_ROLES: Final = (
    "armi_owner",
    "armi_migrator",
    "armi_runtime",
    "armi_admin",
)


def physical_role_name(environment_id: UUID, role_class: str) -> str:
    if environment_id.version != 7 or role_class not in _ROLE_CLASSES:
        raise DatabaseViolation(
            "DB-ROLE-IDENTITY", "the database role identity is invalid"
        )
    return f"armi_{environment_id.hex}_{role_class}"


@dataclass(frozen=True, slots=True)
class RolePolicyStatus:
    verified: bool = True


class PostgreSQLRolePolicyGateway:
    """Verify the fixed development roles without a generated policy manifest."""

    __slots__ = ()

    def verify(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        environment_id: UUID,
        role_class: str,
        require_objects: bool = True,
    ) -> RolePolicyStatus:
        expected_role = physical_role_name(environment_id, role_class)
        self._verify_session(connection, expected_role)
        self._verify_role_attributes(connection, environment_id)
        self._verify_memberships(connection, environment_id)
        self._verify_database_grants(connection, environment_id)
        if require_objects:
            self._verify_object_policy(connection)
        return RolePolicyStatus()

    def _verify_session(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        expected_role: str,
    ) -> None:
        try:
            row = connection.execute(
                "SELECT session_user, current_user, current_setting('search_path')"
            ).fetchone()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-IDENTITY", "the database session identity is unavailable"
            ) from None
        if row != (expected_role, expected_role, _SEARCH_PATH):
            code = (
                "DB-ROLE-SEARCH-PATH"
                if row is not None
                and row[0] == expected_role
                and row[1] == expected_role
                else "DB-ROLE-IDENTITY"
            )
            raise DatabaseViolation(code, "the database session role policy is unsafe")

    def _verify_role_attributes(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        environment_id: UUID,
    ) -> None:
        expected: dict[str, tuple[bool, bool]] = {
            name: (False, False) for name in _CAPABILITY_ROLES
        }
        expected.update(
            {
                physical_role_name(environment_id, role_class): (True, True)
                for role_class in _ROLE_CLASSES
            }
        )
        try:
            rows = connection.execute(
                """
                SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles
                WHERE rolname = ANY(%s)
                ORDER BY rolname
                """,
                (list(expected),),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-ATTRIBUTES", "database role attributes are unavailable"
            ) from None
        actual = {
            str(row[0]): (
                bool(row[1]),
                bool(row[2]),
                any(bool(value) for value in row[3:]),
            )
            for row in rows
        }
        if set(actual) != set(expected) or any(
            actual[name] != (login, inherit, False)
            for name, (login, inherit) in expected.items()
        ):
            raise DatabaseViolation(
                "DB-ROLE-ATTRIBUTES", "database role attributes have drifted"
            )

    def _verify_memberships(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        environment_id: UUID,
    ) -> None:
        expected = {
            (
                physical_role_name(environment_id, "runtime"),
                "armi_runtime",
            ): (False, True, False),
            (
                physical_role_name(environment_id, "admin"),
                "armi_admin",
            ): (False, True, False),
            (
                physical_role_name(environment_id, "migrator"),
                "armi_migrator",
            ): (False, True, False),
            (
                physical_role_name(environment_id, "migrator"),
                "armi_owner",
            ): (False, False, True),
        }
        members = [
            physical_role_name(environment_id, role_class)
            for role_class in _ROLE_CLASSES
        ]
        try:
            rows = connection.execute(
                """
                SELECT member_role.rolname, granted_role.rolname,
                       membership.admin_option,
                       membership.inherit_option,
                       membership.set_option
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role
                  ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                WHERE member_role.rolname = ANY(%s)
                ORDER BY member_role.rolname, granted_role.rolname
                """,
                (members,),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-MEMBERSHIP", "database role memberships are unavailable"
            ) from None
        actual = {
            (str(row[0]), str(row[1])): (
                bool(row[2]),
                bool(row[3]),
                bool(row[4]),
            )
            for row in rows
        }
        if actual != expected:
            raise DatabaseViolation(
                "DB-ROLE-MEMBERSHIP", "database role memberships have drifted"
            )

    def _verify_database_grants(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        environment_id: UUID,
    ) -> None:
        expected_roles = [
            physical_role_name(environment_id, role_class)
            for role_class in ("runtime", "admin", "migrator")
        ]
        try:
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
            rows = [
                connection.execute(
                    """
                    SELECT
                        has_database_privilege(%s, current_database(), 'CONNECT'),
                        has_database_privilege(%s, current_database(), 'CREATE'),
                        has_database_privilege(%s, current_database(), 'TEMPORARY')
                    """,
                    (role, role, role),
                ).fetchone()
                for role in expected_roles
            ]
            owner = connection.execute(
                """
                SELECT
                    has_database_privilege(
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
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "database role grants are unavailable"
            ) from None
        if public != ([],):
            raise DatabaseViolation(
                "DB-ROLE-PUBLIC-PRIVILEGE",
                "PUBLIC database privileges are unsafe",
            )
        if any(row != (True, False, False) for row in rows):
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "database login grants have drifted"
            )
        if owner != (False, True, False):
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "database owner grants have drifted"
            )

    @staticmethod
    def _verify_object_policy(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> None:
        try:
            ownership = connection.execute(
                """
                SELECT
                    namespace.nspowner = owner_role.oid,
                    bool_and(relation.relowner = owner_role.oid),
                    count(relation.oid)
                FROM pg_catalog.pg_namespace AS namespace
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.rolname = 'armi_owner'
                LEFT JOIN pg_catalog.pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relkind IN ('r', 'p')
                WHERE namespace.nspname = 'armi'
                GROUP BY namespace.nspowner, owner_role.oid
                """
            ).fetchone()
            public_count = connection.execute(
                """
                SELECT (
                    SELECT count(*)
                    FROM pg_catalog.pg_namespace AS namespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            namespace.nspacl,
                            pg_catalog.acldefault('n', namespace.nspowner)
                        )
                    ) AS acl
                    WHERE namespace.nspname = 'armi' AND acl.grantee = 0
                ) + (
                    SELECT count(*)
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            relation.relacl,
                            pg_catalog.acldefault('r', relation.relowner)
                        )
                    ) AS acl
                    WHERE namespace.nspname = 'armi'
                      AND relation.relkind IN ('r', 'p')
                      AND acl.grantee = 0
                )
                """
            ).fetchone()
            schema_grants = connection.execute(
                """
                SELECT role_name,
                       pg_catalog.has_schema_privilege(
                           role_name, 'armi', 'USAGE'
                       ),
                       pg_catalog.has_schema_privilege(
                           role_name, 'armi', 'CREATE'
                       )
                FROM unnest(%s::text[]) AS role_name
                ORDER BY role_name
                """,
                (["armi_admin", "armi_migrator", "armi_runtime"],),
            ).fetchall()
            definers = connection.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_proc AS procedure
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'armi'
                  AND procedure.prosecdef
                """
            ).fetchone()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-GRANT",
                "database object grants are unavailable",
            ) from None
        if (
            ownership is None
            or ownership[0] is not True
            or ownership[1] is not True
            or int(ownership[2]) < 1
        ):
            raise DatabaseViolation(
                "DB-ROLE-OWNER",
                "database object ownership has drifted",
            )
        if public_count != (0,):
            raise DatabaseViolation(
                "DB-ROLE-PUBLIC-PRIVILEGE",
                "PUBLIC object privileges are unsafe",
            )
        if any(tuple(row[1:]) != (True, False) for row in schema_grants):
            raise DatabaseViolation(
                "DB-ROLE-GRANT",
                "database schema grants have drifted",
            )
        if definers != (0,):
            raise DatabaseViolation(
                "DB-ROLE-SECURITY-DEFINER",
                "an unregistered security-definer entry exists",
            )


__all__ = (
    "PostgreSQLRolePolicyGateway",
    "RolePolicyStatus",
    "physical_role_name",
)
