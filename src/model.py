"""Steps 7-9 — EDA / parallel-trends (Step 7), DiD estimation (Step 8), robustness (Step 9).

Step 7: descriptive plots + preliminary TWFE event-study + parallel-trends verdict.
Step 8: TWFE DiD (naive benchmark) + full event-study + Callaway-Sant'Anna group-time
        ATT with NOT-YET-TREATED controls (primary, heterogeneity-robust) + cluster
        bootstrap CIs. Headline taken from the CS estimator.

NOTE ON DESIGN: no never-treated control survived the 500m spillover rule (Step 5), so the
comparison group is NOT-YET-TREATED counters. With staggered timing, naive TWFE is biased
(Goodman-Bacon / Sun-Abraham); the Callaway-Sant'Anna estimator is the credible one.

Run:
    python -m src.model step7      # EDA + parallel-trends
    python -m src.model step8      # estimation (default)
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from linearmodels.panel import PanelOLS

from .db import get_engine

FIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "figures")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
WEEKS = 8                      # leads/lags window in weeks
LEAD_LAG_DAYS = WEEKS * 7      # +/- 56 days


def load_panel() -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT id_compteur, day, total_count, grp, event_date, rel_day, "
        "post, treated, dow, month, is_holiday FROM model_panel;",
        get_engine(),
        parse_dates=["day", "event_date"],
    )
    df["y"] = np.log1p(df["total_count"])
    df["cal_week"] = df["day"].dt.strftime("%G-%V")
    return df


# --------------------------------------------------------------------------- #
# (1) descriptive plots
# --------------------------------------------------------------------------- #
def plot_descriptive(df: pd.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5.5))

    # (a) calendar time: treated vs non-treated, 7-day rolling mean of cross-counter mean
    treated_daily = (df[df.treated == 1].groupby("day")["total_count"].mean()
                     .rolling(7, min_periods=3).mean())
    comp_daily = (df[df.treated == 0].groupby("day")["total_count"].mean()
                  .rolling(7, min_periods=3).mean())
    ax1.plot(treated_daily.index, treated_daily.values, label=f"treated (n={df[df.treated==1].id_compteur.nunique()})", color="#c0392b")
    ax1.plot(comp_daily.index, comp_daily.values, label=f"non-treated pool (n={df[df.treated==0].id_compteur.nunique()})", color="#2980b9")
    ax1.set_title("(a) Mean daily bike count over calendar time\n(7-day rolling)")
    ax1.set_xlabel("date"); ax1.set_ylabel("mean daily passages / counter")
    ax1.legend(); ax1.grid(alpha=0.3)
    fig.autofmt_xdate()

    # (b) event time: each treated counter indexed to its own pre-event mean, weekly bins
    tr = df[(df.treated == 1) & df.rel_day.notna()].copy()
    pre_mean = (tr[tr.rel_day < 0].groupby("id_compteur")["total_count"].mean()
                .rename("pre_mean"))
    tr = tr.join(pre_mean, on="id_compteur")
    tr = tr[tr.pre_mean > 0]
    tr["index"] = tr["total_count"] / tr["pre_mean"]
    tr["rel_week"] = np.floor(tr["rel_day"] / 7).astype(int)
    win = tr[(tr.rel_week >= -WEEKS) & (tr.rel_week <= WEEKS)]
    wk = win.groupby("rel_week")["index"].mean()
    ax2.axhline(1.0, color="grey", lw=1, ls=":")
    ax2.axvline(0, color="black", lw=1)
    ax2.plot(wk.index, wk.values, marker="o", color="#c0392b")
    ax2.set_title("(b) Treated counters indexed to own pre-event mean\n(event time, weekly)")
    ax2.set_xlabel("weeks relative to chantier opening (t=0)")
    ax2.set_ylabel("count / pre-event mean")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    out = os.path.join(FIG_DIR, "parallel_trends.png")
    fig.savefig(out, dpi=130); plt.close(fig)
    print(f"  saved {out}")


# --------------------------------------------------------------------------- #
# (2) preliminary weekly event-study
# --------------------------------------------------------------------------- #
def event_study(df: pd.DataFrame):
    tr = df[(df.treated == 1) & df.rel_day.notna()].copy()
    tr = tr[(tr.rel_day >= -LEAD_LAG_DAYS) & (tr.rel_day <= LEAD_LAG_DAYS + 6)]
    tr["rel_week"] = np.floor(tr["rel_day"] / 7).astype(int)
    tr = tr[(tr.rel_week >= -WEEKS) & (tr.rel_week <= WEEKS)]

    # week -1 is the reference (omitted) category.
    model = smf.ols(
        "y ~ C(rel_week, Treatment(reference=-1)) + C(id_compteur) + C(cal_week)",
        data=tr,
    ).fit(cov_type="cluster", cov_kwds={"groups": tr["id_compteur"]})

    # extract rel_week coefficients
    rows = []
    for name in model.params.index:
        if name.startswith("C(rel_week"):
            wk = int(name.split("[T.")[1].rstrip("]"))
            rows.append((wk, model.params[name], model.bse[name], model.pvalues[name]))
    rows.append((-1, 0.0, 0.0, np.nan))  # reference
    es = pd.DataFrame(rows, columns=["rel_week", "coef", "se", "pval"]).sort_values("rel_week")
    es["ci_lo"] = es.coef - 1.96 * es.se
    es["ci_hi"] = es.coef + 1.96 * es.se

    # plot
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.axhline(0, color="grey", lw=1, ls=":")
    ax.axvline(-0.5, color="black", lw=1, label="chantier opens")
    ax.errorbar(es.rel_week, es.coef, yerr=1.96 * es.se, fmt="o-", capsize=3,
                color="#c0392b")
    ax.set_title("Preliminary event-study: log(daily count) around chantier opening\n"
                 "counter + calendar-week FE, SE clustered by counter (ref week = -1)")
    ax.set_xlabel("weeks relative to chantier opening"); ax.set_ylabel("coef vs week -1 (log points)")
    ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "event_study_pre.png")
    fig.savefig(out, dpi=130); plt.close(fig)
    print(f"  saved {out}")

    # parallel-trends test: are leads (weeks < -1) jointly + individually ~ 0?
    leads = es[es.rel_week < -1]
    sig_leads = leads[leads.pval < 0.05]
    hyp = " = ".join(
        [f"C(rel_week, Treatment(reference=-1))[T.{w}] = 0" for w in leads.rel_week]
    )
    ftest = model.f_test(hyp)
    joint_p = float(np.ravel(ftest.pvalue))
    return es, sig_leads, joint_p


def run_step7() -> int:
    os.makedirs(FIG_DIR, exist_ok=True)
    df = load_panel()
    print(f"loaded model_panel: {len(df):,} rows, "
          f"{df[df.treated==1].id_compteur.nunique()} treated counters")
    plot_descriptive(df)
    es, sig_leads, joint_p = event_study(df)

    print("\n== event-study lead coefficients (pre-period, should be ~0) ==")
    for _, r in es[es.rel_week < 0].iterrows():
        flag = "  <-- p<0.05" if (pd.notna(r.pval) and r.pval < 0.05) else ""
        print(f"  week {int(r.rel_week):>3}: coef={r.coef:+.3f}  se={r.se:.3f}  p={r.pval:.3f}{flag}")

    n_sig = len(sig_leads)
    print("\n================ PARALLEL-TRENDS VERDICT ================")
    if n_sig == 0 and joint_p > 0.05:
        verdict = (f"Parallel-trends SUPPORTED (joint F-test p={joint_p:.3f}).")
    else:
        verdict = (f"Parallel-trends QUESTIONABLE: {n_sig} pre-period lead(s) significant; "
                   f"joint F-test p={joint_p:.3f}.")
    print(verdict)
    print("========================================================")
    return 0


# =========================================================================== #
# STEP 8 — estimation
# =========================================================================== #
def twfe_did(df: pd.DataFrame) -> dict:
    """Naive staggered TWFE DiD on treated counters: y ~ post + EntityFE + TimeFE.
    (C(dow)+is_holiday are absorbed by the day fixed effects.)"""
    d = df[df.treated == 1].copy()
    d["post"] = (d["rel_day"] >= 0).astype(int)
    base_level = d.loc[d["post"] == 0, "total_count"].mean()  # pre-event mean daily count
    pan = d.set_index(["id_compteur", "day"])
    res = PanelOLS.from_formula(
        "y ~ post + EntityEffects + TimeEffects", pan,
    ).fit(cov_type="clustered", cluster_entity=True)
    b, se = res.params["post"], res.std_errors["post"]
    lo, hi = b - 1.96 * se, b + 1.96 * se
    return {
        "coef_log": b, "se": se, "ci_log": (lo, hi),
        "pct": np.expm1(b), "pct_ci": (np.expm1(lo), np.expm1(hi)),
        "base_level": base_level,
        "abs": base_level * np.expm1(b),
        "abs_ci": (base_level * np.expm1(lo), base_level * np.expm1(hi)),
    }


# --------------------------- Callaway-Sant'Anna ---------------------------- #
def _weekly_arrays(df: pd.DataFrame):
    """Build a counter×week matrix of log mean-daily counts + cohort (event week)."""
    d = df[df.treated == 1].copy()
    d["iso"] = d["day"].dt.strftime("%G%V")
    weeks = sorted(d["iso"].unique())
    widx = {w: i for i, w in enumerate(weeks)}
    d["wk"] = d["iso"].map(widx)
    wk = (d.groupby(["id_compteur", "wk"])["total_count"].mean()
            .rename("mean_daily").reset_index())
    wk["y"] = np.log1p(wk["mean_daily"])

    cids = sorted(d["id_compteur"].unique())
    cidx = {c: i for i, c in enumerate(cids)}
    W = len(weeks)
    Y = np.full((len(cids), W), np.nan)
    for _, r in wk.iterrows():
        Y[cidx[r.id_compteur], int(r.wk)] = r.y

    ev = d.groupby("id_compteur")["event_date"].first()
    g = np.array([widx[ev[c].strftime("%G%V")] for c in cids])
    base_level = d.loc[d["rel_day"] < 0, "total_count"].mean()
    return Y, g, W, base_level


def _cs_event_study(Y, g, W, idx, horizons):
    """Group-time ATT aggregated to event time, not-yet-treated controls.
    Returns (att_by_horizon dict, overall_post_ATT)."""
    Ys, gs = Y[idx], g[idx]
    att = {}
    post_num = post_w = 0.0
    for e in horizons:
        num = wsum = 0.0
        for gg in np.unique(gs):
            t = gg + e
            if t < 0 or t >= W or gg - 1 < 0:
                continue
            diff = Ys[:, t] - Ys[:, gg - 1]
            tr = (gs == gg) & ~np.isnan(diff)
            ct = (gs > max(t, gg)) & ~np.isnan(diff)          # not-yet-treated by t
            if tr.sum() == 0 or ct.sum() == 0:
                continue
            att_gt = diff[tr].mean() - diff[ct].mean()
            n = tr.sum()
            num += att_gt * n
            wsum += n
            if e >= 0:
                post_num += att_gt * n
                post_w += n
        att[e] = (num / wsum) if wsum else np.nan
    overall = (post_num / post_w) if post_w else np.nan
    return att, overall


def callaway_santanna(df: pd.DataFrame, n_boot: int = 500, seed: int = 42) -> dict:
    Y, g, W, base_level = _weekly_arrays(df)
    n = Y.shape[0]
    horizons = list(range(-WEEKS, WEEKS + 1))
    full_idx = np.arange(n)
    att, overall = _cs_event_study(Y, g, W, full_idx, horizons)

    rng = np.random.default_rng(seed)
    boot_overall = np.empty(n_boot)
    boot_att = {e: np.empty(n_boot) for e in horizons}
    for b in range(n_boot):
        idx = rng.integers(0, n, n)              # cluster bootstrap over counters
        a_b, o_b = _cs_event_study(Y, g, W, idx, horizons)
        boot_overall[b] = o_b
        for e in horizons:
            boot_att[e][b] = a_b[e]

    def ci(arr):
        arr = arr[~np.isnan(arr)]
        return (np.percentile(arr, 2.5), np.percentile(arr, 97.5)) if len(arr) else (np.nan, np.nan)

    o_lo, o_hi = ci(boot_overall)
    es = pd.DataFrame({"rel_week": horizons,
                       "att": [att[e] for e in horizons],
                       "ci_lo": [ci(boot_att[e])[0] for e in horizons],
                       "ci_hi": [ci(boot_att[e])[1] for e in horizons]})
    return {
        "coef_log": overall, "ci_log": (o_lo, o_hi),
        "pct": np.expm1(overall), "pct_ci": (np.expm1(o_lo), np.expm1(o_hi)),
        "base_level": base_level,
        "abs": base_level * np.expm1(overall),
        "abs_ci": (base_level * np.expm1(o_lo), base_level * np.expm1(o_hi)),
        "event_study": es,
    }


def plot_cs_event_study(cs: dict, twfe_es: pd.DataFrame) -> None:
    es = cs["event_study"]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axhline(0, color="grey", lw=1, ls=":")
    ax.axvline(-0.5, color="black", lw=1, label="chantier opens")
    # CS with bootstrap CI band
    ax.errorbar(es.rel_week, es.att, yerr=[es.att - es.ci_lo, es.ci_hi - es.att],
                fmt="o-", capsize=3, color="#1a7f37", label="Callaway-Sant'Anna (not-yet-treated)")
    # TWFE overlay
    ax.plot(twfe_es.rel_week, twfe_es.coef, "s--", color="#c0392b", alpha=0.7,
            label="naive TWFE (biased)")
    ax.set_title("Event-study: log(weekly mean daily count) around chantier opening\n"
                 "CS vs naive TWFE — leads should be flat if the effect is real")
    ax.set_xlabel("weeks relative to chantier opening"); ax.set_ylabel("ATT (log points)")
    ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "event_study_cs.png")
    fig.savefig(out, dpi=130); plt.close(fig)
    print(f"  saved {out}")


def run_step8() -> int:
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_panel()
    print(f"loaded model_panel: {len(df):,} rows, "
          f"{df[df.treated==1].id_compteur.nunique()} treated counters\n")

    # (1) naive TWFE benchmark
    print("[1/3] TWFE DiD (naive benchmark)...")
    tw = twfe_did(df)
    pd.DataFrame([{
        "estimator": "TWFE", "coef_log": tw["coef_log"], "se": tw["se"],
        "pct": tw["pct"], "pct_lo": tw["pct_ci"][0], "pct_hi": tw["pct_ci"][1],
        "abs_per_day": tw["abs"], "abs_lo": tw["abs_ci"][0], "abs_hi": tw["abs_ci"][1],
    }]).to_csv(os.path.join(OUT_DIR, "twfe_did.csv"), index=False)

    # (2) full TWFE event-study (reuse Step 7 machinery) -> table
    twfe_es, _, _ = event_study(df)
    twfe_es.to_csv(os.path.join(OUT_DIR, "event_study_twfe.csv"), index=False)

    # (3) Callaway-Sant'Anna with not-yet-treated controls (primary)
    print("[2/3] Callaway-Sant'Anna group-time ATT + cluster bootstrap...")
    cs = callaway_santanna(df, n_boot=500)
    cs["event_study"].to_csv(os.path.join(OUT_DIR, "cs_event_study.csv"), index=False)
    pd.DataFrame([{
        "estimator": "Callaway-SantAnna", "coef_log": cs["coef_log"],
        "pct": cs["pct"], "pct_lo": cs["pct_ci"][0], "pct_hi": cs["pct_ci"][1],
        "abs_per_day": cs["abs"], "abs_lo": cs["abs_ci"][0], "abs_hi": cs["abs_ci"][1],
        "base_level": cs["base_level"],
    }]).to_csv(os.path.join(OUT_DIR, "cs_headline.csv"), index=False)

    print("[3/3] plotting...")
    plot_cs_event_study(cs, twfe_es)

    # ---- CS lead flatness re-check ----
    leads = cs["event_study"]
    pre = leads[leads.rel_week < -1]
    pre_sig = pre[(pre.ci_lo > 0) | (pre.ci_hi < 0)]   # CI excludes 0
    leads_flat = len(pre_sig) == 0

    # ---- headline + agreement ----
    def fmt(d):
        return (f"{d['abs']:+.1f} passages/day ({d['pct']*100:+.1f}%), "
                f"95% CI [{d['abs_ci'][0]:+.1f}, {d['abs_ci'][1]:+.1f}] "
                f"/ [{d['pct_ci'][0]*100:+.1f}%, {d['pct_ci'][1]*100:+.1f}%]")

    same_sign = np.sign(tw["coef_log"]) == np.sign(cs["coef_log"])
    cs_lo, cs_hi = cs["pct_ci"]
    tw_in_cs = cs_lo <= tw["pct"] <= cs_hi
    agree = same_sign and tw_in_cs

    print("\n================== STEP 8 — HEADLINE ==================")
    print(f"base pre-event level (treated)......... {cs['base_level']:.1f} passages/day")
    print(f"PRIMARY (Callaway-Sant'Anna).......... {fmt(cs)}")
    print(f"naive TWFE benchmark.................. {fmt(tw)}")
    print(f"CS pre-period leads flat (CI incl 0).. {'YES' if leads_flat else 'NO ('+str(len(pre_sig))+' sig leads)'}")
    print(f"TWFE vs CS agree...................... "
          f"{'YES' if agree else 'NO'} (same sign={same_sign}, TWFE pt within CS CI={tw_in_cs})")
    print("======================================================")

    # headline string for deliverable
    headline = (f"PRIMARY (Callaway-Sant'Anna): {fmt(cs)}. "
                f"Naive TWFE: {fmt(tw)}. "
                f"CS pre-trends flat: {leads_flat}. TWFE-vs-CS agree: {agree}.")
    with open(os.path.join(OUT_DIR, "step8_headline.txt"), "w", encoding="utf-8") as fh:
        fh.write(headline + "\n")
    return 0


# =========================================================================== #
# STEP 9 — robustness battery (all variants via Callaway-Sant'Anna)
# =========================================================================== #
def _build_weekly(daily: pd.DataFrame, event_map: dict):
    """counter×week log mean-daily matrix + cohort week, keeping only valid cohorts (g>=1)."""
    d = daily[daily["id_compteur"].isin(event_map)].copy()
    d["iso"] = d["day"].dt.strftime("%G%V")
    weeks = sorted(d["iso"].unique())
    widx = {w: i for i, w in enumerate(weeks)}
    d["wk"] = d["iso"].map(widx)
    wk = (d.groupby(["id_compteur", "wk"])["total_count"].mean()
            .rename("mean_daily").reset_index())
    wk["y"] = np.log1p(wk["mean_daily"])

    cids = sorted(event_map)
    cidx = {c: i for i, c in enumerate(cids)}
    W = len(weeks)
    Y = np.full((len(cids), W), np.nan)
    for r in wk.itertuples():
        Y[cidx[r.id_compteur], int(r.wk)] = r.y
    g = np.array([widx.get(pd.Timestamp(event_map[c]).strftime("%G%V"), -1) for c in cids])

    keep = g >= 1
    Y, g = Y[keep], g[keep]
    cids = [c for c, k in zip(cids, keep) if k]

    dd = d[d["id_compteur"].isin(cids)].copy()
    dd["ev"] = dd["id_compteur"].map({c: pd.Timestamp(event_map[c]) for c in cids})
    base = dd.loc[dd["day"] < dd["ev"], "total_count"].mean()
    return Y, g, W, base, cids


def _cs_overall(Y, g, W, idx):
    _, overall = _cs_event_study(Y, g, W, idx, list(range(0, WEEKS + 1)))
    return overall


def _cs_overall_ci(Y, g, W, n_boot=300, seed=42):
    n = Y.shape[0]
    overall = _cs_overall(Y, g, W, np.arange(n))
    rng = np.random.default_rng(seed)
    boot = np.array([_cs_overall(Y, g, W, rng.integers(0, n, n)) for _ in range(n_boot)])
    boot = boot[~np.isnan(boot)]
    lo, hi = (np.percentile(boot, 2.5), np.percentile(boot, 97.5)) if len(boot) else (np.nan, np.nan)
    return overall, lo, hi


def _event_map(pairs_sub: pd.DataFrame, shift_days: int = 0) -> dict:
    g = pairs_sub.groupby("id_compteur")["date_debut"].min()
    return {c: pd.Timestamp(v) - pd.Timedelta(days=shift_days) for c, v in g.items()}


def run_step9() -> int:
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    eng = get_engine()
    daily = pd.read_sql(
        "SELECT id_compteur, day, total_count FROM daily_counts WHERE n_hours_observed >= 20;",
        eng, parse_dates=["day"])
    pairs = pd.read_sql("""
        SELECT cp.id_compteur, cp.chantier_id, cp.date_debut, cp.distance_m,
               cp.long_site, cp.debut_has_padding,
               ch.surface,
               (ch.localisation_detail && ARRAY['EMPRISE_CHAUSSEE','EMPRISE_STATIONNEMENT']) AS roadway
        FROM candidate_pairs cp
        JOIN raw_chantiers ch ON ch.num_emprise = cp.chantier_id;
    """, eng, parse_dates=["date_debut"])
    pad = pairs[pairs.debut_has_padding]

    # variant -> qualifying-pairs filter (all keep >=21d padding)
    variants = {
        "main (150m, disruptive)": pad[pad.distance_m <= 150],
        "radius 300m":             pad[pad.distance_m <= 300],
        "long sites (>=60d)":      pad[(pad.distance_m <= 150) & (pad.long_site)],
        "roadway-only":            pad[(pad.distance_m <= 150) & (pad.roadway)],
        "surface-only (>=100m2)":  pad[(pad.distance_m <= 150) & (pad.surface >= 100)],
    }

    rows = []
    for name, sub in variants.items():
        em = _event_map(sub)
        Y, g, W, base, cids = _build_weekly(daily, em)
        ov, lo, hi = _cs_overall_ci(Y, g, W, n_boot=300)
        rows.append(dict(variant=name, n_counters=len(cids),
                         pct=np.expm1(ov)*100, pct_lo=np.expm1(lo)*100, pct_hi=np.expm1(hi)*100,
                         abs_per_day=base*np.expm1(ov),
                         abs_lo=base*np.expm1(lo), abs_hi=base*np.expm1(hi),
                         base_level=base))
        print(f"  {name:28s} n={len(cids):3d}  effect={np.expm1(ov)*100:+.1f}% "
              f"[{np.expm1(lo)*100:+.1f},{np.expm1(hi)*100:+.1f}]")

    # (a) placebo: main set, event shifted back 120 days
    em_pl = _event_map(variants["main (150m, disruptive)"], shift_days=120)
    Yp, gp, Wp, basep, cidsp = _build_weekly(daily, em_pl)
    ov, lo, hi = _cs_overall_ci(Yp, gp, Wp, n_boot=300)
    placebo = dict(variant="PLACEBO (event -120d)", n_counters=len(cidsp),
                   pct=np.expm1(ov)*100, pct_lo=np.expm1(lo)*100, pct_hi=np.expm1(hi)*100,
                   abs_per_day=basep*np.expm1(ov), abs_lo=basep*np.expm1(lo),
                   abs_hi=basep*np.expm1(hi), base_level=basep)
    rows.append(placebo)
    print(f"  {'PLACEBO (event -120d)':28s} n={len(cidsp):3d}  effect={placebo['pct']:+.1f}% "
          f"[{placebo['pct_lo']:+.1f},{placebo['pct_hi']:+.1f}]")

    # (e) leave-one-out on main
    em_main = _event_map(variants["main (150m, disruptive)"])
    Ym, gm, Wm, basem, cidsm = _build_weekly(daily, em_main)
    n = Ym.shape[0]
    loo = np.array([np.expm1(_cs_overall(Ym, gm, Wm, np.delete(np.arange(n), i)))*100
                    for i in range(n)])
    print(f"  leave-one-out main: range [{loo.min():+.2f}%, {loo.max():+.2f}%] over {n} drops")

    df_out = pd.DataFrame(rows)
    df_out.to_csv(os.path.join(OUT_DIR, "robustness.csv"), index=False)

    # forest plot
    fig, ax = plt.subplots(figsize=(10, 6))
    order = list(range(len(rows)))[::-1]
    for y, r in zip(order, rows):
        color = "#7f8c8d" if r["variant"].startswith("PLACEBO") else (
                "#1a7f37" if r["variant"].startswith("main") else "#2c3e50")
        ax.errorbar(r["pct"], y, xerr=[[r["pct"]-r["pct_lo"]], [r["pct_hi"]-r["pct"]]],
                    fmt="o", capsize=4, color=color)
    ax.axvline(0, color="red", lw=1, ls="--")
    ax.set_yticks(order); ax.set_yticklabels([r["variant"] for r in rows])
    ax.set_xlabel("effect on daily cycling (%) — Callaway-Sant'Anna, 95% bootstrap CI")
    ax.set_title("Le Péage Invisible — robustness of the treatment effect")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "robustness_forest.png"), dpi=130); plt.close(fig)
    print(f"  saved {os.path.join(FIG_DIR, 'robustness_forest.png')}")

    # ------------------------------- verdict --------------------------------
    def incl0(r):
        return r["pct_lo"] <= 0 <= r["pct_hi"]
    main_row = rows[0]
    main_null = incl0(main_row)
    placebo_ok = incl0(placebo)
    others = rows[1:-1]  # exclude main + placebo
    consistent = [r for r in others if incl0(r) == main_null]
    breakers = [r for r in others if not incl0(r)]  # CI excludes 0 -> a real effect emerges

    print("\n==================== STEP 9 VERDICT ====================")
    print(f"main finding............... {'NULL (CI incl 0)' if main_null else 'EFFECT'} "
          f"{main_row['pct']:+.1f}% [{main_row['pct_lo']:+.1f},{main_row['pct_hi']:+.1f}]")
    print(f"placebo ~ 0................ {'YES' if placebo_ok else 'NO'} "
          f"({placebo['pct']:+.1f}% [{placebo['pct_lo']:+.1f},{placebo['pct_hi']:+.1f}])")
    print(f"variants consistent w/ main {len(consistent)}/{len(others)}  (need >=3)")
    if breakers:
        print("  high-dose subsets that DO show a non-zero effect:")
        for r in breakers:
            print(f"    - {r['variant']}: {r['pct']:+.1f}% [{r['pct_lo']:+.1f},{r['pct_hi']:+.1f}]")
    print(f"leave-one-out stable...... range [{loo.min():+.2f}%, {loo.max():+.2f}%]")
    ok = placebo_ok and len(consistent) >= 3
    print(f"ACCEPTANCE (reinterpreted): {'PASS' if ok else 'REVIEW'} — placebo~0 and the "
          f"{'NULL' if main_null else 'effect'} reproduces in >=3 variants.")
    print("========================================================")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    step = argv[0] if argv else "step8"
    if step == "step7":
        return run_step7()
    if step == "step9":
        return run_step9()
    return run_step8()


if __name__ == "__main__":
    raise SystemExit(main())
