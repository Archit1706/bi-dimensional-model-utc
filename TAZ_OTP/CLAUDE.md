# CLAUDE.md — Chicago Multimodal Accessibility Analysis

> This file provides Claude Code with full project context for the Chicago 7-county
> multimodal travel time and accessibility analysis. Read this before touching any script.

---

## Project Overview

Large-scale transportation research project computing **travel time matrices** across
**2,926 Traffic Analysis Zones (TAZs)** in the Chicago 7-county metropolitan area.
The full matrix is ~8.56 million origin-destination (OD) pairs per mode, across
**6 transportation modes**: walk, bike, car, bus, rail, transit (combined).

The stack is:
- **OpenTripPlanner (OTP)** — routing engine, run via Docker on Windows/WSL2
- **Python** — all data collection, processing, and analysis scripts
- **Replica mobility data** — real-world OD trip flows and mode split (separate from OTP)
- **ArcGIS Pro** — GIS visualization of outputs
- **Jupyter notebooks** — EDA

Transit agencies integrated into OTP: **CTA** (bus + rail), **Metra**, **Pace**.

Primary analysis time window: **9 AM arrival** (`arriveBy: true`).

---

## Repository Layout

```
project-root/
├── CLAUDE.md                      ← you are here
├── docs/
│   ├── otp-setup.md               ← Docker/OTP startup, WSL2 config
│   ├── scripts-inventory.md       ← every script, what it does, key args
│   ├── data-schema.md             ← file formats, column definitions
│   └── lessons-learned.md         ← hard-won lessons (READ BEFORE DEBUGGING)
├── scripts/
│   ├── taz_otp_matrix_json.py     ← primary OTP data collection (all modes)
│   ├── taz_retry_empty_trips.py   ← targeted retry for empty trip_patterns
│   ├── combine_json_to_csv.py     ← merges JSON → 6 mode CSVs
│   ├── analyze_invalid_car_pairs.py
│   ├── analyze_foot_legs.py       ← walking burden analysis
│   ├── transit_leg_combinations.py
│   ├── find_null.py
│   ├── recollect.py
│   └── merge_to_csv.py
├── data/
│   ├── taz_new2.csv               ← TAZ centroids (zone17, Lat, Lon, chicago, cbd)
│   ├── arrive-9AM/                ← primary JSON output (taz_travel_times_otp*.json)
│   ├── transit-arrive-9AM/        ← recollected transit JSON (taz_recollect_otp*.json)
│   └── csv/
│       ├── travel_time_car.csv
│       ├── travel_time_walk.csv
│       ├── travel_time_bike.csv
│       ├── travel_time_bus.csv
│       ├── travel_time_rail.csv
│       └── travel_time_transit.csv
└── outputs/
    ├── invalid_pairs.csv
    ├── foot_leg_analysis.csv
    ├── walking_report.txt
    └── plots/
```

---

## Current State of the Project

### ✅ Completed
- **Car matrix**: Full collection run done (8,558,550 OD pairs across 5,136+ JSON files).
- **Transit/bus/rail recollection**: Done in `transit-arrive-9AM/` after the lat/lon swap bug
  was fixed. A merge script combines both runs, with new transit data taking priority.
- **CSV merge**: `combine_json_to_csv.py` produces 6 mode-specific CSVs.
- **Invalid OD pair analysis** (car): ~64,700 missing pairs (0.76%) identified and classified.
- **Walking burden analysis**: `analyze_foot_legs.py` parses ~1,712 transit JSON files,
  classifying first-mile, last-mile, and within-trip walking; outputs `foot_leg_analysis.csv`
  and a 9-section plain-English `walking_report.txt` with 18 plots in `plots/`.
- **Transit leg combination analysis**: `transit_leg_combinations.py` catalogs all unique
  agency/mode combinations across the full transit dataset.

### 🔄 In Progress / Next Steps
- **Retry pass for empty trip_patterns (car)**: `taz_retry_empty_trips.py` was written to
  re-fetch entries where OTP returned `success: true` but `trip_patterns: []`. Needs to be
  run and validated.
- **Mode choice and accessibility analysis** across the full OD matrix (building on the
  Jupyter EDA notebook work).
- **Circuity metrics** — actual vs. straight-line distance comparisons per mode.
- **Transit competitiveness** — time ratio analysis (transit vs. car per OD pair).

---

## Key Files You Need to Know

### `taz_new2.csv`
TAZ centroid lookup. Critical columns:
| Column   | Description                              |
|----------|------------------------------------------|
| `zone17` | TAZ identifier (numeric)                 |
| `Lat`    | Latitude of centroid                     |
| `Lon`    | Longitude of centroid                    |
| `chicago`| 1 = City of Chicago zone, 0 = suburb     |
| `cbd`    | 1 = Chicago CBD zone (implies chicago=1) |

Zone type classification:
- **CBD**: `chicago=1, cbd=1`
- **City non-CBD**: `chicago=1, cbd=0`
- **Suburb**: `chicago=0, cbd=0`

Chicago TAZ IDs: zones 1–718 and 1733–1734 (total 720 Chicago zones).

### JSON output format (`arrive-9AM/taz_travel_times_otp*.json`)
Each file holds up to ~1,667 origin TAZs worth of results. Structure:
```json
[
  {
    "origin_taz": 1.0,
    "dest_taz": 137.0,
    "mode": "car",
    "success": true,
    "trip_patterns": [
      {
        "duration": 823,
        "distance": 5421.3,
        "legs": [...]
      }
    ],
    "retried": false
  }
]
```
- `success: true` with `trip_patterns: []` = OTP returned nothing (needs retry).
- `success: false` = OTP hard error.
- `retried: true` = was re-fetched by `taz_retry_empty_trips.py`.

---

## OTP API — Critical Facts

**Endpoint**: `http://localhost:8080/otp/transmodel/v3` (GraphQL)

**COORDINATE ORDER**: OTP GraphQL API takes `lat` then `lon` — **not** lon/lat.
This is the single most dangerous gotcha in this codebase. A lat/lon swap caused
the entire first transit collection run to fail (0% success for transit/bus/rail).

**Parameter formats** — these must be ISO 8601 duration strings, not integers:
```python
"maxAccessEgressDurationForMode": {"WALK": "PT15M"}   # ✅ correct
"maxAccessEgressDurationForMode": {"WALK": 900}        # ❌ will fail
"searchWindow": "PT2H"                                 # ✅ correct
"searchWindow": 7200                                   # ❌ will fail
```

**Arrival datetime** for 9 AM Wednesday:
```python
"2026-04-08T09:00:00-05:00"   # CDT offset; update date as needed
```
With `arriveBy: true` in the GraphQL variables.

**Mode variable structures**:
```python
# Car
{"directMode": "car"}
# Walk
{"directMode": "walk"}
# Bike
{"directMode": "bike"}
# Transit (combined)
{"transitModes": [...], "accessMode": "WALK", "egressMode": "WALK"}
# Bus only
{"transitModes": [{"mode": "BUS"}], ...}
# Rail only
{"transitModes": [{"mode": "RAIL"}, {"mode": "SUBWAY"}, ...], ...}
```

See `docs/otp-setup.md` for the full Docker command and graph build process.

---

## Python Script Conventions

- All scripts are **standalone** with `argparse` CLI arguments.
- Async OTP querying via `aiohttp` with a semaphore (limit ~18) and batch size ~55.
- **Crash-resilient**: flush to disk every 10 batches using atomic writes (write to `.tmp`,
  then `os.replace()`).
- Resume logic: pre-filter already-processed OD pairs **before** the main loop (not per-batch).
- Large datasets: process file-by-file to avoid OOM; never load all 5,136 JSON files at once.
- Plots: always use `matplotlib.use('Agg')` (non-interactive backend) and save to `plots/`
  subdirectory. Never `plt.show()`.
- Reports: always open files with `encoding="utf-8"` to avoid Windows cp1252 codec errors.
- Parallelization: two machines, one forward (TAZ 1→2926), one reverse (TAZ 2926→1).

---

## Environment

- **OS**: Windows with WSL2 + Docker Desktop
- **OTP**: run in Docker (see `docs/otp-setup.md`)
- **Python packages**: `aiohttp`, `pandas`, `numpy`, `matplotlib`, `seaborn`, `plotly`,
  `tqdm`, `openpyxl`, `pickle`, `gzip`
- **GIS**: ArcGIS Pro for map outputs
- **Notebooks**: Jupyter for EDA

---

## What NOT to Do

1. **Never swap lat/lon** — OTP wants `(lat, lon)` in that order.
2. **Never pass integer seconds** to `searchWindow` or `maxAccessEgressDurationForMode`
   — must be ISO 8601 strings like `"PT15M"`, `"PT2H"`.
3. **Never use OTP 2.9.0-SNAPSHOT** — has a NullPointerException serialization bug on
   graph load. Use stable releases with combined `--build --serve`.
4. **Never write to JSON files on every batch** — causes severe I/O bottleneck at scale.
   Flush every 10 batches.
5. **Never check resume state per-batch** — pre-filter all done pairs before the loop.
6. **Never allocate Java heap ≥ WSL2 memory ceiling** — WSL2 defaults to 50% of system RAM
   or 8 GB, whichever is smaller. Set `.wslconfig` first, then size the heap below that.
