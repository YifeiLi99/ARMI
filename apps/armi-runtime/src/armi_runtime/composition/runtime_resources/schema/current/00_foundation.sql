CREATE SCHEMA armi;

REVOKE ALL ON SCHEMA armi FROM PUBLIC;
GRANT USAGE ON SCHEMA armi TO armi_runtime, armi_admin, armi_migrator;
