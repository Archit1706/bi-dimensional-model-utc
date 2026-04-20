"""
Transit Mode Generalized Speed and Time Calculator
Using the Bidimensional Transportation Model (Khisty & Sriraj)

Computes generalized speed/time for transit OD pairs in the Chicago 7-county
TAZ system, parsing per-leg OTP JSON output to apply real-world one-way fare
rules across CTA bus, CTA rail, Pace, and Metra (and walking access/egress).

Companion to walk_generalized_metrics.py / bike_generalized_metrics.py /
car_generalized_metrics.py. Same I/O conventions: outputs full / clean /
invalid CSVs in `output/`.

================================================================================
FARE MODEL — ONE-WAY TICKETS ONLY (NO DAY/MONTHLY PASSES)
================================================================================

Sources (see transit_meta/):
  - CTA:   https://www.transitchicago.com/fares/        (cta_fare.md)
  - Pace:  https://www.pacebus.com/fares                (pace_fare.md)
  - Metra: https://metra.com/fare-table                 (metra_fare.md)
           Station -> FAREZONE mapping: metrastations_taz.xls

Base one-way fares (Ventra full-fare adult, current as of 2024-2026 schedule):
  CTA bus              $2.25
  CTA 'L' rail         $2.50  (any station except O'Hare boarding)
  CTA 'L' from O'Hare  $5.00  (boarding at O'Hare Blue Line only)
  Pace local bus       $2.00  (flat fare, distance-independent)
  Pace Premium/Express $4.50  (some Pulse / express routes — applied if route
                               name pattern indicates express; else $2.00)
  Metra one-way        zone-based (see METRA_FARE_TABLE)

Transfer rules on a single Ventra one-way trip (within 2-hour transfer window,
maximum of 2 transfers per fare-paid leg group):
  CTA  -> CTA  : +$0.25  (1st transfer); +$0.00 (2nd transfer)
  CTA  -> Pace : +$0.25
  Pace -> CTA  : +$0.25
  Pace -> Pace : +$0.25
  After the 2nd transfer is consumed, the next CTA/Pace boarding is a NEW
  full-fare boarding (this is the standard Ventra rule).

Metra integration (one-way only — Link-Up / PlusBus are MONTHLY passes and
are explicitly excluded by the project requirements):
  any -> Metra : Metra is always its own full-fare ticket
  Metra -> any : the next CTA/Pace boarding is a NEW full-fare boarding

Walking legs (first-mile, last-mile, transfer walks) carry no fare; they only
contribute to total travel time and total distance.

================================================================================
BIDIMENSIONAL MODEL APPLICATION
================================================================================
For each OD pair we compute:

  access_time      = ACCESS_TIME_HOURS  (assumed wait/access at first stop)
  travel_time      = sum of in-vehicle + walking-leg durations from OTP
  total_distance   = sum of leg distances (miles)
  fixed_cost       = total fare from the leg-by-leg fare engine ($)
  variable_cost    = $0/mile  (transit fare is not distance-priced once on)

  generalized_time  = access_time + travel_time + (fixed_cost / VoT)
                                                 + (variable_cost * d / VoT)
  generalized_speed = total_distance / generalized_time

================================================================================
DATA SOURCES
================================================================================
Primary:  per-pair JSON in TAZ_OTP/data/{arrive-9AM,transit-arrive-9AM}/.
          The transit-arrive-9AM/ files take priority on duplicate (origin,dest)
          (same precedence as combine_json_to_csv.py).

Fallback: travel_time_transit.csv aggregate. If JSON for a pair is missing but
          the CSV has it, we still compute distance/time but fare cannot be
          derived from leg structure — we flag fare_estimated=True and apply a
          conservative single-boarding $2.50 fare.

Outputs (in --output-dir, default 'output/'):
  transit_generalized_metrics_full.csv
  transit_generalized_metrics_clean.csv
  transit_invalid_pairs.csv
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# CONFIGURATION
# =============================================================================

# --- Bidimensional model parameters ---
ACCESS_TIME_MINS = 5                              # minutes — initial wait/access
ACCESS_TIME_HOURS = ACCESS_TIME_MINS / 60.0
VARIABLE_COST_PER_MILE = 0.00                     # transit fare not per-mile

# --- VoT income brackets ($/hour) -- match car/bike/walk scripts ---
VOT_LEVELS: Dict[str, float] = {
    "low":  14.64,
    "mid":  30.62,
    "high": 80.84,
}

# --- CTA one-way fares ---
CTA_BUS_FARE          = 2.25
CTA_RAIL_FARE         = 2.50
CTA_RAIL_OHARE_FARE   = 5.00
CTA_TRANSFER_FARE     = 0.25     # 1st transfer cost
CTA_TRANSFER_FREE     = 0.00     # 2nd transfer cost
TRANSFER_WINDOW_HOURS = 2.0
MAX_TRANSFERS         = 2

# --- Pace one-way fares ---
PACE_LOCAL_FARE       = 2.00
PACE_EXPRESS_FARE     = 4.50     # Pulse Premium / Express routes
PACE_EXPRESS_KEYWORDS = ("PREMIUM", "EXPRESS", "PULSE")  # route name match

# --- Metra one-way fare table (zone-pair -> $) ---
# From metra_fare.md. Distance-based: fare depends on the highest and lowest
# fare zones traversed by the leg.
#   1<->2  $3.75
#   1<->3  $5.50
#   1<->4  $6.75
#   2<->2  $3.75   (intra-zone)
#   2<->3  $3.75
#   2<->4  $3.75
#   3<->3  $3.75
#   3<->4  $3.75
#   4<->4  $3.75
# Rule of thumb from Metra: trips not touching Zone 1 are flat $3.75;
# trips touching Zone 1 are priced by the outer zone.
METRA_FARES_TOUCHING_Z1 = {1: 3.75, 2: 3.75, 3: 5.50, 4: 6.75}
METRA_FARE_NON_Z1       = 3.75

# --- O'Hare CTA station detection ---
# Used to decide whether to charge $5 or $2.50 for an L boarding.
OHARE_STATION_KEYWORDS = ("O'HARE", "OHARE", "O HARE")

# --- Default file paths (overridable on the CLI) ---
DEFAULT_TAZ_FILE        = "taz.xlsx"
DEFAULT_TAZ_CENTROID    = "TAZ_OTP/data/taz_new2.csv"
DEFAULT_METRA_STATIONS  = "transit_meta/metrastations_taz.xls"
DEFAULT_TRANSIT_CSV     = "TAZ_OTP/data/csv/travel_time_transit.csv"
DEFAULT_JSON_DIRS       = [
    "TAZ_OTP/data/transit-arrive-9AM",   # higher priority (recollected)
    "TAZ_OTP/data/arrive-9AM",
]
DEFAULT_OUTPUT_DIR      = "output"

# --- Zone classification fixed cost (kept for parity with car script; transit
#     does not pay parking, so all zone-type fixed costs are $0 here.) ---
FIXED_COST_BY_ZONE = {"CBD": 0.00, "City_non_CBD": 0.00, "Suburb": 0.00,
                      "Unknown": 0.00}


# =============================================================================
# AGENCY / MODE NORMALIZATION
# =============================================================================

# Match the AGENCY_MAP in TAZ_OTP/data-schema.md.
AGENCY_MAP = {
    "Chicago Transit Authority": {"BUS": "cta_bus", "RAIL": "cta_rail",
                                  "SUBWAY": "cta_rail", "TRAM": "cta_rail"},
    "CTA":   {"BUS": "cta_bus", "RAIL": "cta_rail", "SUBWAY": "cta_rail"},
    "Metra": {"RAIL": "metra_rail", "TRAM": "metra_rail"},
    "Pace":  {"BUS": "pace_bus"},
}

WALK_LEG_MODES = {"WALK", "FOOT"}


def classify_leg(leg: dict) -> str:
    """
    Normalize an OTP leg into one of:
      walk | cta_bus | cta_rail | metra_rail | pace_bus | unknown_transit
    """
    mode = (leg.get("mode") or "").upper()
    if mode in WALK_LEG_MODES:
        return "walk"

    # Best-effort agency lookup
    route = leg.get("route") or {}
    agency = (route.get("agency") or {}).get("name", "") or ""
    by_agency = AGENCY_MAP.get(agency)
    if by_agency:
        return by_agency.get(mode, "unknown_transit")

    # Fallback: try matching common short names
    short = (route.get("shortName") or "").upper()
    long_name = (route.get("longName") or "").upper()
    if "METRA" in agency.upper() or "METRA" in long_name:
        return "metra_rail"
    if "PACE" in agency.upper():
        return "pace_bus"
    if mode in ("RAIL", "SUBWAY", "TRAM"):
        return "cta_rail"
    if mode == "BUS":
        return "cta_bus"
    return "unknown_transit"


def is_ohare_boarding(leg: dict) -> bool:
    name = ((leg.get("from") or {}).get("name") or "").upper()
    if not name:
        return False
    return any(kw in name for kw in OHARE_STATION_KEYWORDS)


def is_pace_express(leg: dict) -> bool:
    route = leg.get("route") or {}
    text = " ".join([
        str(route.get("shortName") or ""),
        str(route.get("longName")  or ""),
    ]).upper()
    return any(kw in text for kw in PACE_EXPRESS_KEYWORDS)


# =============================================================================
# METRA FARE
# =============================================================================

def metra_fare(zone_a: Optional[int], zone_b: Optional[int]) -> float:
    """
    One-way Metra fare for a single Metra leg, given boarding and alighting
    fare zones. Zones outside 1..4 fall back to $3.75 ('all other zones' rule).
    """
    if zone_a is None or zone_b is None:
        return METRA_FARE_NON_Z1
    lo, hi = sorted((int(zone_a), int(zone_b)))
    if lo == 1:
        return METRA_FARES_TOUCHING_Z1.get(hi, METRA_FARE_NON_Z1)
    return METRA_FARE_NON_Z1


# =============================================================================
# METRA STATION LOOKUP (for resolving fare zones from leg coordinates)
# =============================================================================

@dataclass
class MetraStation:
    station_id: int
    name: str
    farezone: int
    taz: Optional[float]
    lat: Optional[float] = None
    lon: Optional[float] = None


def load_metra_stations(stations_path: str,
                        taz_centroid_path: Optional[str] = None
                        ) -> List[MetraStation]:
    """
    Load Metra stations and attach a (lat, lon) — taken from the centroid of
    each station's TAZ (zone17) when a centroid file is available. The xls in
    transit_meta/metrastations_taz.xls does not carry station lat/lon directly
    so we proxy via the TAZ centroid, which is sufficient for nearest-station
    matching against an OTP leg's from/to coordinates.
    """
    stations: List[MetraStation] = []
    if not os.path.exists(stations_path):
        print(f"  [warn] Metra station file not found: {stations_path}")
        return stations

    try:
        df = pd.read_excel(stations_path)
    except ImportError as e:
        print(f"  [warn] Could not read {stations_path} ({e}). "
              "Install xlrd to enable Metra fare-zone lookup.")
        return stations

    centroid_lookup: Dict[float, Tuple[float, float]] = {}
    if taz_centroid_path and os.path.exists(taz_centroid_path):
        cdf = pd.read_csv(taz_centroid_path)
        for _, r in cdf.iterrows():
            try:
                centroid_lookup[float(r["zone17"])] = (float(r["Lat"]),
                                                       float(r["Lon"]))
            except (KeyError, ValueError, TypeError):
                continue

    for _, r in df.iterrows():
        try:
            zone17 = float(r.get("zone17"))
        except (TypeError, ValueError):
            zone17 = None
        try:
            farezone = int(r.get("FAREZONE"))
        except (TypeError, ValueError):
            continue  # cannot price without a zone

        latlon = centroid_lookup.get(zone17, (None, None))
        stations.append(MetraStation(
            station_id=int(r.get("STATION_ID", 0) or 0),
            name=str(r.get("LONGNAME") or r.get("SHORTNAME") or ""),
            farezone=farezone,
            taz=zone17,
            lat=latlon[0],
            lon=latlon[1],
        ))
    print(f"  Loaded {len(stations)} Metra stations "
          f"({sum(1 for s in stations if s.lat is not None)} with coords)")
    return stations


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    R = 3958.7613  # earth radius (miles)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_metra_zone(lat: Optional[float], lon: Optional[float],
                       stations: List[MetraStation]) -> Optional[int]:
    """Return the FAREZONE of the nearest Metra station to (lat, lon)."""
    if lat is None or lon is None or not stations:
        return None
    best, best_d = None, float("inf")
    for s in stations:
        if s.lat is None or s.lon is None:
            continue
        d = _haversine_miles(lat, lon, s.lat, s.lon)
        if d < best_d:
            best_d, best = d, s
    return best.farezone if best is not None else None


# =============================================================================
# FARE ENGINE
# =============================================================================

@dataclass
class FareBreakdown:
    total_fare: float = 0.0
    boardings: int = 0
    transfers_used: int = 0
    detail: List[str] = field(default_factory=list)


def compute_trip_fare(legs: List[dict],
                      metra_stations: List[MetraStation]) -> FareBreakdown:
    """
    Walk the leg list in order and apply Ventra one-way fare + transfer rules.

    Resets transfer state after a Metra leg, and after the 2-hour transfer
    window or 2-transfer cap is exhausted.
    """
    fb = FareBreakdown()

    # State for the current 'fare group' (a single boarding that may carry
    # transfer privileges).
    transfer_count = 0           # number of transfers consumed in this group
    transfers_avail = False      # True if last paid leg was CTA/Pace
    group_start_time_sec = None  # OTP startTime in epoch ms or seconds (best effort)
    last_leg_end_time_sec = None

    def leg_start_sec(leg: dict) -> Optional[float]:
        # OTP exposes startTime/endTime in ms (epoch); fall back to None.
        for key in ("startTime", "from"):
            v = leg.get(key)
            if isinstance(v, (int, float)):
                return v / 1000.0
            if isinstance(v, dict) and isinstance(v.get("departure"), (int, float)):
                return v["departure"] / 1000.0
        return None

    def within_window(now_sec: Optional[float]) -> bool:
        if group_start_time_sec is None or now_sec is None:
            return True  # if we can't tell, give the rider the benefit of the doubt
        return (now_sec - group_start_time_sec) <= TRANSFER_WINDOW_HOURS * 3600

    for leg in legs:
        kind = classify_leg(leg)
        if kind == "walk" or kind == "unknown_transit":
            # walks don't end transfer privileges; unknown legs we skip pricing
            # but allow downstream legs to still chain
            continue

        now = leg_start_sec(leg)

        if kind == "metra_rail":
            # Metra is always its own full-fare ticket on one-way.
            zone_from = nearest_metra_zone(
                (leg.get("from") or {}).get("lat"),
                (leg.get("from") or {}).get("lon"),
                metra_stations,
            )
            zone_to = nearest_metra_zone(
                (leg.get("to") or {}).get("lat"),
                (leg.get("to") or {}).get("lon"),
                metra_stations,
            )
            fare = metra_fare(zone_from, zone_to)
            fb.total_fare += fare
            fb.boardings += 1
            fb.detail.append(
                f"metra_rail z{zone_from}->z{zone_to} ${fare:.2f}"
            )
            # Metra does not extend or accept Ventra transfer privileges
            # on a one-way ticket, so reset the CTA/Pace transfer group.
            transfer_count = 0
            transfers_avail = False
            group_start_time_sec = None
            last_leg_end_time_sec = now
            continue

        # CTA bus / CTA rail / Pace bus
        # Decide base fare for this boarding type
        if kind == "cta_bus":
            base = CTA_BUS_FARE
        elif kind == "cta_rail":
            base = CTA_RAIL_OHARE_FARE if is_ohare_boarding(leg) else CTA_RAIL_FARE
        elif kind == "pace_bus":
            base = PACE_EXPRESS_FARE if is_pace_express(leg) else PACE_LOCAL_FARE
        else:
            base = CTA_BUS_FARE  # safe default

        # Determine if this leg uses a transfer or starts a new fare group
        if (transfers_avail
                and transfer_count < MAX_TRANSFERS
                and within_window(now)):
            # Use a transfer
            if transfer_count == 0:
                cost = CTA_TRANSFER_FARE       # 1st transfer = $0.25
            else:
                cost = CTA_TRANSFER_FREE       # 2nd transfer = free
            fb.total_fare += cost
            fb.transfers_used += 1
            transfer_count += 1
            fb.detail.append(f"{kind} (transfer #{transfer_count}) ${cost:.2f}")
            # transfers_avail stays True until cap reached
            if transfer_count >= MAX_TRANSFERS:
                transfers_avail = False
        else:
            # New full-fare boarding -> opens a new fare group
            fb.total_fare += base
            fb.boardings += 1
            transfer_count = 0
            transfers_avail = True
            group_start_time_sec = now if now is not None else group_start_time_sec
            fb.detail.append(f"{kind} (boarding) ${base:.2f}")

        last_leg_end_time_sec = now

    return fb


# =============================================================================
# JSON LOADING
# =============================================================================

def _iter_json_files(dirs: Iterable[str]) -> Iterable[Path]:
    for d in dirs:
        p = Path(d)
        if not p.exists():
            continue
        for f in sorted(p.glob("*.json")):
            yield f


def load_transit_pairs_from_json(dirs: Iterable[str]) -> Dict[Tuple[float, float], dict]:
    """
    Walk every JSON file in the given dirs (in order — earlier dirs win on
    duplicate keys, matching combine_json_to_csv.py precedence) and return a
    {(origin_taz, dest_taz): best_trip_pattern_with_metadata} dict.

    Filters to entries with mode in {transit, bus, rail}. The first non-empty
    trip_patterns[0] for an OD pair is treated as the 'best' pattern.
    """
    out: Dict[Tuple[float, float], dict] = {}
    files_seen = 0
    pairs_seen = 0

    for jpath in _iter_json_files(dirs):
        files_seen += 1
        try:
            with open(jpath, "r", encoding="utf-8") as fh:
                records = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [warn] could not read {jpath.name}: {e}")
            continue

        for rec in records:
            mode = (rec.get("mode") or "").lower()
            if mode not in {"transit", "bus", "rail"}:
                continue
            if not rec.get("success"):
                continue
            patterns = rec.get("trip_patterns") or []
            if not patterns:
                continue
            key = (rec.get("origin_taz"), rec.get("dest_taz"))
            if key in out:
                continue  # earlier (higher-priority) directory already populated
            best = patterns[0]
            out[key] = {
                "duration_sec": best.get("duration"),
                "distance_m":   best.get("distance"),
                "legs":         best.get("legs") or [],
            }
            pairs_seen += 1

    print(f"  Scanned {files_seen} JSON file(s); collected {len(out)} OD pairs")
    return out


# =============================================================================
# TAZ CLASSIFICATION
# =============================================================================

def load_taz_classifications(taz_filepath: str
                             ) -> Tuple[Dict[float, str], Dict[float, float]]:
    """
    Same loader as car_generalized_metrics.py — supports both .xlsx and .csv.
    """
    print(f"Loading TAZ classifications from: {taz_filepath}")
    if taz_filepath.lower().endswith(".csv"):
        df = pd.read_csv(taz_filepath)
    else:
        df = pd.read_excel(taz_filepath, sheet_name=0)

    required = ["zone17", "cbd", "chicago"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in TAZ file: {missing}")

    classifications: Dict[float, str] = {}
    fixed_costs:     Dict[float, float] = {}
    for _, row in df.iterrows():
        zid = row["zone17"]
        chicago, cbd = row["chicago"], row["cbd"]
        if chicago == 1 and cbd == 1:
            cls = "CBD"
        elif chicago == 0 and cbd == 0:
            cls = "Suburb"
        elif chicago == 1 and cbd == 0:
            cls = "City_non_CBD"
        else:
            cls = "Other"
        classifications[zid] = cls
        fixed_costs[zid] = FIXED_COST_BY_ZONE.get(cls, 0.0)

    counts = pd.Series(list(classifications.values())).value_counts()
    print(f"  Loaded {len(classifications)} TAZ zones — {counts.to_dict()}")
    return classifications, fixed_costs


# =============================================================================
# PER-PAIR PROCESSING
# =============================================================================

METERS_PER_MILE = 1609.344


@dataclass
class TripSummary:
    distance_miles: float
    travel_time_mins: float
    fare: float
    boardings: int
    transfers_used: int
    fare_detail: str
    fare_estimated: bool
    leg_sequence: str  # pipe-separated mode list, e.g. 'walk|cta_bus|walk'


def summarize_trip(pattern: Optional[dict],
                   metra_stations: List[MetraStation],
                   csv_distance_miles: Optional[float],
                   csv_time_mins: Optional[float]) -> Optional[TripSummary]:
    """
    Convert a JSON trip pattern into a TripSummary. Falls back to CSV
    distance/time + a conservative single-boarding fare if no JSON pattern
    is available.
    """
    if pattern is not None:
        legs = pattern.get("legs") or []
        # Distance: prefer summed leg distances; fall back to pattern distance
        leg_dist_m = sum((l.get("distance") or 0.0) for l in legs)
        total_m = leg_dist_m if leg_dist_m > 0 else (pattern.get("distance_m") or 0.0)
        # Time: prefer pattern duration; fall back to summed leg duration
        total_sec = pattern.get("duration_sec") or sum(
            (l.get("duration") or 0.0) for l in legs
        )

        if total_m <= 0 or total_sec <= 0:
            return None

        fb = compute_trip_fare(legs, metra_stations)
        seq = "|".join(classify_leg(l) for l in legs) if legs else ""

        return TripSummary(
            distance_miles=total_m / METERS_PER_MILE,
            travel_time_mins=total_sec / 60.0,
            fare=fb.total_fare,
            boardings=fb.boardings,
            transfers_used=fb.transfers_used,
            fare_detail="; ".join(fb.detail),
            fare_estimated=False,
            leg_sequence=seq,
        )

    # Fallback to CSV-only
    if csv_distance_miles and csv_time_mins and csv_distance_miles > 0 and csv_time_mins > 0:
        return TripSummary(
            distance_miles=float(csv_distance_miles),
            travel_time_mins=float(csv_time_mins),
            fare=CTA_RAIL_FARE,           # conservative default
            boardings=1,
            transfers_used=0,
            fare_detail="estimated single CTA boarding (no JSON leg detail)",
            fare_estimated=True,
            leg_sequence="",
        )
    return None


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def build_dataframe(json_pairs: Dict[Tuple[float, float], dict],
                    csv_path: Optional[str],
                    metra_stations: List[MetraStation]) -> pd.DataFrame:
    """
    Build the per-OD-pair dataframe by iterating the union of JSON keys and
    CSV rows. CSV rows without JSON get the fallback fare estimate.
    """
    csv_index: Dict[Tuple[float, float], Tuple[float, float]] = {}
    if csv_path and os.path.exists(csv_path):
        print(f"\nLoading transit CSV fallback: {csv_path}")
        cdf = pd.read_csv(csv_path)
        # Accept either {origin_taz,dest_taz,distance_miles,travel_time_min}
        # or the bidim convention {origin_taz,destination_taz,
        #                          travel_distance_miles,travel_time_mins}
        col_o = "origin_taz"
        col_d = "destination_taz" if "destination_taz" in cdf.columns else "dest_taz"
        col_dist = ("travel_distance_miles" if "travel_distance_miles" in cdf.columns
                    else "distance_miles")
        col_time = ("travel_time_mins" if "travel_time_mins" in cdf.columns
                    else "travel_time_min")
        for _, r in cdf.iterrows():
            csv_index[(r[col_o], r[col_d])] = (r.get(col_dist), r.get(col_time))
        print(f"  CSV holds {len(csv_index)} OD pairs")
    else:
        print("\n[info] No transit CSV provided; using JSON-only OD pairs.")

    keys = set(json_pairs.keys()) | set(csv_index.keys())
    print(f"\nProcessing {len(keys)} unique OD pairs...")

    rows = []
    for (o, d) in keys:
        pattern = json_pairs.get((o, d))
        cdist, ctime = csv_index.get((o, d), (None, None))
        ts = summarize_trip(pattern, metra_stations, cdist, ctime)
        if ts is None:
            rows.append({
                "origin_taz": o, "destination_taz": d,
                "is_valid": False, "invalid_reason": "no usable trip data",
                "travel_distance_miles": np.nan, "travel_time_mins": np.nan,
                "fare": np.nan, "boardings": 0, "transfers_used": 0,
                "fare_detail": "", "fare_estimated": False,
                "leg_sequence": "",
            })
        else:
            rows.append({
                "origin_taz": o, "destination_taz": d,
                "is_valid": True, "invalid_reason": "",
                "travel_distance_miles": ts.distance_miles,
                "travel_time_mins": ts.travel_time_mins,
                "fare": ts.fare,
                "boardings": ts.boardings,
                "transfers_used": ts.transfers_used,
                "fare_detail": ts.fare_detail,
                "fare_estimated": ts.fare_estimated,
                "leg_sequence": ts.leg_sequence,
            })
    return pd.DataFrame(rows)


def calculate_generalized_metrics(df: pd.DataFrame,
                                  zone_classifications: Dict[float, str],
                                  vot_levels: Dict[str, float]) -> pd.DataFrame:
    """
    Apply the bidimensional model. fixed_cost = trip fare ($).
    """
    print("\nCalculating generalized metrics...")
    df = df.copy()
    df["travel_time_hours"] = df["travel_time_mins"] / 60.0
    df["dest_classification"] = df["destination_taz"].map(zone_classifications).fillna("Unknown")
    df["modal_speed_mph"] = np.where(
        df["is_valid"] & (df["travel_time_hours"] > 0),
        df["travel_distance_miles"] / df["travel_time_hours"],
        np.nan,
    )

    for vot_name, vot in vot_levels.items():
        gt_col = f"generalized_time_hours_{vot_name}"
        gs_col = f"generalized_speed_mph_{vot_name}"
        df[gt_col] = (
            ACCESS_TIME_HOURS
            + df["travel_time_hours"]
            + (df["fare"] / vot)
            + (VARIABLE_COST_PER_MILE * df["travel_distance_miles"] / vot)
        )
        df[gs_col] = df["travel_distance_miles"] / df[gt_col]
        df.loc[~df["is_valid"], [gt_col, gs_col]] = np.nan
    return df


def save_outputs(df: pd.DataFrame, output_dir: str):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    full = out / "transit_generalized_metrics_full.csv"
    df.to_csv(full, index=False)
    print(f"\nFull results       -> {full}")

    valid = df[df["is_valid"]].copy()
    essential = [
        "origin_taz", "destination_taz", "dest_classification",
        "travel_distance_miles", "travel_time_mins", "modal_speed_mph",
        "fare", "boardings", "transfers_used", "fare_estimated",
        "leg_sequence",
    ]
    for vot in VOT_LEVELS:
        essential += [f"generalized_time_hours_{vot}",
                      f"generalized_speed_mph_{vot}"]
    clean = out / "transit_generalized_metrics_clean.csv"
    valid[essential].to_csv(clean, index=False)
    print(f"Clean results      -> {clean}")

    invalid = df[~df["is_valid"]].copy()
    if len(invalid):
        ipath = out / "transit_invalid_pairs.csv"
        invalid.to_csv(ipath, index=False)
        print(f"Invalid pairs      -> {ipath}")


def generate_statistics(df: pd.DataFrame):
    print("\n" + "=" * 80)
    print("TRANSIT SUMMARY STATISTICS")
    print("=" * 80)
    valid = df[df["is_valid"]]
    print(f"Total OD pairs:        {len(df):,}")
    print(f"Valid:                 {len(valid):,}")
    print(f"Invalid:               {len(df) - len(valid):,}")
    if not len(valid):
        return
    print(f"Fare-estimated pairs:  {valid['fare_estimated'].sum():,}")
    print(f"Mean boardings/trip:   {valid['boardings'].mean():.2f}")
    print(f"Mean transfers/trip:   {valid['transfers_used'].mean():.2f}")
    print(f"Mean fare:             ${valid['fare'].mean():.2f}")
    print(f"Median fare:           ${valid['fare'].median():.2f}")
    print(f"Max fare:              ${valid['fare'].max():.2f}")
    print(f"Mean travel time:      {valid['travel_time_mins'].mean():.1f} min")
    print(f"Mean modal speed:      {valid['modal_speed_mph'].mean():.2f} mph")
    for vot_name, vot in VOT_LEVELS.items():
        gs = valid[f"generalized_speed_mph_{vot_name}"]
        gt = valid[f"generalized_time_hours_{vot_name}"]
        print(f"\nVoT {vot_name} (${vot}/hr):")
        print(f"  gen speed mean: {gs.mean():.2f} mph   "
              f"gen time mean:  {gt.mean()*60:.1f} min")


def main():
    ap = argparse.ArgumentParser(
        description="Transit bidimensional generalized speed/time calculator")
    ap.add_argument("--taz-file",       default=DEFAULT_TAZ_FILE,
                    help="TAZ classification (xlsx or csv with zone17/chicago/cbd)")
    ap.add_argument("--taz-centroids",  default=DEFAULT_TAZ_CENTROID,
                    help="taz_new2.csv with zone17/Lat/Lon (used for Metra station coords)")
    ap.add_argument("--metra-stations", default=DEFAULT_METRA_STATIONS,
                    help="metrastations_taz.xls (STATION_ID, FAREZONE, zone17, ...)")
    ap.add_argument("--transit-csv",    default=DEFAULT_TRANSIT_CSV,
                    help="Aggregate transit CSV fallback (origin_taz, dest_taz, distance, time)")
    ap.add_argument("--json-dir", action="append", default=None,
                    help="Directory of OTP JSON files. Repeat to add multiple "
                         "(earlier dirs take priority on duplicates).")
    ap.add_argument("--output-dir",     default=DEFAULT_OUTPUT_DIR)
    args = ap.parse_args()

    json_dirs = args.json_dir or DEFAULT_JSON_DIRS

    print("=" * 80)
    print("TRANSIT MODE GENERALIZED METRICS CALCULATOR")
    print("Bidimensional Transportation Model (Khisty & Sriraj)")
    print("=" * 80)
    print(f"\n--- Parameters ---")
    print(f"Access time:        {ACCESS_TIME_MINS} min")
    print(f"Variable cost:      ${VARIABLE_COST_PER_MILE}/mile (transit fare not per-mile)")
    print(f"VoT levels:         {VOT_LEVELS}")
    print(f"Transfer window:    {TRANSFER_WINDOW_HOURS} hours, max {MAX_TRANSFERS} transfers")
    print(f"CTA bus / rail / O'Hare: ${CTA_BUS_FARE} / ${CTA_RAIL_FARE} / ${CTA_RAIL_OHARE_FARE}")
    print(f"Pace local / express:    ${PACE_LOCAL_FARE} / ${PACE_EXPRESS_FARE}")
    print(f"Metra one-way table:     touching Z1 -> {METRA_FARES_TOUCHING_Z1}, "
          f"non-Z1 flat ${METRA_FARE_NON_Z1}")

    print("\n--- Loading reference data ---")
    zone_class, _ = load_taz_classifications(args.taz_file) \
        if os.path.exists(args.taz_file) else ({}, {})
    if not zone_class:
        print(f"  [warn] TAZ classifications not loaded from {args.taz_file}; "
              "destinations will be marked 'Unknown'.")
    metra_stations = load_metra_stations(args.metra_stations, args.taz_centroids)

    print("\n--- Loading OTP JSON ---")
    json_pairs = load_transit_pairs_from_json(json_dirs)

    df = build_dataframe(json_pairs, args.transit_csv, metra_stations)
    df = calculate_generalized_metrics(df, zone_class, VOT_LEVELS)

    generate_statistics(df)
    save_outputs(df, args.output_dir)

    print("\n" + "=" * 80)
    print("Processing complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
