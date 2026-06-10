"""Step 6 — Panel construction: hourly -> daily counter panel, outage-aware.

Builds two tables:
  * daily_counts : ALL (id_compteur, day) aggregates with n_hours_observed.
  * model_panel  : analysis-ready rows (low-coverage days EXCLUDED, never zero-imputed),
                   with treatment metadata + calendar controls.

Daily aggregation uses Europe/Paris local days (bike timestamps are stored UTC).

French public + Zone-C (Paris) school holidays are verified from the Éducation
Nationale open calendar (fr-en-calendrier-scolaire) for the study window.

Run:
    python -m src.panel
"""
from __future__ import annotations

import datetime as dt

from .db import get_engine

LOW_COVERAGE_HOURS = 20  # days with < this many observed hours are dropped from modeling

# --- French public holidays (jours fériés) in 2025-05-01 .. 2026-06-08 ---------
PUBLIC_HOLIDAYS = [
    "2025-05-01", "2025-05-08", "2025-05-29", "2025-06-09", "2025-07-14",
    "2025-08-15", "2025-11-01", "2025-11-11", "2025-12-25",
    "2026-01-01", "2026-04-06", "2026-05-01", "2026-05-08", "2026-05-14", "2026-05-25",
]

# --- Zone C (Paris) school-holiday ranges, inclusive [start, end] --------------
# Source: data.education.gouv.fr/fr-en-calendrier-scolaire (Zone C), verified live.
SCHOOL_RANGES = [
    ("2025-05-28", "2025-06-01"),  # Pont de l'Ascension
    ("2025-07-04", "2025-08-31"),  # Vacances d'Été
    ("2025-10-17", "2025-11-02"),  # Toussaint
    ("2025-12-19", "2026-01-04"),  # Noël
    ("2026-02-20", "2026-03-08"),  # Hiver
    ("2026-04-17", "2026-05-03"),  # Printemps
    ("2026-05-13", "2026-05-17"),  # Pont de l'Ascension
]


def _holiday_dates() -> list[str]:
    """Union of public holidays + expanded school ranges, as 'YYYY-MM-DD' strings."""
    days: set[dt.date] = {dt.date.fromisoformat(d) for d in PUBLIC_HOLIDAYS}
    for start, end in SCHOOL_RANGES:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        d = a
        while d <= b:
            days.add(d)
            d += dt.timedelta(days=1)
    return sorted(d.isoformat() for d in days)


def build_panel(conn) -> None:
    cur = conn.cursor()

    # (1) daily aggregate (ALL days), Europe/Paris local day.
    cur.execute("TRUNCATE daily_counts;")
    cur.execute("""
        INSERT INTO daily_counts (id_compteur, day, total_count, n_hours_observed)
        SELECT id_compteur,
               (ts AT TIME ZONE 'Europe/Paris')::date AS day,
               SUM(sum_counts)::bigint,
               COUNT(*)::int
        FROM raw_bike_counts
        WHERE id_compteur IS NOT NULL AND ts IS NOT NULL
        GROUP BY id_compteur, (ts AT TIME ZONE 'Europe/Paris')::date;
    """)

    # (2-4) model_panel: exclude low-coverage rows; attach treatment + calendar features.
    holidays = _holiday_dates()
    cur.execute("TRUNCATE model_panel;")
    cur.execute("""
        INSERT INTO model_panel
          (id_compteur, day, total_count, n_hours_observed, grp, event_date,
           rel_day, post, treated, dow, month, is_holiday)
        SELECT
            dc.id_compteur, dc.day, dc.total_count, dc.n_hours_observed,
            ta.grp, ta.event_date,
            (dc.day - ta.event_date)                                   AS rel_day,
            CASE WHEN ta.event_date IS NOT NULL AND dc.day >= ta.event_date
                 THEN 1 ELSE 0 END                                     AS post,
            CASE WHEN ta.grp = 'treated' THEN 1 ELSE 0 END             AS treated,
            EXTRACT(DOW   FROM dc.day)::int                            AS dow,
            EXTRACT(MONTH FROM dc.day)::int                            AS month,
            (dc.day = ANY(%(holidays)s::date[]))                       AS is_holiday
        FROM daily_counts dc
        LEFT JOIN treatment_assignment ta USING (id_compteur)
        WHERE dc.n_hours_observed >= %(thresh)s;
    """, {"holidays": holidays, "thresh": LOW_COVERAGE_HOURS})
    conn.commit()


def report_and_assert(conn) -> int:
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM daily_counts;")
    daily_all = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM daily_counts WHERE n_hours_observed < %s;",
                (LOW_COVERAGE_HOURS,))
    dropped = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM model_panel;")
    panel_rows = cur.fetchone()[0]

    # Per-treated-counter valid pre/post day counts.
    cur.execute("""
        SELECT ta.id_compteur,
               count(*) FILTER (WHERE mp.rel_day < 0)  AS pre_days,
               count(*) FILTER (WHERE mp.rel_day >= 0) AS post_days
        FROM treatment_assignment ta
        JOIN model_panel mp USING (id_compteur)
        WHERE ta.grp = 'treated'
        GROUP BY ta.id_compteur;
    """)
    rows = cur.fetchall()
    failing = [(cid, pre, post) for cid, pre, post in rows if pre < 21 or post < 21]
    min_pre = min((r[1] for r in rows), default=0)
    min_post = min((r[2] for r in rows), default=0)

    print("\n================ PANEL SUMMARY ================")
    print(f"daily_counts rows (all days)......... {daily_all:,}")
    print(f"low-coverage rows DROPPED (<{LOW_COVERAGE_HOURS}h)..... {dropped:,}")
    print(f"model_panel rows (valid)............. {panel_rows:,}")
    print(f"treated counters..................... {len(rows)}")
    print(f"min valid pre days / post days....... {min_pre} / {min_post}")
    if failing:
        print(f"!! treated counters below 21 pre/post: {len(failing)}")
        for cid, pre, post in failing:
            print(f"     {cid}: pre={pre} post={post}")
    print("==============================================")

    assert not failing, (
        f"{len(failing)} treated counters have <21 valid pre or post days: {failing}"
    )
    print("ACCEPTANCE: PASS — every treated counter has >=21 valid pre AND post days.")
    return 0


def main() -> int:
    conn = get_engine().raw_connection()
    try:
        build_panel(conn)
        return report_and_assert(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
