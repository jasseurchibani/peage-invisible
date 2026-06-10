# 🛠️ Le Péage Invisible — Implementation Plan (Python + PostgreSQL/PostGIS)

**Goal:** Prove *causally* whether disruptive construction sites (chantiers) suppress cycling traffic at nearby Paris bike counters, and quantify the effect ("−X passages/day"), using a Difference-in-Differences / event-study natural experiment.

**Stack:** Python · PostgreSQL + PostGIS · ODS v2.1 open-data API.

---

## 0. Shared context (prepend this to every step prompt)

> **Project:** "Le Péage Invisible" — causal study (Difference-in-Differences / event-study), NOT descriptive.
> **API base:** `https://opendata.paris.fr/api/explore/v2.1/catalog/datasets` (key-free JSON; `/records` caps limit=100 & offset≤9900 → use `/exports/json` for bulk).
> **Dataset A — `comptage-velo-donnees-compteurs`:** ~882,530 hourly rows, window 2025-05-01 → 2026-06-08, 95 counters. Fields: `id_compteur, nom_compteur, sum_counts, date (hourly ISO), installation_date, coordinates ({lon,lat}), mois_annee_comptage`.
> **Dataset B — `chantiers-a-paris`:** 5,331 rows. Fields: `num_emprise, cp_arrondissement, date_debut, date_fin, chantier_categorie, moa_principal, surface (m²), chantier_synthese, localisation_detail (array, e.g. ["EMPRISE_CHAUSSEE"]), geo_shape (polygon), geo_point_2d ({lon,lat})`. **There is NO "perturbant" flag — "disruptive" must be defined by us** (roadway/parking emprise `EMPRISE_CHAUSSEE`/`STATIONNEMENT`, and/or `surface` threshold).
> **Pre-verified feasibility (design assumptions):** 92 usable treatment events at 150m radius, 222 at 300m, with ≥21 days pre/post; 56 of 95 counters treated, 39 never-treated controls.
> **Design rules:** radius R = 150m primary / 300m sensitivity · aggregate hourly→daily · event t=0 = first qualifying chantier opening · exclude control counters within 500m of ANY chantier (spillover/SUTVA) · handle counter outages (never read missing as zero) · prefer chantiers ≥60 days · run parallel-trends + placebo tests · all SRIDs: 4326 for storage, 2154 (Lambert-93) for metric distance.

---

## 🧭 Architecture overview

```
ODS API ──(requests)──> raw_* tables ──(PostGIS spatial+temporal join)──> treatment_assignment
                                   │
            counters / daily_counts ┘
                                   ▼
                         model_panel (counter × day, relative-time)
                                   ▼
                 Python (statsmodels / linearmodels) ── DiD / event-study
                                   ▼
                         figures/ (divergence chart, event-study plot, map)
                                   ▼
                              deliverable (report + notebook)
```

**Repo structure**
```
peage-invisible/
├── .env                  # DB creds (never commit)
├── requirements.txt
├── sql/                  # DDL + PostGIS transforms
├── src/
│   ├── ingest.py         # API → Postgres
│   ├── spatial.py        # distance join, treatment def
│   ├── panel.py          # daily aggregation, outage handling
│   ├── model.py          # DiD / event-study
│   └── viz.py            # figures
├── data/{raw,processed}/
├── figures/
├── outputs/              # model tables, coefficients
└── notebooks/analysis.ipynb
```

**PostgreSQL tables**
| Table | Purpose | Key |
|---|---|---|
| `raw_bike_counts` | hourly counts as ingested | (id_compteur, ts) |
| `counters` | 1 row/counter + point geom | id_compteur |
| `raw_chantiers` | chantiers + point & polygon geom | num_emprise |
| `daily_counts` | counter×day totals + hours observed | (id_compteur, day) |
| `treatment_assignment` | event date, nearest chantier, distance, group | (id_compteur) |
| `model_panel` | analysis-ready counter×day with relative time | (id_compteur, day) |

---

## Step 1 — Environment & repository scaffold

**What & why:** Stand up a reproducible workspace before touching data: Python virtualenv with pinned deps, a running PostgreSQL instance with the PostGIS extension enabled, `.env`-based DB credentials, and the folder/module skeleton above. Output: a repo that imports cleanly and a DB connection test that succeeds. Done when `python -c "import geopandas, sqlalchemy, statsmodels"` works and `SELECT postgis_version();` returns a version.

**Tools:** Python venv, `pip`, `requirements.txt` (requests, pandas, geopandas, shapely, sqlalchemy, psycopg2-binary, statsmodels, linearmodels, matplotlib, plotly, python-dotenv), PostgreSQL ≥14, PostGIS extension, `.env` + python-dotenv.

> **Agent prompt — Step 1**
> *(Prepend Section 0 "Shared context".)*
> Create the project scaffold for "Le Péage Invisible". Generate: (1) the folder structure `sql/ src/ data/raw data/processed figures/ outputs/ notebooks/` with empty module files `src/{ingest,spatial,panel,model,viz}.py`; (2) a `requirements.txt` pinning requests, pandas, geopandas, shapely, sqlalchemy, psycopg2-binary, statsmodels, linearmodels, matplotlib, plotly, python-dotenv; (3) a `.env.example` with `PGHOST,PGPORT,PGDATABASE,PGUSER,PGPASSWORD`; (4) `src/db.py` exposing a `get_engine()` SQLAlchemy helper that reads `.env`; (5) a `sql/00_init.sql` that runs `CREATE EXTENSION IF NOT EXISTS postgis;`. Then write a `make check` / `python -m src.db` smoke test that connects and prints `postgis_version()`. Do not download data yet. Acceptance: the smoke test prints a PostGIS version string.

---

## Step 2 — Database schema (PostGIS)

**What & why:** Define the tables above with correct types, geometry columns (SRID 4326), and GIST spatial indexes, plus a projected geometry (SRID 2154) for metric distance. A clean schema up front prevents ad-hoc CSV juggling and lets PostGIS do the spatial join natively. Done when all tables exist, are empty, and `\d+` shows GIST indexes on geometry columns.

**Tools:** PostgreSQL DDL, PostGIS (`geometry(Point,4326)`, `geometry(Polygon,4326)`, `ST_Transform`, GIST index), SQL migration file `sql/01_schema.sql`.

> **Agent prompt — Step 2**
> *(Prepend Section 0.)*
> Write `sql/01_schema.sql` creating these tables with PostGIS geometry columns in SRID 4326 and GIST indexes: `raw_bike_counts(id_compteur text, nom_compteur text, ts timestamptz, sum_counts int, installation_date date, lon double precision, lat double precision)`; `counters(id_compteur text primary key, nom_compteur text, installation_date date, geom geometry(Point,4326))`; `raw_chantiers(num_emprise text primary key, cp_arrondissement text, date_debut date, date_fin date, surface numeric, chantier_categorie text, localisation_detail text[], geom_point geometry(Point,4326), geom_poly geometry(Polygon,4326))`; `daily_counts(id_compteur text, day date, total_count bigint, n_hours_observed int, primary key(id_compteur,day))`; `treatment_assignment(id_compteur text primary key, grp text, event_date date, chantier_id text, distance_m numeric)`; `model_panel(id_compteur text, day date, total_count bigint, n_hours_observed int, grp text, event_date date, rel_day int, post int, treated int, dow int, month int, is_holiday boolean, primary key(id_compteur,day))`. Add GIST indexes on every geometry column and a btree index on `raw_bike_counts(id_compteur, ts)`. Make it idempotent (`DROP TABLE IF EXISTS ... CASCADE`). Acceptance: running the file leaves all tables empty with indexes present.

---

## Step 3 — Ingestion: API → Postgres

**What & why:** Pull both datasets in full from the ODS `/exports/json` endpoint (bypasses the 10k offset cap), normalize fields, derive geometry from `coordinates`/`geo_point_2d`/`geo_shape`, and load into `raw_bike_counts`, `counters`, and `raw_chantiers`. This is the only network step; everything downstream reads Postgres. Done when row counts ≈ 882k bike rows, 95 counters, ~5,331 chantiers, and geometry is non-null.

**Tools:** Python `requests` (streamed `/exports/json`), `pandas`, `shapely` (build points/polygons), `geopandas` (optional), SQLAlchemy `to_sql` / `COPY` for bulk load, `src/ingest.py`.

> **Agent prompt — Step 3**
> *(Prepend Section 0.)*
> Implement `src/ingest.py` with three functions. (1) `ingest_bike()` — fetch the full `comptage-velo-donnees-compteurs` dataset via `GET {API_base}/comptage-velo-donnees-compteurs/exports/json`, parse `coordinates` into `lon/lat`, insert all hourly rows into `raw_bike_counts`, then populate `counters` as the distinct `(id_compteur, nom_compteur, installation_date)` with `geom = ST_SetSRID(ST_MakePoint(lon,lat),4326)`. (2) `ingest_chantiers()` — fetch `chantiers-a-paris/exports/json`, keep the listed fields, store `localisation_detail` as a Postgres `text[]`, build `geom_point` from `geo_point_2d` and `geom_poly` from `geo_shape`, insert into `raw_chantiers`. Use chunked inserts/`COPY` for the ~882k bike rows; retry transient HTTP errors with backoff; be idempotent (truncate-then-load). Acceptance: print final counts and assert ~882k bike rows, 95 counters with non-null geom, and ~5,331 chantiers with non-null `geom_point`.

---

## Step 4 — Spatial + temporal join & treatment definition

**What & why:** Define "disruptive" from `localisation_detail`/`surface`, then for every counter find qualifying chantiers within radius R using PostGIS `ST_DWithin` on projected geometry (SRID 2154, metres), keeping the temporal overlap with the bike window. This produces the candidate counter–chantier pairs with true metric distances. Done when a pairs table reproduces the verified feasibility (~92 pairs at 150m, ~222 at 300m).

**Tools:** PostGIS `ST_Transform`, `ST_DWithin`, `ST_Distance` (geometry in SRID 2154), SQL array filtering on `localisation_detail`, `sql/02_spatial.sql` or `src/spatial.py`.

> **Agent prompt — Step 4**
> *(Prepend Section 0.)*
> Create the disruptive-chantier × counter pairing. (1) Define a SQL boolean `is_disruptive` = `localisation_detail && ARRAY['EMPRISE_CHAUSSEE','EMPRISE_STATIONNEMENT']` OR `surface >= 100`. (2) Build a `candidate_pairs` table: for each counter and each disruptive chantier whose `[date_debut,date_fin]` overlaps 2025-05-01..2026-06-08, compute `distance_m = ST_Distance(ST_Transform(counter.geom,2154), ST_Transform(chantier.geom_point,2154))` and keep pairs with `ST_DWithin(...,2154 versions...,300)`. Add a `radius_band` column (`'150'` if ≤150 else `'300'`) and a `long_site` flag (`date_fin-date_debut >= 60`). Acceptance: report counts per radius band and confirm they are in the same ballpark as the verified figures (≈92 within 150m, ≈222 within 300m with ≥21d pre/post once Step 5 timing is applied).

---

## Step 5 — Treatment assignment & control group (spillover-safe)

**What & why:** Collapse candidate pairs to one event per counter (t=0 = earliest qualifying `date_debut` with ≥21 days of pre/post inside the window). Tag the 39 never-treated counters as controls, then **drop any control within 500m of *any* chantier** to kill diversion contamination (SUTVA). Output: `treatment_assignment` with `grp ∈ {treated, control, excluded}`. Done when treated/control/excluded counts are sensible and no control sits within 500m of a chantier.

**Tools:** PostGIS `ST_DWithin` (500m), SQL window functions (`MIN(date_debut)` per counter), `src/spatial.py`.

> **Agent prompt — Step 5**
> *(Prepend Section 0.)*
> Populate `treatment_assignment`. (1) For each counter with ≥1 candidate pair, set `grp='treated'`, `event_date = MIN(date_debut)` among its qualifying disruptive chantiers where `date_debut` is between window_start+21d and window_end−21d; record the nearest such `chantier_id` and `distance_m`. Use the 150m band as primary; keep 300m available for sensitivity. (2) Counters with no qualifying chantier → candidate controls. (3) Mark a candidate control as `grp='excluded'` if it lies within 500m (`ST_DWithin`, SRID 2154) of ANY chantier active in the window; otherwise `grp='control'`. Acceptance: print the breakdown (expect ~56 treated, 39 controls before exclusion, fewer after), and assert zero `control` counters are within 500m of any chantier.

---

## Step 6 — Panel construction (daily, outage-aware)

**What & why:** Aggregate hourly counts to a counter×day panel, record `n_hours_observed` per day, and mark/drop low-coverage days instead of imputing zeros (a counter offline ≠ zero cyclists — this is the integrity move the brief rewards). Attach `grp`, `event_date`, `rel_day` (days since event), `post`, `treated`, and calendar controls. Output: `model_panel`. Done when each treated counter has both pre and post days and outage days are flagged not zeroed.

**Tools:** SQL aggregation (`date_trunc`, `GROUP BY`), Python `pandas` for calendar features + French holidays (`holidays` lib or a static list), `src/panel.py`.

> **Agent prompt — Step 6**
> *(Prepend Section 0.)*
> Build `model_panel`. (1) From `raw_bike_counts`, aggregate to `(id_compteur, day)` with `total_count = SUM(sum_counts)` and `n_hours_observed = COUNT(*)`. (2) Flag `low_coverage = n_hours_observed < 20` and EXCLUDE those rows from modeling (do NOT impute zeros); document how many were dropped. (3) Join `treatment_assignment` to attach `grp, event_date`; compute `rel_day = day - event_date`, `post = (rel_day >= 0)`, `treated = (grp='treated')`. (4) Add `dow`, `month`, and `is_holiday` (French public + school holidays). Acceptance: assert every treated counter has ≥21 valid pre days and ≥21 valid post days; print the count of dropped low-coverage rows.

---

## Step 7 — EDA & parallel-trends check

**What & why:** Before trusting DiD, verify the identifying assumption: treated and control daily counts should move in parallel *before* t=0. Plot raw and normalized series, and an event-study lead plot whose pre-period coefficients should be ≈0. This is the honesty gate — if pre-trends diverge, the design is reported as weaker. Done when a parallel-trends figure and a leads table exist and are interpreted in plain language.

**Tools:** `pandas`, `matplotlib`/`plotly`, a preliminary `linearmodels.PanelOLS` event-study spec for the leads, `notebooks/analysis.ipynb`.

> **Agent prompt — Step 7**
> *(Prepend Section 0.)*
> Do exploratory + assumption checks on `model_panel`. (1) Plot mean daily counts for treated vs control over calendar time, and a version indexed to each treated counter's `rel_day` (event time). (2) Estimate a preliminary event-study with leads `rel_day ∈ [-8..-1 weeks]` and lags `[0..+8 weeks]` (bin to weeks), counter + week fixed effects, SE clustered by counter; plot the coefficient path with CIs. (3) State in one plain sentence whether pre-period leads are statistically indistinguishable from zero (parallel-trends supported) or not. Acceptance: save `figures/parallel_trends.png` and `figures/event_study_pre.png`, and output a short written verdict on the assumption.

---

## Step 8 — DiD / event-study estimation

**What & why:** Estimate the causal effect: two-way fixed-effects DiD (counter FE + day FE) with `post×treated`, calendar controls, SE clustered by counter; plus the full event-study for dynamics. Because adoption is staggered, also run a robust modern estimator (Callaway–Sant'Anna or not-yet-treated controls) and compare. Output: effect size in passages/day and %, with CIs. Done when a coefficient table + event-study plot are saved and the headline number is stated with uncertainty.

**Tools:** `linearmodels.PanelOLS` (TWFE), `statsmodels`, optionally `differences`/`csdid`-style estimator (Callaway–Sant'Anna), `src/model.py`, `outputs/`.

> **Agent prompt — Step 8**
> *(Prepend Section 0.)*
> Estimate the treatment effect on `model_panel`. (1) TWFE DiD: `log1p(total_count) ~ post*treated + C(dow) + is_holiday` with entity (counter) and time (day) fixed effects, cluster SE by counter; report β for `post:treated` as % change and back-transform to passages/day at the mean. (2) Full event-study with weekly leads/lags for dynamics. (3) Robustness to staggered timing: re-estimate using a Callaway–Sant'Anna style group-time ATT (or restrict controls to not-yet-treated) and compare to TWFE. Save coefficient tables to `outputs/` and an event-study plot to `figures/`. Acceptance: print the headline effect as "−X passages/day (−Y%), 95% CI [..]" and note whether TWFE and the robust estimator agree.

---

## Step 9 — Robustness & placebo battery

**What & why:** Stress-test the result so the jury can't poke a hole: placebo event dates (expect null), radius sensitivity (150 vs 300m), long-site subset (≥60 days), alternative "disruptive" definitions, and leave-one-counter-out. Reporting these *especially when one fails* is what separates a professional from a student. Done when a results table summarizes every robustness variant with its effect + CI.

**Tools:** `src/model.py` parameterized runs, `pandas` results table, `matplotlib`, `outputs/robustness.csv`.

> **Agent prompt — Step 9**
> *(Prepend Section 0.)*
> Run the robustness battery and assemble one comparison table. Variants: (a) **placebo** — shift each event_date back 120 days onto pre-period and re-estimate (effect should be ≈0); (b) **radius** — 150m vs 300m; (c) **long sites only** (`date_fin-date_debut ≥ 60`); (d) **alt disruptive definition** — roadway-only vs surface-threshold-only; (e) **leave-one-out** over treated counters to check no single site drives the result. For each, output effect %, passages/day, CI, and N. Save `outputs/robustness.csv` and `figures/robustness_forest.png` (forest plot). Acceptance: the placebo effect is statistically indistinguishable from zero while the main effect survives ≥3 of the other variants; flag honestly if not.

---

## Step 10 — Headline visualization & deliverable

**What & why:** Produce the one chart a novice reads in seconds — treated vs control daily counts aligned at t=0, diverging after the chantier opens, gap shaded and labeled "−X passages/day" — plus a counter map and the event-study plot, then assemble a short, plain-language report stating H₀/H₁, the effect with uncertainty, the spillover/parallel-trends caveats, and the live API code. Done when `figures/` holds the three figures and a clean report (PDF/notebook/slide) tells the story end-to-end.

**Tools:** `plotly`/`matplotlib` (divergence chart + event-study), `geopandas`+`folium`/`plotly` (counter map), `notebooks/analysis.ipynb` → export, Markdown/PowerPoint for the report.

> **Agent prompt — Step 10**
> *(Prepend Section 0.)*
> Build the final deliverable. (1) Headline figure: two lines (mean daily count, treated vs control) on event-time `rel_day`, a vertical line at t=0, the post-period gap shaded and annotated with the Step-8 effect ("−X passages/day, −Y%"). (2) A Paris map of treated (red) vs control (blue) counters with chantier locations. (3) The event-study coefficient plot. (4) A 1–2 page plain-French report: state H₀/H₁; show one real `requests.get(...)` API call; report the effect with its 95% CI; include explicit uncertainty/caveat sentences (spillover, parallel-trends result, staggered-DiD note); end each figure with a one-sentence "so what". Acceptance: a non-technical reader can state the conclusion and its main caveat after 30 seconds with the headline figure alone.

---

## ⚠️ Risks & assumptions
- **No native "perturbant" flag** → disruption is a defined proxy; report sensitivity to the definition (Step 9d).
- **Spillover (SUTVA):** diverted cyclists may inflate nearby controls → mitigated by the 500m control-exclusion (Step 5); residual risk attenuates the effect toward zero (conservative).
- **Staggered adoption** can bias naïve TWFE → cross-checked with a Callaway–Sant'Anna-style estimator (Step 8).
- **Counter outages** must never be read as zeros → low-coverage days dropped, not imputed (Step 6).
- **Selection:** chantiers may be sited on busy corridors → counter fixed effects absorb level differences; parallel-trends check (Step 7) tests what remains.

## ✅ Definition of done
- [ ] Postgres holds ~882k bike rows, 95 counters, ~5,331 chantiers, all with valid geometry.
- [ ] `treatment_assignment`: ~56 treated, clean spillover-safe controls, zero controls within 500m of a chantier.
- [ ] `model_panel`: every treated counter has ≥21 valid pre and post days; outages dropped not zeroed.
- [ ] Parallel-trends checked and reported (pass/fail stated).
- [ ] Headline effect reported as "−X passages/day (−Y%), 95% CI [..]", agreeing across TWFE and a robust DiD estimator.
- [ ] Placebo ≈ 0; main effect survives radius/long-site/alt-definition/leave-one-out.
- [ ] Three figures + a plain-French report a novice understands in 30 seconds, with API code and explicit uncertainty.
