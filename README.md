# Le Péage Invisible

Causal study (Difference-in-Differences / event-study) testing whether disruptive
construction sites suppress cycling traffic at nearby Paris bike counters.

## Quickstart (Step 1)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
# source .venv/bin/activate                         # macOS/Linux
pip install -r requirements.txt

cp .env.example .env        # then edit credentials
psql -f sql/00_init.sql     # enable PostGIS on the target DB

make check                  # or: python -m src.db   -> prints "PostGIS OK -> ..."
```

## Layout
- `sql/` — DDL and PostGIS transforms
- `src/` — `db, ingest, spatial, panel, model, viz`
- `data/{raw,processed}/`, `figures/`, `outputs/`, `notebooks/`

See [Le_Peage_Invisible_Plan.md](Le_Peage_Invisible_Plan.md) for the full 10-step plan,
and [outputs/RAPPORT_Le_Peage_Invisible.md](outputs/RAPPORT_Le_Peage_Invisible.md) for the
final report (FR).

## Result (headline)
Construction sites have **no measurable effect** on nearby cycling: **−0.1 %, 95% CI
[−3.5 %, +3.1 %]** (Callaway–Sant'Anna, not-yet-treated controls). A naive TWFE event-study
suggested a large decline, but it was a staggered-DiD artifact — see
[figures/event_study_cs.png](figures/event_study_cs.png).
