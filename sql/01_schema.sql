-- Step 2: schema for "Le Péage Invisible".
-- Idempotent: safe to re-run. Storage SRID = 4326 (metric distance done later in 2154).
-- Usage: psql "$DATABASE_URL" -f sql/01_schema.sql
-- Acceptance: all tables exist and are empty, with GIST indexes on geometry columns
--             and a btree index on raw_bike_counts(id_compteur, ts).

CREATE EXTENSION IF NOT EXISTS postgis;

-- Drop in any order; CASCADE clears dependent objects/indexes.
DROP TABLE IF EXISTS model_panel CASCADE;
DROP TABLE IF EXISTS treatment_assignment CASCADE;
DROP TABLE IF EXISTS daily_counts CASCADE;
DROP TABLE IF EXISTS raw_chantiers CASCADE;
DROP TABLE IF EXISTS counters CASCADE;
DROP TABLE IF EXISTS raw_bike_counts CASCADE;

-- ---------------------------------------------------------------------------
-- Raw hourly bike counts (Dataset A, as ingested). No geometry here; the point
-- lives on `counters`. PK-less on purpose: raw landing table.
-- ---------------------------------------------------------------------------
CREATE TABLE raw_bike_counts (
    id_compteur        text,
    nom_compteur       text,
    ts                 timestamptz,
    sum_counts         int,
    installation_date  date,
    lon                double precision,
    lat                double precision
);

-- ---------------------------------------------------------------------------
-- One row per physical counter, with its point geometry (SRID 4326).
-- ---------------------------------------------------------------------------
CREATE TABLE counters (
    id_compteur        text PRIMARY KEY,
    nom_compteur       text,
    installation_date  date,
    geom               geometry(Point, 4326)
);

-- ---------------------------------------------------------------------------
-- Raw chantiers (Dataset B). localisation_detail kept as a text[] for the
-- disruptive-emprise filter. Point + polygon geometry (SRID 4326).
-- NOTE: geo_shape may arrive as MultiPolygon; ingestion (Step 3) must normalise
-- to Polygon (e.g. ST_CollectionExtract/ST_GeometryN) to match this column type.
-- ---------------------------------------------------------------------------
CREATE TABLE raw_chantiers (
    num_emprise         text PRIMARY KEY,
    cp_arrondissement   text,
    date_debut          date,
    date_fin            date,
    surface             numeric,
    chantier_categorie  text,
    localisation_detail text[],
    geom_point          geometry(Point, 4326),
    geom_poly           geometry(Polygon, 4326)
);

-- ---------------------------------------------------------------------------
-- Daily aggregated counts per counter (Step 6 output).
-- ---------------------------------------------------------------------------
CREATE TABLE daily_counts (
    id_compteur       text,
    day               date,
    total_count       bigint,
    n_hours_observed  int,
    PRIMARY KEY (id_compteur, day)
);

-- ---------------------------------------------------------------------------
-- Treatment / control assignment per counter (Step 5 output).
-- grp ∈ {treated, control, excluded}.
-- ---------------------------------------------------------------------------
CREATE TABLE treatment_assignment (
    id_compteur   text PRIMARY KEY,
    grp           text,
    event_date    date,
    chantier_id   text,
    distance_m    numeric
);

-- ---------------------------------------------------------------------------
-- Analysis-ready counter × day panel (Step 6/7 output).
-- ---------------------------------------------------------------------------
CREATE TABLE model_panel (
    id_compteur       text,
    day               date,
    total_count       bigint,
    n_hours_observed  int,
    grp               text,
    event_date        date,
    rel_day           int,
    post              int,
    treated           int,
    dow               int,
    month             int,
    is_holiday        boolean,
    PRIMARY KEY (id_compteur, day)
);

-- ---------------------------------------------------------------------------
-- Indexes: GIST on every geometry column + btree on the raw hourly lookup key.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS counters_geom_gix
    ON counters USING GIST (geom);
CREATE INDEX IF NOT EXISTS raw_chantiers_geom_point_gix
    ON raw_chantiers USING GIST (geom_point);
CREATE INDEX IF NOT EXISTS raw_chantiers_geom_poly_gix
    ON raw_chantiers USING GIST (geom_poly);
CREATE INDEX IF NOT EXISTS raw_bike_counts_id_ts_bix
    ON raw_bike_counts (id_compteur, ts);
