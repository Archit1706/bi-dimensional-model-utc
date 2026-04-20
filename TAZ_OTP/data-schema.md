# Data Schema & File Formats

---

## Input Files

### `taz_new2.csv` — TAZ Centroid Lookup
The master zone reference file. All collection scripts load this.

| Column    | Type    | Description                                      |
|-----------|---------|--------------------------------------------------|
| `zone17`  | float   | TAZ identifier (e.g., 1.0, 2.0, ... 2926.0)     |
| `Lat`     | float   | Centroid latitude (WGS84)                        |
| `Lon`     | float   | Centroid longitude (WGS84)                       |
| `chicago` | int     | 1 = City of Chicago zone, 0 = suburban           |
| `cbd`     | int     | 1 = Chicago CBD zone (always chicago=1 too)      |

**Zone classification logic:**
```python
if chicago == 1 and cbd == 1:     zone_type = "CBD"
elif chicago == 1 and cbd == 0:   zone_type = "City non-CBD"
else:                              zone_type = "Suburb"
```

**Chicago TAZ IDs**: zones 1–718 and 1733–1734 (total 720 Chicago zones).
**Total zones**: 2,926.
**Total OD pairs**: 2,926 × 2,926 = 8,558,276 (or 8,558,550 including self-pairs per some scripts).

---

### `mode_split.csv` — Replica Mobility Data
Real-world observed trip flows from Replica. Separate from OTP outputs.

| Column                        | Description                            |
|-------------------------------|----------------------------------------|
| `month_starting`              | Month of observation                   |
| `origin_geo_id`               | Origin TAZ ID                          |
| `origin_geo_name`             | Origin zone name                       |
| `origin_population`           | Population of origin zone              |
| `destination_geo_id`          | Destination TAZ ID                     |
| `destination_geo_name`        | Destination zone name                  |
| `destination_population`      | Population of destination zone         |
| `walking_trip_count`          | Observed walking trips                 |
| `biking_trip_count`           | Observed biking trips                  |
| `public_transit_trip_count`   | Observed transit trips                 |
| `private_auto_trip_count`     | Observed private auto trips            |
| `on_demand_auto_trip_count`   | Observed rideshare trips               |
| `auto_passenger_trip_count`   | Observed auto passenger trips          |
| `other_travel_mode_trip_count`| Observed other mode trips              |

---

## Output Files

### JSON Collection Files

**Primary collection**: `arrive-9AM/taz_travel_times_otp{N}.json`  
**Transit recollection**: `transit-arrive-9AM/taz_recollect_otp{N}.json`

Each file contains a JSON array. Each element:
```json
{
  "origin_taz": 1.0,
  "dest_taz": 137.0,
  "mode": "car",
  "success": true,
  "trip_patterns": [
    {
      "duration": 823,
      "distance": 5421.3,
      "generalizedCost": 1234,
      "legs": [
        {
          "mode": "CAR",
          "distance": 5421.3,
          "duration": 823,
          "from": {"lat": 41.85, "lon": -87.63},
          "to": {"lat": 41.87, "lon": -87.60}
        }
      ]
    }
  ],
  "retried": false,
  "retry_timestamp": null
}
```

**Key states:**
| `success` | `trip_patterns` | Meaning |
|-----------|-----------------|---------|
| `true`    | non-empty array | Valid route found |
| `true`    | `[]`            | OTP responded but found no route → needs retry |
| `false`   | any             | OTP error |

**Transit JSON leg structure** (for transit/bus/rail modes):
```json
{
  "legs": [
    {
      "mode": "WALK",
      "distance": 412.3,
      "duration": 295,
      "from": {...},
      "to": {...}
    },
    {
      "mode": "BUS",
      "distance": 8234.1,
      "duration": 1820,
      "route": {"agency": {"name": "Chicago Transit Authority"}},
      "from": {...},
      "to": {...}
    },
    {
      "mode": "WALK",
      "distance": 215.7,
      "duration": 156
    }
  ]
}
```

**Transit agency name mapping:**
```python
AGENCY_MAP = {
    "Chicago Transit Authority": {"BUS": "cta_bus", "RAIL": "cta_rail", "SUBWAY": "cta_rail"},
    "Metra": {"RAIL": "metra_rail"},
    "Pace": {"BUS": "pace_bus"},
}
```

---

### Mode CSV Files (`csv/travel_time_{mode}.csv`)

One file per mode: `walk`, `bike`, `car`, `bus`, `rail`, `transit`

| Column             | Type    | Description                             |
|--------------------|---------|-----------------------------------------|
| `origin_taz`       | int     | Origin TAZ ID                           |
| `dest_taz`         | int     | Destination TAZ ID                      |
| `distance_miles`   | float   | Route distance in miles                 |
| `travel_time_min`  | float   | Travel time in minutes                  |

Missing pairs (routing failure) → row simply absent (not null row).

---

### `invalid_pairs.csv`
Output of `analyze_invalid_car_pairs.py`.

| Column            | Description                                 |
|-------------------|---------------------------------------------|
| `origin_taz`      | Origin TAZ                                  |
| `dest_taz`        | Destination TAZ                             |
| `failure_type`    | `dead_origin`, `dead_dest`, `isolated`, `fringe_gap` |
| `origin_zone_type`| CBD / City non-CBD / Suburb                 |
| `dest_zone_type`  | CBD / City non-CBD / Suburb                 |

---

### `foot_leg_analysis.csv`
Output of `analyze_foot_legs.py`. One row per trip pattern.

| Column                  | Description                                        |
|-------------------------|----------------------------------------------------|
| `origin_taz`            | Origin TAZ                                         |
| `dest_taz`              | Destination TAZ                                    |
| `pattern_rank`          | Rank of this pattern (1 = best/fastest)            |
| `total_duration_sec`    | Total trip duration in seconds                     |
| `total_distance_m`      | Total trip distance in meters                      |
| `foot_distance_m`       | Total walking distance in meters                   |
| `foot_duration_sec`     | Total walking time in seconds                      |
| `foot_share_pct`        | Walking as % of total trip time                    |
| `first_mile_dist_m`     | Distance of first walking leg (0 if none)          |
| `last_mile_dist_m`      | Distance of last walking leg (0 if none)           |
| `within_trip_dist_m`    | Total walking distance for transfer legs           |
| `max_walking_leg_m`     | Distance of longest single walking leg             |
| `n_walking_legs`        | Total count of walking legs in this trip           |
| `has_first_mile`        | Boolean                                            |
| `has_last_mile`         | Boolean                                            |
| `has_transfer_walk`     | Boolean                                            |

---

### `transit_combinations.csv`
Output of `transit_leg_combinations.py`.

| Column                  | Description                                        |
|-------------------------|----------------------------------------------------|
| `combination`           | Human-readable leg sequence (e.g., `foot > cta_bus > foot`) |
| `leg_count`             | Number of legs in this pattern                     |
| `trip_count`            | Number of trips using this pattern                 |
| `example_origin_taz`    | Example origin TAZ using this pattern              |
| `example_dest_taz`      | Example destination TAZ                            |
| `modes_pipe_separated`  | Machine-readable version (`foot|cta_bus|foot`)     |

---

## Scale Reference

| Metric | Value |
|--------|-------|
| Total TAZs | 2,926 |
| Total OD pairs (per mode) | ~8.56 million |
| JSON files (primary collection) | ~5,136 |
| JSON files (transit recollection) | ~1,712 |
| Records per JSON file | up to ~5,000 |
| Missing car pairs | ~64,700 (0.76%) |
| Chicago TAZs | 720 (zones 1–718, 1733–1734) |
| Suburban TAZs | 2,206 |
