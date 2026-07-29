REVOKE ALL ON SCHEMA armi FROM PUBLIC;
REVOKE ALL ON TABLE armi.schema_migrations FROM PUBLIC;

GRANT USAGE ON SCHEMA armi TO armi_runtime, armi_admin, armi_migrator;
GRANT SELECT ON TABLE armi.schema_migrations
    TO armi_runtime, armi_admin, armi_migrator;
