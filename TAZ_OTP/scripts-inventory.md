# Scripts Inventory

Every Python script in the project, what it does, and how to run it.

---

## Primary Data Collection

### `taz_otp_matrix_json.py`
**Purpose**: Main OTP data collection script. Queries the OTP GraphQL API for all
~8.56M OD pairs across 6 modes and saves results to chunked JSON files.

**Key behavior:**
- Reads TAZ centroids from `taz_new2.csv`
- Queries OTP at `http://localhost:8080/otp/transmodel/v3`
- Runs asynchronously (`aiohttp`) with semaphore limit 18, batch size 55
- Flushes to disk every 10 batches (atomic write via `.tmp` rename)
- Pre-filters already-processed pairs on resume (efficient restart)
- Outputs to `arrive-9AM/taz_travel_times_otp{N}.json`

**Usage:**
```bash
python taz_otp_matrix_json.py --input taz_new2.csv --output-dir arrive-9AM --mode car
```

**Modes**: `walk`, `bike`, `car`, `bus`, `rail`, `transit`

**Time/arriveBy config** (edit in script):
```python
ARRIVAL_DATETIME = "2026-04-08T09:00:00-05:00"   # next Wednesday 9 AM CDT
ARRIVE_BY = True
```

---

### `taz_retry_empty_trips.py`
**Purpose**: Targeted retry for OD pairs where OTP returned `success: true` but
`trip_patterns: []` (no itinerary). Patches results in-place in the original JSON files.

**Key behavior:**
- Scans all JSON files in the output directory for `trip_patterns == []`
- Re-queries those specific pairs against OTP
- Patches the result back into the correct index in the original file
- Stamps retried entries with `retried: true` and a timestamp
- Distinguishes "genuinely unreachable" (still empty after retry) vs newly resolved
- Flush every 10 batches

**Usage:**
```bash
python taz_retry_empty_trips.py --input taz_new2.csv --output-dir arrive-9AM
```

**Status**: Script is written; full retry run needs to be completed and validated.

---

## Data Merging

### `combine_json_to_csv.py`
**Purpose**: Merges all JSON files from both collection directories into 6 mode-specific
CSV files. New transit data (from `transit-arrive-9AM/`) takes priority over old data
for any duplicate OD pairs.

**Key behavior:**
- Phase 1: Process all files from `arrive-9AM/` (all 6 modes)
- Phase 2: Merge updated transit data from `transit-arrive-9AM/`, overwriting old transit
  records for matching OD pairs
- Tracks duplicates per mode; logs how many transit records were replaced
- Produces: `travel_time_{mode}.csv` for each of the 6 modes

**Output CSV columns**: `origin_taz`, `dest_taz`, `distance_miles`, `travel_time_min`

**Usage:**
```bash
python combine_json_to_csv.py \
  --primary-dir arrive-9AM \
  --transit-dir transit-arrive-9AM \
  --output-dir csv/
```

**Known issue fixed**: Filename sorting used `int()` on filename suffix — fails if file
doesn't match the `taz_travel_times_otp{N}.json` pattern exactly. Fixed by safe parsing
with a default of 0 and a warning log.

---

### `merge_to_csv.py`
**Purpose**: Earlier version of the merge script; combines two collection runs
(original + recollect) into mode CSVs. Superseded by `combine_json_to_csv.py` for the
two-directory transit merge scenario.

---

## Quality Assurance

### `find_null.py`
**Purpose**: Scans JSON output files to identify TAZ pairs where all modes returned null
(complete routing failure). Outputs a list of failed pairs for re-collection.

**Usage:**
```bash
python find_null.py --input-dir arrive-9AM --output null_pairs.csv
```

---

### `analyze_invalid_car_pairs.py`
**Purpose**: Comprehensive analysis of missing OD pairs in the car travel time matrix.

**Key behavior:**
- Enumerates all 8,558,550 expected pairs
- Identifies the ~64,700 missing ones (0.76%)
- Classifies zones as:
  - **Dead origin**: zone has no outgoing routes at all
  - **Dead destination**: zone has no incoming routes
  - **Fully isolated**: dead both ways
  - **Partially isolated**: dead in exactly one direction
  - **Suburban fringe gap**: residual ~38,000 pairs from OSM connectivity issues
- Generates 9 plots, saves `invalid_pairs.csv`, writes plain-English summary report

**Usage:**
```bash
python analyze_invalid_car_pairs.py \
  --car-csv csv/travel_time_car.csv \
  --taz-csv taz_new2.csv \
  --output-dir outputs/
```

**Key finding**: ~64,700 missing pairs break down as:
- Dead origins → ~11,700 pairs
- Dead destinations → ~14,625 pairs
- Overlap correction → subtract double-counted
- Suburban fringe residual → ~38,000 pairs (OSM network gaps at region edge)

---

## Analysis

### `analyze_foot_legs.py`
**Purpose**: Walking burden analysis of transit trips. Parses all transit JSON files,
classifies walking legs by position, and quantifies first-mile/last-mile burden.

**Key behavior:**
- Reads ~1,712 JSON files from `transit_data/` (or `transit-arrive-9AM/`)
- Classifies each foot leg as: `first_mile`, `last_mile`, or `within_trip`
- Computes per-trip: total foot distance, total foot duration, longest walking leg,
  walking share of total trip time
- Outputs `foot_leg_analysis.csv`
- Generates structured 9-section plain-English `walking_report.txt` with:
  percentile ladders, IQR, skewness labels, zone-level burden tables, extreme trips
- Saves 18 numbered PNG plots to `plots/` using non-interactive Matplotlib backend

**Usage:**
```bash
python analyze_foot_legs.py \
  --input-dir transit-arrive-9AM \
  --output-dir outputs/
```

---

### `transit_leg_combinations.py`
**Purpose**: Catalogs all unique transit journey leg patterns across the full dataset.

**Key behavior:**
- Reads all ~1,712 transit JSON files
- Classifies legs into readable labels: `foot`, `cta_bus`, `cta_rail`, `metra_rail`,
  `pace_bus` (based on mode + transit authority fields)
- Identifies unique sequences (e.g., `foot → cta_bus → pace_bus → foot`)
- Counts frequency of each pattern
- Outputs CSV with columns: `combination`, `leg_count`, `trip_count`,
  `example_origin_taz`, `example_dest_taz`, `modes_pipe_separated`
- Also prints top-20 most common patterns to console

**Usage:**
```bash
python transit_leg_combinations.py \
  --input-dir transit-arrive-9AM \
  --output transit_combinations.csv
```

---

### `recollect.py`
**Purpose**: Re-processes only the null/incomplete TAZ pairs identified by `find_null.py`,
using the same async OTP calls as the main collection script.

---

## Replica / Mode Split Analysis (Separate Data Source)

These scripts work with **Replica mobility data** (not OTP outputs):

### `mode_split_analysis.py` (informal name)
Splits `mode_split.csv` into:
- Trips aggregated by origin TAZ
- Trips aggregated by destination TAZ
- Intra-zonal trips (origin TAZ = destination TAZ)

Adds percentage columns (each mode / total trips).

### `trip_data_visualization.py` (informal name)
Generates bar charts, pie charts, and stacked bar charts comparing mode split
across origin, destination, and intra-TAZ trip types.

---

## Jupyter EDA Notebook

A 20-cell Jupyter notebook covers:
1. Data loading and exploration
2. Mode optimality analysis (fastest mode per OD pair)
3. Transit competitiveness (transit time / car time ratio)
4. Active transport potential (walkable ≤1 mi, bikeable ≤5 mi trips)
5. Speed comparisons by mode
6. Circuity calculations (actual distance / straight-line distance)
7. Time penalty vs. car for each mode
8. Transit composition (bus-only, rail-only, mixed)
9. Distance-time relationship modeling
10. Key findings summary + CSV export

All plots are interactive Plotly; export to static PNG via `plotly.io.write_image()`.
