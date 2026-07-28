-- 使用 psql 变量注入强随机密码：
-- psql -v api_password='...' -v worker_password='...' -v migration_password='...' -f deploy/postgres_roles.sql
\set ON_ERROR_STOP on

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opentrace_api') THEN
    CREATE ROLE opentrace_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opentrace_worker') THEN
    CREATE ROLE opentrace_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opentrace_migration') THEN
    CREATE ROLE opentrace_migration LOGIN NOSUPERUSER CREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;

ALTER ROLE opentrace_api PASSWORD :'api_password';
ALTER ROLE opentrace_worker PASSWORD :'worker_password';
ALTER ROLE opentrace_migration PASSWORD :'migration_password';
GRANT CONNECT ON DATABASE opentrace_v2 TO opentrace_api, opentrace_worker, opentrace_migration;
GRANT USAGE ON SCHEMA public TO opentrace_api, opentrace_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO opentrace_api, opentrace_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO opentrace_api, opentrace_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE opentrace_migration IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO opentrace_api, opentrace_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE opentrace_migration IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO opentrace_api, opentrace_worker;
