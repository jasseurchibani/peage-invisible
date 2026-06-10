-- Step 5: treatment / control / excluded assignment (one row per counter).
-- Idempotent. Primary band = 150m; 300m kept in candidate_pairs for sensitivity.
-- Usage: psql "$DATABASE_URL" -f sql/03_treatment.sql
-- Acceptance: print grp breakdown; assert zero 'control' counters lie within 500m
--             (SRID 2154) of ANY chantier active in the window.

TRUNCATE treatment_assignment;

-- (1) TREATED: counters with >=1 qualifying pair (<=150m AND >=21d pre/post padding).
--     event_date = earliest qualifying chantier opening (t=0 per design rule).
--     chantier_id / distance_m = the NEAREST qualifying chantier (metadata).
WITH qualifying AS (
    SELECT id_compteur, chantier_id, date_debut, distance_m
    FROM candidate_pairs
    WHERE distance_m <= 150
      AND debut_has_padding
),
event AS (
    SELECT id_compteur, MIN(date_debut) AS event_date
    FROM qualifying
    GROUP BY id_compteur
),
nearest AS (
    SELECT DISTINCT ON (id_compteur)
           id_compteur, chantier_id, distance_m
    FROM qualifying
    ORDER BY id_compteur, distance_m ASC
)
INSERT INTO treatment_assignment (id_compteur, grp, event_date, chantier_id, distance_m)
SELECT e.id_compteur, 'treated', e.event_date, n.chantier_id, n.distance_m
FROM event e
JOIN nearest n USING (id_compteur);

-- (2)/(3) CONTROLS: every remaining counter. Mark 'excluded' if within 500m of ANY
--     chantier active in the window (spillover/SUTVA), else 'control'.
INSERT INTO treatment_assignment (id_compteur, grp, event_date, chantier_id, distance_m)
SELECT
    c.id_compteur,
    CASE WHEN EXISTS (
        SELECT 1
        FROM raw_chantiers ch
        WHERE ch.geom_point IS NOT NULL
          AND ch.date_debut <= DATE '2026-06-08'
          AND ch.date_fin   >= DATE '2025-05-01'
          AND ST_DWithin(ST_Transform(c.geom, 2154),
                         ST_Transform(ch.geom_point, 2154), 500)
    ) THEN 'excluded' ELSE 'control' END AS grp,
    NULL, NULL, NULL
FROM counters c
WHERE NOT EXISTS (
    SELECT 1 FROM treatment_assignment ta WHERE ta.id_compteur = c.id_compteur
);

-- ----------------------------- ACCEPTANCE REPORT ----------------------------
\echo ''
\echo '== group breakdown =='
SELECT grp, count(*) AS counters
FROM treatment_assignment
GROUP BY grp
ORDER BY grp;

\echo ''
\echo '== candidate controls before/after 500m exclusion =='
SELECT
    count(*) FILTER (WHERE grp IN ('control','excluded')) AS candidate_controls_before,
    count(*) FILTER (WHERE grp = 'control')               AS controls_after,
    count(*) FILTER (WHERE grp = 'excluded')              AS excluded_by_spillover
FROM treatment_assignment;

-- Hard assertion: no 'control' may sit within 500m of any active chantier.
DO $$
DECLARE bad int;
BEGIN
    SELECT count(*) INTO bad
    FROM treatment_assignment ta
    JOIN counters c USING (id_compteur)
    WHERE ta.grp = 'control'
      AND EXISTS (
          SELECT 1 FROM raw_chantiers ch
          WHERE ch.geom_point IS NOT NULL
            AND ch.date_debut <= DATE '2026-06-08'
            AND ch.date_fin   >= DATE '2025-05-01'
            AND ST_DWithin(ST_Transform(c.geom, 2154),
                           ST_Transform(ch.geom_point, 2154), 500)
      );
    IF bad > 0 THEN
        RAISE EXCEPTION 'ACCEPTANCE FAILED: % control counters within 500m of a chantier', bad;
    END IF;
    RAISE NOTICE 'ACCEPTANCE OK: 0 control counters within 500m of any chantier';
END $$;
