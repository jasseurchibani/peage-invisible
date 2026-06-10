"""Step 10 — Visualization: headline divergence chart, counter map, event-study plot.

Reads results saved by Step 8 (outputs/cs_event_study.csv, outputs/cs_headline.csv) and
the panel/geometry from Postgres. Produces:
  * figures/headline_effect.png  — treated (observed) vs CS counterfactual, event-time
  * figures/counter_map.png      — treated vs non-treated counters + chantiers
  * (figures/event_study_cs.png is produced in Step 8 and reused as the coefficient plot)

Run:
    python -m src.viz
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .db import get_engine

FIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "figures")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
WEEKS = 8


def _headline_numbers() -> dict:
    h = pd.read_csv(os.path.join(OUT_DIR, "cs_headline.csv")).iloc[0]
    return dict(pct=h["pct"] * 100, lo=h["pct_lo"] * 100, hi=h["pct_hi"] * 100,
                abs_day=h["abs_per_day"], base=h["base_level"])


# --------------------------------------------------------------------------- #
# (1) headline figure
# --------------------------------------------------------------------------- #
def headline_figure() -> None:
    eng = get_engine()
    df = pd.read_sql(
        "SELECT total_count, rel_day FROM model_panel WHERE treated = 1 AND rel_day IS NOT NULL;",
        eng)
    df["rel_week"] = np.floor(df["rel_day"] / 7).astype(int)
    df = df[(df.rel_week >= -WEEKS) & (df.rel_week <= WEEKS)]
    obs = df.groupby("rel_week")["total_count"].mean()

    es = pd.read_csv(os.path.join(OUT_DIR, "cs_event_study.csv")).set_index("rel_week")
    # counterfactual = observed without the estimated effect: obs / exp(ATT)
    cf = obs / np.exp(es["att"].reindex(obs.index).fillna(0.0))

    h = _headline_numbers()
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.axvline(-0.5, color="black", lw=1.5)
    ax.text(-0.4, ax.get_ylim()[1], "  chantier opens", va="top", fontsize=9)

    ax.plot(obs.index, obs.values, "-o", color="#c0392b", lw=2,
            label="Observed — treated counters")
    ax.plot(cf.index, cf.values, "--", color="#2980b9", lw=2,
            label="Counterfactual — no-chantier (Callaway-Sant'Anna)")
    ax.fill_between(obs.index, obs.values, cf.values, where=obs.index >= 0,
                    color="grey", alpha=0.25, label="post-period gap (≈ the effect)")

    ax.set_title("Le Péage Invisible — do construction sites suppress nearby cycling?",
                 fontsize=14, weight="bold")
    ax.set_xlabel("weeks relative to chantier opening (t = 0)")
    ax.set_ylabel("mean daily passages per counter")
    ax.grid(alpha=0.3); ax.legend(loc="lower left", fontsize=9)

    msg = (f"NO measurable effect: {h['abs_day']:+.0f} passages/day "
           f"({h['pct']:+.1f}%)\n95% CI [{h['lo']:+.1f}%, {h['hi']:+.1f}%] — the two lines "
           f"stay glued through t=0.\nCaveat: measured at 150 m / weekly; cyclists may "
           f"reroute around the single blocked street.")
    ax.text(0.98, 0.97, msg, transform=ax.transAxes, ha="right", va="top", fontsize=10,
            bbox=dict(boxstyle="round", fc="#fdf6e3", ec="#b58900"))

    fig.tight_layout()
    out = os.path.join(FIG_DIR, "headline_effect.png")
    fig.savefig(out, dpi=140); plt.close(fig)
    print(f"  saved {out}")


# --------------------------------------------------------------------------- #
# (2) counter map
# --------------------------------------------------------------------------- #
def counter_map() -> None:
    eng = get_engine()
    counters = pd.read_sql("""
        SELECT ta.grp, ST_X(c.geom) AS lon, ST_Y(c.geom) AS lat
        FROM treatment_assignment ta JOIN counters c USING (id_compteur);
    """, eng)
    chantiers = pd.read_sql("""
        SELECT ST_X(geom_point) AS lon, ST_Y(geom_point) AS lat
        FROM raw_chantiers
        WHERE geom_point IS NOT NULL
          AND (localisation_detail && ARRAY['EMPRISE_CHAUSSEE','EMPRISE_STATIONNEMENT']
               OR surface >= 100)
          AND date_debut <= DATE '2026-06-08' AND date_fin >= DATE '2025-05-01';
    """, eng)

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.scatter(chantiers.lon, chantiers.lat, s=6, c="#bdc3c7", alpha=0.5,
               label=f"disruptive chantiers (n={len(chantiers)})")
    tr = counters[counters.grp == "treated"]
    ot = counters[counters.grp != "treated"]
    ax.scatter(ot.lon, ot.lat, s=70, c="#2980b9", edgecolor="k", marker="^",
               label=f"non-treated counters (n={len(ot)})")
    ax.scatter(tr.lon, tr.lat, s=70, c="#c0392b", edgecolor="k",
               label=f"treated counters (n={len(tr)})")

    ax.set_aspect(1 / np.cos(np.radians(48.85)))
    ax.set_title("Paris bike counters and disruptive construction sites")
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "counter_map.png")
    fig.savefig(out, dpi=140); plt.close(fig)
    print(f"  saved {out}")


def main() -> int:
    os.makedirs(FIG_DIR, exist_ok=True)
    headline_figure()
    counter_map()
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
