"""DBA CLI for the packaged PostgreSQL role installation contract."""

from armi_admin.application.postgresql_bootstrap import main

if __name__ == "__main__":
    raise SystemExit(main())
