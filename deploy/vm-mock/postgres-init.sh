#!/bin/sh
set -eu
test "$POSTGRES_DB" = agentforge
test "$POSTGRES_USER" = postgres
test "${#VM_MOCK_APP_PASSWORD}" -eq 64
case "$VM_MOCK_APP_PASSWORD" in *[!0-9a-f]*) exit 1;; esac
# This script is only run by the official image on its NEW empty PGDATA.
# psql reads secrets from environment, not argv or an echoed SQL command.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password VM_MOCK_APP_PASSWORD
\getenv instance VM_MOCK_INSTANCE_ID
CREATE ROLE agentforge_demo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
ALTER DATABASE agentforge OWNER TO agentforge_demo;
ALTER SCHEMA public OWNER TO agentforge_demo;
CREATE SCHEMA vm_demo_guard AUTHORIZATION postgres;
CREATE TABLE vm_demo_guard.identity (
    instance uuid PRIMARY KEY,
    purpose text NOT NULL CHECK (purpose = 'agentforge-vm-mock'),
    base_source text NOT NULL
);
INSERT INTO vm_demo_guard.identity VALUES (
    :'instance'::uuid, 'agentforge-vm-mock', '662eb38d72f2bed243594deae54008042adf7e45'
);
REVOKE ALL ON SCHEMA vm_demo_guard FROM PUBLIC;
REVOKE ALL ON vm_demo_guard.identity FROM PUBLIC;
GRANT USAGE ON SCHEMA vm_demo_guard TO agentforge_demo;
GRANT SELECT ON vm_demo_guard.identity TO agentforge_demo;
SQL
