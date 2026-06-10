-- Step 1: enable PostGIS. Run once against the target database.
-- Usage: psql "$DATABASE_URL" -f sql/00_init.sql
CREATE EXTENSION IF NOT EXISTS postgis;
