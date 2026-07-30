"""PostgreSQL role-policy verification and role-bound connection reset."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, cast
from uuid import UUID

import psycopg
import rfc8785
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from armi_runtime.adapters.database_errors import DatabaseViolation

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_ROLE_MANIFEST_PATH = "schema/manifests/database-role-manifest.json"
_SCHEMA_MANIFEST_PATH = "schema/manifests/schema-manifest.json"
_ROLE_CLASSES: Final = frozenset({"runtime", "admin", "migrator"})
_SEARCH_PATH: Final = "pg_catalog, armi"
_CAPABILITY_ROLES: Final = (
    "armi_owner",
    "armi_migrator",
    "armi_runtime",
    "armi_admin",
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def physical_role_name(environment_id: UUID, role_class: str) -> str:
    if environment_id.version != 7 or role_class not in _ROLE_CLASSES:
        raise DatabaseViolation(
            "DB-ROLE-IDENTITY", "the database role identity is invalid"
        )
    return f"armi_{environment_id.hex}_{role_class}"


@dataclass(frozen=True, slots=True)
class RolePolicyStatus:
    role_policy_sha256: str
    privilege_catalog_sha256: str


@dataclass(frozen=True, slots=True)
class _LoadedRolePolicy:
    manifest: dict[str, Any]
    digest: str


def _load_role_policy() -> _LoadedRolePolicy:
    root = files(_RESOURCE_PACKAGE)
    try:
        role_bytes = root.joinpath(_ROLE_MANIFEST_PATH).read_bytes()
        schema_bytes = root.joinpath(_SCHEMA_MANIFEST_PATH).read_bytes()
        role_manifest = cast(dict[str, Any], json.loads(role_bytes))
        schema_manifest = cast(dict[str, Any], json.loads(schema_bytes))
        reference = cast(dict[str, Any], schema_manifest["database_role_manifest"])
    except OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError:
        raise DatabaseViolation(
            "DB-ROLE-MANIFEST-DRIFT",
            "the packaged database-role manifest is unavailable",
        ) from None
    digest = _digest(role_bytes)
    if (
        role_manifest.get("schema_version") != "armi.database-roles.v1"
        or rfc8785.dumps(cast(Any, role_manifest)) + b"\n" != role_bytes
        or reference.get("path") != _ROLE_MANIFEST_PATH
        or reference.get("sha256") != digest
    ):
        raise DatabaseViolation(
            "DB-ROLE-MANIFEST-DRIFT",
            "the packaged database-role manifest has drifted",
        )
    return _LoadedRolePolicy(role_manifest, digest)


class PostgreSQLRolePolicyGateway:
    """Verify one environment's exact role topology and effective privileges."""

    __slots__ = ("_policy",)

    def __init__(self) -> None:
        self._policy = _load_role_policy()

    @property
    def role_policy_sha256(self) -> str:
        return self._policy.digest

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
        digest = self._privilege_catalog_digest(
            connection,
            environment_id=environment_id,
            include_objects=require_objects,
        )
        return RolePolicyStatus(self.role_policy_sha256, digest)

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

    def _verify_object_policy(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> None:
        try:
            owners = connection.execute(
                """
                SELECT
                    bool_and(namespace.nspowner = owner_role.oid),
                    bool_and(relation.relowner = owner_role.oid),
                    array_agg(relation.relname ORDER BY relation.relname)
                FROM pg_catalog.pg_namespace AS namespace
                JOIN pg_catalog.pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.rolname = 'armi_owner'
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                """
            ).fetchone()
            public_grants = connection.execute(
                """
                SELECT object_kind, array_agg(privilege_type ORDER BY privilege_type)
                FROM (
                    SELECT 'schema' AS object_kind, acl.privilege_type
                    FROM pg_catalog.pg_namespace AS namespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            namespace.nspacl,
                            pg_catalog.acldefault('n', namespace.nspowner)
                        )
                    ) AS acl
                    WHERE namespace.nspname = 'armi' AND acl.grantee = 0
                    UNION ALL
                    SELECT 'table' AS object_kind, acl.privilege_type
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
                ) AS public_acl
                GROUP BY object_kind
                ORDER BY object_kind
                """
            ).fetchall()
            grants = connection.execute(
                """
                SELECT
                    has_schema_privilege('armi_runtime', 'armi', 'USAGE'),
                    has_schema_privilege('armi_runtime', 'armi', 'CREATE'),
                    has_table_privilege(
                        'armi_runtime', 'armi.schema_migrations', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_runtime', 'armi.artifacts', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_runtime', 'armi.artifacts', 'DELETE'
                    ),
                    has_table_privilege(
                        'armi_runtime', 'armi.audit_events', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_runtime', 'armi.audit_events', 'UPDATE'
                    ),
                    has_table_privilege(
                        'armi_runtime', 'armi.audit_events', 'DELETE'
                    ),
                    has_schema_privilege('armi_admin', 'armi', 'USAGE'),
                    has_schema_privilege('armi_admin', 'armi', 'CREATE'),
                    has_table_privilege(
                        'armi_admin', 'armi.schema_migrations', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_admin', 'armi.artifacts', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_admin', 'armi.audit_events', 'SELECT'
                    ),
                    has_schema_privilege('armi_migrator', 'armi', 'USAGE'),
                    has_schema_privilege('armi_migrator', 'armi', 'CREATE'),
                    has_table_privilege(
                        'armi_migrator', 'armi.schema_migrations', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_migrator', 'armi.artifacts', 'SELECT'
                    ),
                    has_table_privilege(
                        'armi_migrator', 'armi.audit_events', 'SELECT'
                    )
                """
            ).fetchone()
            column_grants = connection.execute(
                """
                SELECT
                    relation.relname,
                    attribute.attname,
                    acl.privilege_type,
                    COALESCE(grantee_role.rolname, 'PUBLIC')
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee_role
                  ON grantee_role.oid = acl.grantee
                WHERE namespace.nspname = 'armi'
                  AND relation.relname IN ('artifacts', 'audit_events')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY relation.relname, attribute.attname, acl.privilege_type,
                         COALESCE(grantee_role.rolname, 'PUBLIC')
                """
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
                "DB-ROLE-GRANT", "database object grants are unavailable"
            ) from None
        if owners != (
            True,
            True,
            ["artifacts", "audit_events", "schema_migrations"],
        ):
            raise DatabaseViolation(
                "DB-ROLE-OWNER", "database object ownership has drifted"
            )
        if public_grants:
            raise DatabaseViolation(
                "DB-ROLE-PUBLIC-PRIVILEGE",
                "PUBLIC object privileges are unsafe",
            )
        if grants is None or tuple(bool(value) for value in grants) != (
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
        ):
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "database object grants have drifted"
            )
        expected_column_grants = {
            ("artifacts", column, "INSERT", "armi_runtime")
            for column in (
                "artifact_id",
                "byte_size",
                "content_digest",
                "logical_kind",
                "media_type",
                "privacy_scope",
                "producer_kind",
                "producer_trace_id",
                "schema_version",
                "storage_locator",
            )
        }
        expected_column_grants.add(
            ("artifacts", "integrity_status", "UPDATE", "armi_runtime")
        )
        expected_column_grants.update(
            {
                ("audit_events", column, "INSERT", "armi_runtime")
                for column in (
                    "actor_kind",
                    "actor_ref",
                    "after_version",
                    "artifact_digest",
                    "audit_event_id",
                    "before_version",
                    "bundle_digest",
                    "details_digest",
                    "error_category",
                    "grant_ref",
                    "operation",
                    "policy_ref",
                    "purpose",
                    "request_digest",
                    "request_kind",
                    "request_ref",
                    "response_digest",
                    "result_status",
                    "schema_version",
                    "sensitivity",
                    "subject_id",
                    "target_kind",
                    "target_ref",
                    "trace_id",
                )
            }
        )
        if {
            (str(table), str(column), str(privilege), str(grantee))
            for table, column, privilege, grantee in column_grants
        } != expected_column_grants:
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "artifact column grants have drifted"
            )
        if definers != (0,):
            raise DatabaseViolation(
                "DB-ROLE-SECURITY-DEFINER",
                "an unregistered security-definer entry exists",
            )

    def _privilege_catalog_digest(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        environment_id: UUID,
        include_objects: bool,
    ) -> str:
        roles = [
            *_CAPABILITY_ROLES,
            *(
                physical_role_name(environment_id, role_class)
                for role_class in ("runtime", "admin", "migrator")
            ),
        ]
        try:
            attributes = connection.execute(
                """
                SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles
                WHERE rolname = ANY(%s)
                ORDER BY rolname
                """,
                (roles,),
            ).fetchall()
            memberships = connection.execute(
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
                (roles,),
            ).fetchall()
            owners = (
                connection.execute(
                    """
                    SELECT namespace.nspname, namespace_owner.rolname,
                           relation.relname, relation_owner.rolname
                    FROM pg_catalog.pg_namespace AS namespace
                    JOIN pg_catalog.pg_roles AS namespace_owner
                      ON namespace_owner.oid = namespace.nspowner
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.relnamespace = namespace.oid
                    JOIN pg_catalog.pg_roles AS relation_owner
                      ON relation_owner.oid = relation.relowner
                    WHERE namespace.nspname = 'armi'
                      AND relation.relkind IN ('r', 'p')
                    ORDER BY relation.relname
                    """
                ).fetchall()
                if include_objects
                else []
            )
            database_acl = connection.execute(
                """
                SELECT COALESCE(grantee_role.rolname, 'PUBLIC'),
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_database AS database_value
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        database_value.datacl,
                        pg_catalog.acldefault('d', database_value.datdba)
                    )
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee_role
                  ON grantee_role.oid = acl.grantee
                WHERE database_value.datname = current_database()
                  AND (
                      acl.grantee = 0
                      OR grantee_role.rolname = ANY(%s)
                  )
                ORDER BY COALESCE(grantee_role.rolname, 'PUBLIC'),
                         acl.privilege_type
                """,
                (roles,),
            ).fetchall()
            object_acl = (
                connection.execute(
                    """
                    SELECT object_kind, object_name,
                           COALESCE(grantee_role.rolname, 'PUBLIC'),
                           privilege_type, is_grantable
                    FROM (
                        SELECT 'schema' AS object_kind, namespace.nspname AS object_name,
                               acl.grantee, acl.privilege_type, acl.is_grantable
                        FROM pg_catalog.pg_namespace AS namespace
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                namespace.nspacl,
                                pg_catalog.acldefault('n', namespace.nspowner)
                            )
                        ) AS acl
                        WHERE namespace.nspname = 'armi'
                        UNION ALL
                        SELECT 'table', namespace.nspname || '.' || relation.relname,
                               acl.grantee, acl.privilege_type, acl.is_grantable
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
                    ) AS object_privilege
                    LEFT JOIN pg_catalog.pg_roles AS grantee_role
                      ON grantee_role.oid = object_privilege.grantee
                    WHERE object_privilege.grantee = 0
                       OR grantee_role.rolname = ANY(%s)
                    ORDER BY object_kind, object_name,
                             COALESCE(grantee_role.rolname, 'PUBLIC'),
                             privilege_type
                    """,
                    (roles,),
                ).fetchall()
                if include_objects
                else []
            )
            column_acl = (
                connection.execute(
                    """
                    SELECT namespace.nspname || '.' || relation.relname,
                           attribute.attname,
                           COALESCE(grantee_role.rolname, 'PUBLIC'),
                           acl.privilege_type,
                           acl.is_grantable
                    FROM pg_catalog.pg_attribute AS attribute
                    JOIN pg_catalog.pg_class AS relation
                      ON relation.oid = attribute.attrelid
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
                    LEFT JOIN pg_catalog.pg_roles AS grantee_role
                      ON grantee_role.oid = acl.grantee
                    WHERE namespace.nspname = 'armi'
                      AND relation.relkind IN ('r', 'p')
                      AND attribute.attnum > 0
                      AND NOT attribute.attisdropped
                      AND (
                          acl.grantee = 0
                          OR grantee_role.rolname = ANY(%s)
                      )
                    ORDER BY namespace.nspname, relation.relname,
                             attribute.attname,
                             COALESCE(grantee_role.rolname, 'PUBLIC'),
                             acl.privilege_type
                    """,
                    (roles,),
                ).fetchall()
                if include_objects
                else []
            )
            role_settings = connection.execute(
                """
                SELECT role_value.rolname, setting
                FROM pg_catalog.pg_db_role_setting AS role_setting
                JOIN pg_catalog.pg_roles AS role_value
                  ON role_value.oid = role_setting.setrole
                JOIN LATERAL unnest(role_setting.setconfig) AS setting ON true
                WHERE role_setting.setdatabase = (
                    SELECT oid FROM pg_catalog.pg_database
                    WHERE datname = current_database()
                )
                  AND role_value.rolname = ANY(%s)
                ORDER BY role_value.rolname, setting
                """,
                (roles,),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-ROLE-GRANT", "the privilege catalog cannot be summarized"
            ) from None
        value = {
            "schema_version": "armi.database-privilege-catalog.v1",
            "roles": [list(row) for row in attributes],
            "memberships": [list(row) for row in memberships],
            "owners": [list(row) for row in owners],
            "database_acl": [list(row) for row in database_acl],
            "object_acl": [list(row) for row in object_acl],
            "column_acl": [list(row) for row in column_acl],
            "role_settings": [list(row) for row in role_settings],
            "role_policy_sha256": self.role_policy_sha256,
        }
        return _digest(rfc8785.dumps(cast(Any, value)))


class RoleBoundConnectionPool:
    """A minimal pool that resets role and session state before reuse."""

    __slots__ = ("_environment_id", "_gateway", "_pool", "_role_class")

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        role_class: str,
        min_size: int = 0,
        max_size: int = 1,
    ) -> None:
        physical_role_name(environment_id, role_class)
        self._environment_id = environment_id
        self._role_class = role_class
        self._gateway = PostgreSQLRolePolicyGateway()
        self._pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=False,
            configure=self._configure,
            reset=self._reset,
            kwargs={"application_name": f"armi-{role_class}-pool"},
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self):
        with self._pool.connection() as connection:
            self._gateway.verify(
                connection,
                environment_id=self._environment_id,
                role_class=self._role_class,
            )
            yield connection

    def _configure(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute("SET search_path TO pg_catalog, armi")
        connection.commit()
        self._gateway.verify(
            connection,
            environment_id=self._environment_id,
            role_class=self._role_class,
        )
        connection.commit()

    def _reset(self, connection: psycopg.Connection[Any]) -> None:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            connection.rollback()
        connection.execute("RESET ROLE")
        connection.execute("RESET ALL")
        connection.execute("SET search_path TO pg_catalog, armi")
        self._gateway.verify(
            connection,
            environment_id=self._environment_id,
            role_class=self._role_class,
        )
        connection.commit()


__all__ = (
    "PostgreSQLRolePolicyGateway",
    "RoleBoundConnectionPool",
    "RolePolicyStatus",
    "physical_role_name",
)
