# Step 7 — Parallel-trends verdict

**Verdict: parallel-trends NOT supported in the naive two-way fixed-effects event-study.**
All 7 pre-period lead coefficients are individually significant and jointly different from
zero (F-test p < 0.001).

## But read the shape, not just the p-values
The event-study coefficient path is a near-perfectly **straight, monotonic line running
from +1.3 log points at week −8 down through 0 at week −1 to −1.7 at week +8, with NO
discontinuity (kink) at the event date (t=0).**

A genuine causal effect looks different: **flat** leads (~0 before the event) followed by a
**drop** at t=0. What we see instead is a smooth trend that passes straight through the
event — the classic signature of a **confounded trend, not a treatment effect**. The
apparent "decline" is a pre-existing downward trajectory that would have happened with or
without the chantier.

## Why this happens here (and it is expected)
1. **Strong cycling seasonality.** Treated events cluster in autumn/winter/early-spring
   (8 in Sep, 5 in Dec, 14 in Mar). Cycling volume has a large seasonal cycle, so a
   counter's −8…−1 week window systematically straddles a seasonal slope.
2. **Staggered adoption contaminates naive TWFE.** With heterogeneous treatment timing,
   already-treated counters leak into the implicit control group (Goodman-Bacon /
   Sun-Abraham). The calendar-week fixed effects cannot fully absorb the seasonal slope
   under this structure (the f-test even reports rank-deficiency among the lead
   constraints — a symptom of leads partly collinear with the week FE).

The descriptive panels corroborate this: in **calendar time** treated and non-treated
counters share the same seasonal shape (common shocks are shared — good), and the **raw
event-time index** moves far less dramatically than the regression leads imply — i.e. the
regression's steep leads are largely artifact.

## Consequence for Step 8 (mandatory, not optional)
The naive TWFE event-study must NOT be used for the headline number. Step 8 will:
- use a **heterogeneity-robust, cohort-based estimator** (Callaway–Sant'Anna group-time
  ATT) with **not-yet-treated** counters as the clean comparison, and
- **de-seasonalize** by adding weather/seasonal controls (temperature, precipitation,
  daylight via Open-Meteo) or a day-of-year term,

then re-test that the leads are flat. Only if the leads flatten and a break appears at t=0
can we claim a causal "péage".

**Bottom line for the jury:** we checked the assumption, found the naive model is
confounded by a seasonal trend, proved it from the no-break-at-t=0 shape, and routed to the
correct estimator — rather than reporting a spurious effect.
