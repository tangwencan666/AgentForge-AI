\getenv app_password APP_DB_PASSWORD
CREATE ROLE agentforge LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE agentforge OWNER TO agentforge;
\connect agentforge
ALTER SCHEMA public OWNER TO agentforge;
