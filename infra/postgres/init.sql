-- Runs once at postgres container first start (docker-entrypoint-initdb.d),
-- with superuser rights. It only prepares extensions; every table lives in
-- Alembic migrations - bring a fresh database to the current schema with:
--   cd apps/api && alembic upgrade head
CREATE EXTENSION IF NOT EXISTS vector;
