-- Step 4: disruptive-chantier × counter candidate pairing.
-- Idempotent. Storage SRID 4326; distances computed in SRID 2154 (Lambert-93, metres).
-- Usage: psql "$DATABASE_URL" -f sql/02_spatial.sql
-- Acceptance: counts per radius band in the same ballpark as ≈92 (≤150m) / ≈222 (≤300m)
--             distinct chantiers once ≥21d pre/post padding is applied.

DROP TABLE IF EXISTS candidate_pairs CASCADE;

CREATE TABLE candidate_pairs AS
WITH disruptive AS (
    -- (1) is_disruptive: roadway/parking emprise OR surface >= 100 m².
    SELECT
        num_emprise,
        date_debut,
        date_fin,
        surface,
        geom_point,
        ( localisation_detail && ARRAY['EMPRISE_CHAUSSEE','EMPRISE_STATIONNEMENT']
          OR surface >= 100 ) AS is_disruptive
    FROM raw_chantiers
    WHERE geom_point IS NOT NULL
),
pairs AS (
    SELECT
        c.id_compteur,
        d.num_emprise AS chantier_id,
        d.date_debut,
        d.date_fin,
        ST_Distance(
            ST_Transform(c.geom, 2154),
            ST_Transform(d.geom_point, 2154)
        ) AS distance_m
    FROM counters c
    JOIN disruptive d
      ON d.is_disruptive
     -- temporal overlap with the bike window [2025-05-01, 2026-06-08]
     AND d.date_debut <= DATE '2026-06-08'
     AND d.date_fin   >= DATE '2025-05-01'
     -- keep pairs within 300m (metric, SRID 2154)
     AND ST_DWithin(
            ST_Transform(c.geom, 2154),
            ST_Transform(d.geom_point, 2154),
            300
         )
)
SELECT
    id_compteur,
    chantier_id,
    date_debut,
    date_fin,
    distance_m,
    CASE WHEN distance_m <= 150 THEN '150' ELSE '300' END AS radius_band,
    ((date_fin - date_debut) >= 60) AS long_site,
    -- ≥21d pre/post padding inside the window (Step-5 timing, surfaced here for the ballpark check)
    (date_debut BETWEEN DATE '2025-05-22' AND DATE '2026-05-18') AS debut_has_padding
FROM pairs;

CREATE INDEX IF NOT EXISTS candidate_pairs_counter_ix ON candidate_pairs (id_compteur);
CREATE INDEX IF NOT EXISTS candidate_pairs_chantier_ix ON candidate_pairs (chantier_id);

-- ----------------------------- ACCEPTANCE REPORT ----------------------------
\echo ''
\echo '== pairs by radius_band (150 = <=150m, 300 = 150-300m) =='
SELECT radius_band,
       count(*)                       AS pairs,
       count(DISTINCT chantier_id)    AS distinct_chantiers,
       count(DISTINCT id_compteur)    AS distinct_counters
FROM candidate_pairs
GROUP BY radius_band
ORDER BY radius_band;

\echo ''
\echo '== cumulative within radius (distinct chantiers / counters) =='
SELECT
    count(DISTINCT chantier_id) FILTER (WHERE distance_m <= 150) AS chantiers_le150,
    count(DISTINCT chantier_id)                                  AS chantiers_le300,
    count(DISTINCT id_compteur) FILTER (WHERE distance_m <= 150) AS counters_le150,
    count(DISTINCT id_compteur)                                  AS counters_le300
FROM candidate_pairs;

\echo ''
\echo '== BALLPARK vs verified (target ~92 @150m, ~222 @300m, with >=21d pre/post) =='
SELECT
    count(DISTINCT chantier_id) FILTER (WHERE distance_m <= 150 AND debut_has_padding) AS chantiers_le150_padded,
    count(DISTINCT chantier_id) FILTER (WHERE debut_has_padding)                       AS chantiers_le300_padded,
    count(*) FILTER (WHERE long_site)                                                  AS pairs_long_site
FROM candidate_pairs;
