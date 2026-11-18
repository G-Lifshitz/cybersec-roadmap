-- Local SQL Server setup for docker compose. Idempotent: safe on every `up`.
--
-- Creates one database per service plus a test database for each, and one
-- login per service that can reach only its own databases. This mirrors Azure,
-- where each service has its own database and its own contained user (see
-- infra/azure-setup.sh); tables are created by each service's migrations, not here.
--
-- Passwords arrive as sqlcmd variables from compose (-v), never written here.

IF DB_ID('roadmap_db') IS NULL CREATE DATABASE roadmap_db;
IF DB_ID('roadmap_test') IS NULL CREATE DATABASE roadmap_test;
IF DB_ID('progress_db') IS NULL CREATE DATABASE progress_db;
IF DB_ID('progress_test') IS NULL CREATE DATABASE progress_test;
GO

IF SUSER_ID('roadmap_svc') IS NULL
    CREATE LOGIN roadmap_svc WITH PASSWORD = '$(ROADMAP_DB_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN roadmap_svc WITH PASSWORD = '$(ROADMAP_DB_PASSWORD)';
IF SUSER_ID('progress_svc') IS NULL
    CREATE LOGIN progress_svc WITH PASSWORD = '$(PROGRESS_DB_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN progress_svc WITH PASSWORD = '$(PROGRESS_DB_PASSWORD)';
GO

-- Same three roles as on Azure: create/alter tables (migrations), read, write.
USE roadmap_db;
IF USER_ID('roadmap_svc') IS NULL CREATE USER roadmap_svc FOR LOGIN roadmap_svc;
ALTER ROLE db_ddladmin ADD MEMBER roadmap_svc;
ALTER ROLE db_datareader ADD MEMBER roadmap_svc;
ALTER ROLE db_datawriter ADD MEMBER roadmap_svc;
GO
USE roadmap_test;
IF USER_ID('roadmap_svc') IS NULL CREATE USER roadmap_svc FOR LOGIN roadmap_svc;
ALTER ROLE db_ddladmin ADD MEMBER roadmap_svc;
ALTER ROLE db_datareader ADD MEMBER roadmap_svc;
ALTER ROLE db_datawriter ADD MEMBER roadmap_svc;
GO
USE progress_db;
IF USER_ID('progress_svc') IS NULL CREATE USER progress_svc FOR LOGIN progress_svc;
ALTER ROLE db_ddladmin ADD MEMBER progress_svc;
ALTER ROLE db_datareader ADD MEMBER progress_svc;
ALTER ROLE db_datawriter ADD MEMBER progress_svc;
GO
USE progress_test;
IF USER_ID('progress_svc') IS NULL CREATE USER progress_svc FOR LOGIN progress_svc;
ALTER ROLE db_ddladmin ADD MEMBER progress_svc;
ALTER ROLE db_datareader ADD MEMBER progress_svc;
ALTER ROLE db_datawriter ADD MEMBER progress_svc;
GO
