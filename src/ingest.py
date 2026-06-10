"""Step 3 — Ingestion: ODS API -> Postgres (raw_bike_counts, counters, raw_chantiers).

Bulk pull via the ODS `/exports/json` endpoint (bypasses the /records 10k offset cap).
Bike data (~882k rows) is streamed with ijson and loaded via COPY in chunks so memory
stays flat. Chantiers (~5.3k rows) are small enough to load in one shot.

Run:
    python -m src.ingest
Idempotent: each loader truncates its target table(s) before loading.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time

import ijson
import requests
from psycopg2.extras import execute_batch
from shapely.geometry import shape

from .db import get_engine

API_BASE = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
BIKE_DS = "comptage-velo-donnees-compteurs"
CHANTIERS_DS = "chantiers-a-paris"

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
CHUNK_ROWS = 50_000


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _coords(obj):
    """Return (lon, lat) from a {lon,lat} dict or a [lat,lon] / [lon,lat] list."""
    if isinstance(obj, dict):
        return obj.get("lon"), obj.get("lat")
    if isinstance(obj, (list, tuple)) and len(obj) == 2:
        # ODS geo_point_2d lists are [lat, lon].
        return obj[1], obj[0]
    return None, None


def _fetch_to_file(dataset: str, dest: str, max_retries: int = 5) -> str:
    """Stream {API_BASE}/{dataset}/exports/json to dest, with exponential backoff."""
    url = f"{API_BASE}/{dataset}/exports/json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(max_retries):
        try:
            with requests.get(url, stream=True, timeout=(10, 300)) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
            size = os.path.getsize(dest)
            print(f"  downloaded {dataset} -> {dest} ({size/1e6:.1f} MB)", flush=True)
            return dest
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  [retry {attempt+1}/{max_retries}] {dataset}: {exc} -> sleep {wait}s",
                  flush=True)
            time.sleep(wait)
    raise RuntimeError(f"failed to download {dataset} after {max_retries} attempts")


# --------------------------------------------------------------------------- #
# (1) bike counts
# --------------------------------------------------------------------------- #
def ingest_bike(conn) -> int:
    """Load all hourly bike rows, then derive the distinct `counters` table."""
    cur = conn.cursor()
    cur.execute("TRUNCATE raw_bike_counts;")
    cur.execute("TRUNCATE counters;")
    conn.commit()

    path = _fetch_to_file(BIKE_DS, os.path.join(RAW_DIR, "bike.json"))

    copy_sql = (
        "COPY raw_bike_counts "
        "(id_compteur, nom_compteur, ts, sum_counts, installation_date, lon, lat) "
        "FROM STDIN WITH (FORMAT csv)"
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    n = chunk = 0

    def flush():
        nonlocal buf, writer, chunk
        if chunk == 0:
            return
        buf.seek(0)
        cur.copy_expert(copy_sql, buf)
        conn.commit()
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        chunk = 0

    with open(path, "rb") as f:
        for rec in ijson.items(f, "item"):
            lon, lat = _coords(rec.get("coordinates"))
            inst = rec.get("installation_date")
            inst = str(inst)[:10] if inst else None
            writer.writerow([
                rec.get("id_compteur"),
                rec.get("nom_compteur"),
                rec.get("date"),
                rec.get("sum_counts"),
                inst,
                lon,
                lat,
            ])
            n += 1
            chunk += 1
            if chunk >= CHUNK_ROWS:
                flush()
                if n % 200_000 == 0:
                    print(f"  ...loaded {n:,} bike rows", flush=True)
    flush()

    # Derive one row per counter (latest non-null coordinate), build point geom.
    cur.execute("""
        INSERT INTO counters (id_compteur, nom_compteur, installation_date, geom)
        SELECT DISTINCT ON (id_compteur)
               id_compteur, nom_compteur, installation_date,
               ST_SetSRID(ST_MakePoint(lon, lat), 4326)
        FROM raw_bike_counts
        WHERE lon IS NOT NULL AND lat IS NOT NULL
        ORDER BY id_compteur, ts DESC
        ON CONFLICT (id_compteur) DO NOTHING;
    """)
    conn.commit()
    print(f"  bike rows inserted: {n:,}", flush=True)
    return n


# --------------------------------------------------------------------------- #
# (2) chantiers
# --------------------------------------------------------------------------- #
def ingest_chantiers(conn) -> tuple[int, int]:
    """Load chantiers with point + polygon geometry. Returns (n_rows, n_multipolygon)."""
    cur = conn.cursor()
    cur.execute("TRUNCATE raw_chantiers;")
    conn.commit()

    path = _fetch_to_file(CHANTIERS_DS, os.path.join(RAW_DIR, "chantiers.json"))
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    sql = """
        INSERT INTO raw_chantiers
          (num_emprise, cp_arrondissement, date_debut, date_fin, surface,
           chantier_categorie, localisation_detail, geom_point, geom_poly)
        VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          CASE WHEN %s IS NULL OR %s IS NULL THEN NULL
               ELSE ST_SetSRID(ST_MakePoint(%s, %s), 4326) END,
          CASE WHEN %s IS NULL THEN NULL
               ELSE ST_SetSRID(ST_GeomFromText(%s), 4326) END
        )
        ON CONFLICT (num_emprise) DO NOTHING;
    """
    params = []
    n_multi = 0
    for r in rows:
        lon, lat = _coords(r.get("geo_point_2d"))

        # Polygon: column type is Polygon(4326); coerce MultiPolygon -> largest part.
        wkt = None
        gs = r.get("geo_shape")
        if gs:
            geom = gs.get("geometry") if isinstance(gs, dict) and "geometry" in gs else gs
            try:
                g = shape(geom)
                if g.geom_type == "Polygon":
                    wkt = g.wkt
                elif g.geom_type == "MultiPolygon":
                    wkt = max(g.geoms, key=lambda p: p.area).wkt
                    n_multi += 1
            except Exception:  # noqa: BLE001 - skip unparseable geometry, keep the row
                wkt = None

        loc = r.get("localisation_detail")
        if loc is None:
            loc = []
        elif isinstance(loc, str):
            loc = [loc]

        params.append((
            r.get("num_emprise"), r.get("cp_arrondissement"),
            r.get("date_debut"), r.get("date_fin"), r.get("surface"),
            r.get("chantier_categorie"), list(loc),
            lon, lat, lon, lat,
            wkt, wkt,
        ))

    execute_batch(cur, sql, params, page_size=500)
    conn.commit()
    print(f"  chantiers inserted: {len(params):,} "
          f"({n_multi} multipolygons coerced to largest part)", flush=True)
    return len(params), n_multi


# --------------------------------------------------------------------------- #
# entry point + acceptance checks
# --------------------------------------------------------------------------- #
def main() -> int:
    conn = get_engine().raw_connection()
    try:
        print("[1/2] bike counts...", flush=True)
        ingest_bike(conn)
        print("[2/2] chantiers...", flush=True)
        ingest_chantiers(conn)

        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM raw_bike_counts;")
        bike_rows = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM counters;")
        counters_all = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM counters WHERE geom IS NOT NULL;")
        counters_geom = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM raw_chantiers;")
        chantiers_all = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM raw_chantiers WHERE geom_point IS NOT NULL;")
        chantiers_geom = cur.fetchone()[0]

        print("\n================ INGESTION SUMMARY ================")
        print(f"raw_bike_counts rows.................. {bike_rows:,}")
        print(f"counters (total / with geom)......... {counters_all} / {counters_geom}")
        print(f"raw_chantiers (total / geom_point)... {chantiers_all:,} / {chantiers_geom:,}")
        print("==================================================")

        assert bike_rows > 800_000, f"expected ~882k bike rows, got {bike_rows}"
        assert 90 <= counters_geom <= 100, f"expected ~95 counters w/ geom, got {counters_geom}"
        assert counters_geom == counters_all, "some counters are missing geometry"
        assert chantiers_all > 5_000, f"expected ~5,331 chantiers, got {chantiers_all}"
        assert chantiers_geom > 5_000, f"expected ~5,331 chantiers w/ geom_point, got {chantiers_geom}"
        print("ACCEPTANCE: PASS")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
