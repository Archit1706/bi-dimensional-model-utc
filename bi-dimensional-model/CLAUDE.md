# CLAUDE.md — Chicago TAZ Transportation Analysis Project

This file gives Claude Code full context to continue a transportation analysis project
that was developed in Claude.ai chat. Read this file plus all files in `docs/` before
doing any work.

---

## Project Goal

Analyze travel behavior and accessibility patterns across Chicago's urban geography
using the **bidimensional transportation model** (Khisty & Sriraj, 1995).

The model evaluates which transportation mode is "optimal" for a given trip by
computing **generalized speed** across a 2D space of:
- **Trip displacement (D)** — distance in miles
- **Value of Time (H)** — $/hr, representing income-based willingness to pay

The study area is Chicago's 7-county metropolitan area, broken into
**Traffic Analysis Zones (TAZ)**. Travel data between TAZ pairs was collected
via **OpenTripPlanner (OTP)**.

---

## Repository Structure (expected)

```
project/
├── CLAUDE.md                    ← you are here
├── main.py                      ← original scenario-building model (Khisty & Sriraj replication)
├── docs/
│   ├── model_theory.md          ← formulas and model background
│   ├── chicago_taz_analysis.md  ← Chicago-specific parameters, zone classification, VoT levels
│   └── scripts_built.md         ← all scripts created, their parameters, and output files
├── data/
│   ├── taz.xlsx                 ← TAZ classification data (chicago, cbd columns)
│   ├── walk_data.csv            ← OTP walk mode output
│   ├── bike_data.csv            ← OTP bicycle mode output
│   ├── car_data.csv             ← OTP car mode output
│   └── transit_data.csv         ← OTP transit mode output
├── scripts/
│   ├── calc_walk_generalized.py
│   ├── calc_bike_generalized.py
│   ├── calc_car_generalized.py
│   └── (transit script — not yet built)
└── outputs/
    └── (CSV outputs from each script)
```

---

## Key Data Files

### `taz.xlsx`
Contains TAZ metadata. Two columns drive all zone classification logic:
- `chicago` — 1 if the TAZ is within Chicago city limits, 0 if suburban
- `cbd` — 1 if the TAZ is in the Central Business District, 0 otherwise

### OTP CSV files
Each mode's CSV has these columns (at minimum):
```
origin_taz, destination_taz, travel_distance_miles, travel_time_mins
```
Missing rows, zero-distance, or zero-time entries indicate **unreachable TAZ pairs**
and must be flagged as invalid rather than computed.

---

## What Has Been Built

Three mode scripts are complete. A transit analysis and visualization layer are in progress.
See `docs/scripts_built.md` for full details.

| Mode      | Script                        | Status   |
|-----------|-------------------------------|----------|
| Walking   | `calc_walk_generalized.py`    | ✅ Done  |
| Bicycle   | `calc_bike_generalized.py`    | ✅ Done  |
| Car       | `calc_car_generalized.py`     | ✅ Done  |
| Transit   | `calc_transit_generalized.py` | ⬜ TODO  |

---

## Critical Conventions

- **Units are miles and hours** throughout all scripts. OTP outputs time in minutes —
  always divide by 60 before computing.
- **VoT levels** are fixed at three income brackets (see `docs/chicago_taz_analysis.md`).
- **Zone classification** is applied to the *destination* TAZ, not the origin.
- **Fixed costs differ by destination zone type** — this is critical for the car mode;
  see `docs/chicago_taz_analysis.md`.
- Walking generalized metrics are VoT-independent (all costs are zero), so
  generalized_speed == average_speed for walk mode.
- Each script must produce three output files:
  1. Full results (all pairs including flagged invalids)
  2. Clean results (valid pairs only)
  3. Invalid/flagged pairs only

---

## Next Steps / Open Tasks

1. **Build transit mode script** — parameters TBD; transit has first-mile/last-mile
   walk legs and transfer legs that may need special handling.
2. **Multi-mode comparison** — once all four mode scripts are done, run `optimum_mode()`
   logic across all modes per TAZ pair to produce Chicago-wide mode choice maps.
3. **Visualization** — gold-scheme Chart.js dashboards have been built for car mode
   and transit walking burden (see `docs/scripts_built.md`). Extend to other modes.
4. **Presentation outputs** — previous charts were sized for PowerPoint screenshots
   with large fonts and permanent data labels (using `chartjs-plugin-datalabels`).

---

## Reference

- Khisty, C.J. & Sriraj, P.S. (1995). *Use of Scenario-Building Transportation Model
  for Developing Countries.* Transportation Research Record 1563, pp. 16–25.
- Model paper is in the project as: `use_of_a_scenario_building_model__sriraj_ms_thesis.pdf`
