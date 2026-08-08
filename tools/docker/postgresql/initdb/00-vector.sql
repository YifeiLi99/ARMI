CREATE SCHEMA armi_extensions;
REVOKE ALL ON SCHEMA armi_extensions FROM PUBLIC;
CREATE EXTENSION vector WITH SCHEMA armi_extensions;
CREATE EXTENSION pg_trgm WITH SCHEMA armi_extensions;
