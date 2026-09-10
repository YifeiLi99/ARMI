"""Disposable native PostgreSQL clusters using the product lifecycle."""

from __future__ import annotations

import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid7

import psycopg
from armi_local_control import (
    NativePostgreSQL,
    PostgreSQLControlBinding,
    free_loopback_port,
)
from armi_local_control.runtime_errors import RuntimeViolation
from psycopg.conninfo import make_conninfo


class PostgreSQLUnavailable(RuntimeError):
    """The exact native database distribution is unavailable."""


class PostgreSQLLaunchError(RuntimeError):
    """A disposable native database could not be initialized or stopped."""


@dataclass(frozen=True, slots=True)
class IsolatedPostgreSQL:
    admin_dsn: str
    data_directory: Path


@contextmanager
def isolated_postgresql(root: Path) -> Iterator[IsolatedPostgreSQL]:
    distribution = (
        root / ".armi-tools/installs/postgresql-native/18.4-vector-0.8.6-utf8/pgsql"
    )
    if not (distribution / "lib/vector.dll").is_file():
        raise PostgreSQLUnavailable("PG-NATIVE-DISTRIBUTION")
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    # Cleanup is explicit: never remove files after an unconfirmed shutdown.
    temporary = tempfile.mkdtemp(prefix="postgresql-native-", dir=temporary_root)
    environment = Path(temporary).resolve()
    binding = PostgreSQLControlBinding(
        ownership="exclusive",
        installation_root=distribution.resolve(),
        data_directory=environment / "postgresql/data",
        port=free_loopback_port(),
    )
    manager = NativePostgreSQL(
        binding, environment_root=environment, environment_id=str(uuid7())
    )
    password = secrets.token_urlsafe(32)
    initialized = False
    try:
        manager.initialize(username="s009_admin", password=password)
        initialized = True
        manager.execute("start")
        dsn = make_conninfo(
            host="127.0.0.1",
            port=binding.port,
            dbname="postgres",
            user="s009_admin",
            password=password,
        )
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE SCHEMA armi_extensions")
            connection.execute("REVOKE ALL ON SCHEMA armi_extensions FROM PUBLIC")
            connection.execute(
                "CREATE EXTENSION vector WITH SCHEMA armi_extensions VERSION '0.8.6'"
            )
            connection.execute(
                "CREATE EXTENSION pg_trgm WITH SCHEMA armi_extensions VERSION '1.6'"
            )
        yield IsolatedPostgreSQL(dsn, binding.data_directory)
    except RuntimeViolation as error:
        raise PostgreSQLLaunchError(error.code) from None
    finally:
        if initialized:
            try:
                manager.execute("stop")
            except RuntimeViolation as error:
                raise PostgreSQLLaunchError(error.code) from None
        import shutil

        if (
            environment.parent != temporary_root.resolve()
            or not environment.name.startswith("postgresql-native-")
        ):
            raise PostgreSQLLaunchError("PG-NATIVE-CLEANUP-BOUNDARY")
        shutil.rmtree(environment)


__all__ = (
    "IsolatedPostgreSQL",
    "PostgreSQLLaunchError",
    "PostgreSQLUnavailable",
    "isolated_postgresql",
)
