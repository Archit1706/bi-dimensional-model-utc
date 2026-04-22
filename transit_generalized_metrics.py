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
For each OD pair we split the OTP total duration into two buckets to avoid
double-counting:

  access_time    = duration of the FIRST foot leg only (origin -> first stop).
                   If the first leg is not a foot leg, access_time = 0.
  travel_time    = total_duration - access_time, i.e. in-vehicle time + any
                   transfer-walk legs + the last-mile (egress) foot leg.
                   Transfer walks are part of travel_time because they happen
                   between vehicles, not before boarding the first one.
  total_distance = sum of all leg distances (miles) = OTP total_distance_miles
  fixed_cost     = total fare from the leg-by-leg fare engine ($)
  variable_cost  = $0/mile  (transit fare is not distance-priced once on)

Formulas (units: miles, hours, $):

  generalized_speed = (distance * VoT) /
                      (VoT*(access_time + travel_time) + fixed_cost
                       + variable_cost * distance)
  generalized_time  = access_time + (distance / modal_speed)
                      + (fixed_cost / VoT) + (variable_cost * distance / VoT)

  where modal_speed = distance / travel_time  (so distance / modal_speed
  is just travel_time; the two formulas are equivalent).

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
import csv
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# CONFIGURATION
# =============================================================================

# --- Bidimensional model parameters ---
# Access time is computed PER TRIP from the first foot leg (see summarize_trip);
# this module-level constant is only the fallback for CSV-only rows that have
# no leg breakdown available.
ACCESS_TIME_MINS_FALLBACK = 0                      # minutes
ACCESS_TIME_HOURS_FALLBACK = ACCESS_TIME_MINS_FALLBACK / 60.0
VARIABLE_COST_PER_MILE = 0.00                      # transit fare not per-mile

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
DEFAULT_TAZ_FILE        = "taz_new.csv"   # zone17, chicago, cbd, Lat, Lon
DEFAULT_METRA_STATIONS  = "transit_meta/metrastations_taz.xls"
# Candidate locations for the aggregate transit CSV — tried in order.
# Pass --transit-csv explicitly to override.
DEFAULT_TRANSIT_CSV_CANDIDATES = [
    "travel_time_transit.csv",
    "TAZ_OTP/data/csv/travel_time_transit.csv",
    "data/csv/travel_time_transit.csv",
    "csv/travel_time_transit.csv",
]
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


def _leg_transit_info(leg: dict) -> dict:
    return leg.get("transit_info") or leg.get("route") or {}


def _leg_agency(leg: dict) -> str:
    ti = _leg_transit_info(leg)
    # New schema: transit_info.authority_name / authority_id
    agency = ti.get("authority_name") or ""
    if not agency:
        # Legacy shape: route.agency.name
        agency = (ti.get("agency") or {}).get("name", "") if isinstance(ti.get("agency"), dict) else ""
    if not agency:
        # Infer from authority_id prefix (e.g. 'cta:50066', 'metra:...', 'pace:...')
        aid = (ti.get("authority_id") or "").lower()
        if aid.startswith("cta"):   return "Chicago Transit Authority"
        if aid.startswith("metra"): return "Metra"
        if aid.startswith("pace"):  return "Pace"
    return agency


def classify_leg(leg: dict) -> str:
    """
    Normalize an OTP leg into one of:
      walk | cta_bus | cta_rail | metra_rail | pace_bus | unknown_transit
    """
    mode = (leg.get("mode") or "").upper()
    if mode in WALK_LEG_MODES:
        return "walk"

    agency = _leg_agency(leg)
    by_agency = AGENCY_MAP.get(agency)
    if by_agency:
        mapped = by_agency.get(mode)
        if mapped:
            return mapped

    # Fallbacks
    ti = _leg_transit_info(leg)
    long_name = (ti.get("line_name") or ti.get("longName") or "").upper()
    if "METRA" in agency.upper() or "METRA" in long_name:
        return "metra_rail"
    if "PACE" in agency.upper():
        return "pace_bus"
    if mode in ("RAIL", "SUBWAY", "TRAM", "METRO"):
        return "cta_rail"
    if mode == "BUS":
        return "cta_bus"
    return "unknown_transit"


def _leg_from_name(leg: dict) -> str:
    fp = leg.get("from_place") or leg.get("from") or {}
    return (fp.get("name") or "").upper()


def _leg_to_name(leg: dict) -> str:
    tp = leg.get("to_place") or leg.get("to") or {}
    return (tp.get("name") or "").upper()


def is_ohare_boarding(leg: dict) -> bool:
    name = _leg_from_name(leg)
    if not name:
        return False
    return any(kw in name for kw in OHARE_STATION_KEYWORDS)


def is_pace_express(leg: dict) -> bool:
    ti = _leg_transit_info(leg)
    text = " ".join([
        str(ti.get("line_public_code") or ti.get("shortName") or ""),
        str(ti.get("line_name")        or ti.get("longName")  or ""),
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
    name_norm: str = ""


def _norm_station_name(s: str) -> str:
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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
        if taz_centroid_path.lower().endswith(".csv"):
            cdf = pd.read_csv(taz_centroid_path)
        else:
            cdf = pd.read_excel(taz_centroid_path, sheet_name=0)
        if "Lat" in cdf.columns and "Lon" in cdf.columns:
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
        name = str(r.get("LONGNAME") or r.get("SHORTNAME") or "")
        stations.append(MetraStation(
            station_id=int(r.get("STATION_ID", 0) or 0),
            name=name,
            farezone=farezone,
            taz=zone17,
            lat=latlon[0],
            lon=latlon[1],
            name_norm=_norm_station_name(name),
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


def metra_zone_for_leg_endpoint(name: str,
                                stations: List[MetraStation]) -> Optional[int]:
    """
    Resolve a Metra fare zone from a station NAME (e.g. 'Schiller Park',
    'Geneva'). Used because the OTP transit JSON exposes only stop name +
    quay_id (no lat/lon) on the leg endpoints.

    Strategy: normalize and look for the station whose name appears in,
    or contains, the leg's place name. Returns None if no confident match.
    """
    if not name or not stations:
        return None
    n = _norm_station_name(name)
    if not n:
        return None
    # Exact match first
    for s in stations:
        if s.name_norm and s.name_norm == n:
            return s.farezone
    # Substring match (leg name contains station, or vice-versa)
    best = None
    best_len = 0
    for s in stations:
        if not s.name_norm:
            continue
        if s.name_norm in n or n in s.name_norm:
            if len(s.name_norm) > best_len:
                best, best_len = s, len(s.name_norm)
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
        # New schema: ISO 8601 strings in 'expected_start_time'/'aimed_start_time'
        for key in ("expected_start_time", "aimed_start_time"):
            v = leg.get(key)
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v).timestamp()
                except ValueError:
                    continue
        # Legacy: epoch ms
        for key in ("startTime",):
            v = leg.get(key)
            if isinstance(v, (int, float)):
                return v / 1000.0
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
            # Try station-name match first (new OTP schema lacks lat/lon on legs);
            # fall back to coordinate-based nearest-station if available.
            from_name = _leg_from_name(leg)
            to_name   = _leg_to_name(leg)
            zone_from = metra_zone_for_leg_endpoint(from_name, metra_stations)
            zone_to   = metra_zone_for_leg_endpoint(to_name,   metra_stations)
            if zone_from is None:
                zone_from = nearest_metra_zone(
                    (leg.get("from") or {}).get("lat"),
                    (leg.get("from") or {}).get("lon"),
                    metra_stations,
                )
            if zone_to is None:
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


def _iter_records(payload) -> Iterable[dict]:
    """Yield trip records from either {trip_data:[...]} (current) or bare-list (legacy)."""
    if isinstance(payload, dict):
        records = payload.get("trip_data") or payload.get("results") or []
    elif isinstance(payload, list):
        records = payload
    else:
        return
    for rec in records:
        if isinstance(rec, dict):
            yield rec


def _extract_pattern(rec: dict) -> Optional[dict]:
    """Return a normalized pattern-summary dict from a trip record, or None."""
    if (rec.get("mode") or "").lower() not in {"transit", "bus", "rail"}:
        return None
    if not rec.get("success"):
        return None
    patterns = rec.get("trip_patterns") or []
    if not patterns:
        return None
    best = patterns[0]
    return {
        "duration_sec":   best.get("total_duration_seconds") or best.get("duration"),
        "distance_m":     best.get("total_distance_meters")  or best.get("distance"),
        "distance_miles": best.get("total_distance_miles"),
        "legs":           best.get("legs") or [],
    }


def _record_od(rec: dict) -> Tuple[Optional[float], Optional[float]]:
    o = rec.get("origin_zone")      if "origin_zone"      in rec else rec.get("origin_taz")
    d = rec.get("destination_zone") if "destination_zone" in rec else rec.get("dest_taz")
    return o, d


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
    access_time_mins: float      # first foot leg only (origin -> first stop)
    travel_time_mins: float      # total - access (in-vehicle + transfer + egress walks)
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

        def leg_dist_m(l):
            return l.get("distance_meters") or l.get("distance") or 0.0

        def leg_dur_sec(l):
            return l.get("duration_seconds") or l.get("duration") or 0.0

        # Distance: prefer pattern total; else sum legs
        total_m = pattern.get("distance_m") or sum(leg_dist_m(l) for l in legs)
        # Time: prefer pattern duration; else sum legs
        total_sec = pattern.get("duration_sec") or sum(leg_dur_sec(l) for l in legs)

        if total_m <= 0 or total_sec <= 0:
            return None

        # Access time = duration of the FIRST foot leg only (origin -> first stop).
        # If the first leg is not a walking leg, access = 0 and the whole trip is
        # travel_time. Transfer walks (foot legs that are not leg[0]) and the
        # final egress walk are intentionally NOT counted as access; they are
        # part of travel_time because they happen inter-vehicle or post-egress.
        access_sec = 0.0
        if legs and classify_leg(legs[0]) == "walk":
            access_sec = leg_dur_sec(legs[0])

        travel_sec = max(total_sec - access_sec, 0.0)

        fb = compute_trip_fare(legs, metra_stations)
        seq = "|".join(classify_leg(l) for l in legs) if legs else ""

        # Prefer the precomputed miles when present (avoids rounding drift)
        miles = pattern.get("distance_miles")
        if miles is None:
            miles = total_m / METERS_PER_MILE

        return TripSummary(
            distance_miles=float(miles),
            access_time_mins=access_sec / 60.0,
            travel_time_mins=travel_sec / 60.0,
            fare=fb.total_fare,
            boardings=fb.boardings,
            transfers_used=fb.transfers_used,
            fare_detail="; ".join(fb.detail),
            fare_estimated=False,
            leg_sequence=seq,
        )

    # Fallback to CSV-only (no leg detail, so we cannot split access from travel)
    if csv_distance_miles and csv_time_mins and csv_distance_miles > 0 and csv_time_mins > 0:
        return TripSummary(
            distance_miles=float(csv_distance_miles),
            access_time_mins=float(ACCESS_TIME_MINS_FALLBACK),
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

def _build_row(o, d, ts: Optional[TripSummary],
               zone_classifications: Dict[float, str],
               vot_levels: Dict[str, float]) -> Dict[str, object]:
    """Build a single CSV row (all fields already resolved to scalars)."""
    dest_cls = zone_classifications.get(d, "Unknown")
    row: Dict[str, object] = {
        "origin_taz": o,
        "destination_taz": d,
        "dest_classification": dest_cls,
    }
    if ts is None:
        row.update({
            "is_valid": False,
            "invalid_reason": "no usable trip data",
            "travel_distance_miles": "",
            "access_time_mins": "",
            "travel_time_mins": "",
            "modal_speed_mph": "",
            "fare": "",
            "boardings": 0,
            "transfers_used": 0,
            "fare_detail": "",
            "fare_estimated": False,
            "leg_sequence": "",
        })
        for vot_name in vot_levels:
            row[f"generalized_time_hours_{vot_name}"] = ""
            row[f"generalized_speed_mph_{vot_name}"] = ""
        return row

    dist   = ts.distance_miles
    acc_h  = ts.access_time_mins / 60.0
    trav_h = ts.travel_time_mins / 60.0
    modal_speed = (dist / trav_h) if trav_h > 0 else None

    row.update({
        "is_valid": True,
        "invalid_reason": "",
        "travel_distance_miles": dist,
        "access_time_mins": ts.access_time_mins,
        "travel_time_mins": ts.travel_time_mins,
        "modal_speed_mph": modal_speed if modal_speed is not None else "",
        "fare": ts.fare,
        "boardings": ts.boardings,
        "transfers_used": ts.transfers_used,
        "fare_detail": ts.fare_detail,
        "fare_estimated": ts.fare_estimated,
        "leg_sequence": ts.leg_sequence,
    })
    for vot_name, vot in vot_levels.items():
        gt = acc_h + trav_h + (ts.fare / vot) + (VARIABLE_COST_PER_MILE * dist / vot)
        denom = vot * (acc_h + trav_h) + ts.fare + VARIABLE_COST_PER_MILE * dist
        gs = (dist * vot) / denom if denom > 0 else None
        row[f"generalized_time_hours_{vot_name}"] = gt
        row[f"generalized_speed_mph_{vot_name}"]  = gs if gs is not None else ""
    return row


def _output_columns(vot_levels: Dict[str, float]) -> Tuple[List[str], List[str]]:
    """(full_columns, clean_columns)"""
    full = [
        "origin_taz", "destination_taz", "dest_classification",
        "is_valid", "invalid_reason",
        "travel_distance_miles",
        "access_time_mins", "travel_time_mins", "modal_speed_mph",
        "fare", "boardings", "transfers_used",
        "fare_detail", "fare_estimated", "leg_sequence",
    ]
    for v in vot_levels:
        full += [f"generalized_time_hours_{v}", f"generalized_speed_mph_{v}"]

    clean = [
        "origin_taz", "destination_taz", "dest_classification",
        "travel_distance_miles",
        "access_time_mins", "travel_time_mins", "modal_speed_mph",
        "fare", "boardings", "transfers_used", "fare_estimated",
        "leg_sequence",
    ]
    for v in vot_levels:
        clean += [f"generalized_time_hours_{v}", f"generalized_speed_mph_{v}"]
    return full, clean


@dataclass
class Stats:
    total: int = 0
    valid: int = 0
    invalid: int = 0
    fare_estimated: int = 0
    fare_sum: float = 0.0
    fares: List[float] = field(default_factory=list)  # for median (reservoir-ish)
    boardings_sum: int = 0
    transfers_sum: int = 0
    fare_max: float = 0.0
    access_sum: float = 0.0
    travel_sum: float = 0.0
    modal_speed_sum: float = 0.0
    gt_sum: Dict[str, float] = field(default_factory=dict)
    gs_sum: Dict[str, float] = field(default_factory=dict)

    def update(self, row: Dict[str, object], vot_levels: Dict[str, float]):
        self.total += 1
        if row["is_valid"]:
            self.valid += 1
            if row["fare_estimated"]:
                self.fare_estimated += 1
            f = float(row["fare"])
            self.fare_sum += f
            self.fares.append(f)
            self.fare_max = max(self.fare_max, f)
            self.boardings_sum += int(row["boardings"])
            self.transfers_sum += int(row["transfers_used"])
            self.access_sum += float(row["access_time_mins"])
            self.travel_sum += float(row["travel_time_mins"])
            if row["modal_speed_mph"] != "":
                self.modal_speed_sum += float(row["modal_speed_mph"])
            for v in vot_levels:
                self.gt_sum[v] = self.gt_sum.get(v, 0.0) + float(
                    row[f"generalized_time_hours_{v}"])
                gs = row[f"generalized_speed_mph_{v}"]
                if gs != "":
                    self.gs_sum[v] = self.gs_sum.get(v, 0.0) + float(gs)
        else:
            self.invalid += 1


class StreamingWriter:
    """Append-mode CSV writer with a row buffer to keep disk I/O cheap."""

    def __init__(self, path: Path, columns: List[str],
                 buffer_size: int = 5000, resume: bool = False):
        self.path = path
        self.columns = columns
        self.buffer_size = buffer_size
        self.buffer: List[Dict[str, object]] = []
        # On resume the file already exists and has a header — don't rewrite it.
        self._header_written = resume and path.exists()
        if not resume and path.exists():
            path.unlink()  # fresh start

    def write(self, row: Dict[str, object]):
        self.buffer.append(row)
        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        mode = "a" if self._header_written else "w"
        with open(self.path, mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.columns,
                                    extrasaction="ignore")
            if not self._header_written:
                writer.writeheader()
                self._header_written = True
            writer.writerows(self.buffer)
        self.buffer.clear()

    def close(self):
        self.flush()


def _rebuild_seen_from_output(full_path: Path) -> set:
    """
    Read only the (origin_taz, destination_taz) columns from an existing
    full-output CSV to rebuild the seen set for a resume run.
    Chunked so the read stays memory-bounded regardless of file size.
    """
    seen: set = set()
    if not full_path.exists():
        return seen
    print(f"  Rebuilding seen set from existing output: {full_path}")
    rows_read = 0
    for chunk in pd.read_csv(full_path,
                             usecols=["origin_taz", "destination_taz"],
                             chunksize=200_000):
        for o, d in zip(chunk["origin_taz"], chunk["destination_taz"]):
            seen.add((o, d))
        rows_read += len(chunk)
    print(f"  Loaded {rows_read:,} already-processed pairs — will skip these")
    return seen


def process_streaming(json_dirs: Iterable[str],
                      csv_fallback_path: Optional[str],
                      metra_stations: List[MetraStation],
                      zone_classifications: Dict[float, str],
                      vot_levels: Dict[str, float],
                      output_dir: str,
                      resume: bool = False) -> Stats:
    """
    Stream JSON files one at a time, compute per-pair metrics, and append to
    disk. Avoids holding the full ~8.5M-pair dataset in memory.

    Dedup policy: first sighting of an (origin, dest) wins. Since we walk
    `json_dirs` in the order given, pass higher-priority dirs first to match
    combine_json_to_csv.py precedence.

    If resume=True, the existing output files are kept and the seen set is
    pre-populated from the full-output CSV so already-processed pairs are
    skipped efficiently.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    full_cols, clean_cols = _output_columns(vot_levels)
    full_path    = out / "transit_generalized_metrics_full.csv"
    clean_path   = out / "transit_generalized_metrics_clean.csv"
    invalid_path = out / "transit_invalid_pairs.csv"

    # On resume, pre-populate seen from the existing full output before opening
    # any writers (so we don't accidentally wipe the file before reading it).
    seen: set = _rebuild_seen_from_output(full_path) if resume else set()

    w_full  = StreamingWriter(full_path,    full_cols,  resume=resume)
    w_clean = StreamingWriter(clean_path,   clean_cols, resume=resume)
    w_inv   = StreamingWriter(invalid_path, full_cols,  resume=resume)

    stats = Stats()

    # --- Phase 1: JSON files, one at a time -----------------------------------
    files_seen = 0
    t0 = time.time()
    last_report = t0

    for jpath in _iter_json_files(json_dirs):
        files_seen += 1
        try:
            with open(jpath, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [warn] could not read {jpath.name}: {e}")
            continue

        for rec in _iter_records(payload):
            o, d = _record_od(rec)
            if o is None or d is None:
                continue
            key = (o, d)
            if key in seen:
                continue

            # Only mark as seen (and write) when OTP returned a usable trip.
            # Records with success=False, trip_patterns=[], or wrong mode are
            # skipped here so the CSV fallback can still fill them in.
            pattern = _extract_pattern(rec)
            if pattern is None:
                continue

            seen.add(key)
            ts = summarize_trip(pattern, metra_stations, None, None)
            row = _build_row(o, d, ts, zone_classifications, vot_levels)
            stats.update(row, vot_levels)
            w_full.write(row)
            if row["is_valid"]:
                w_clean.write(row)
            else:
                w_inv.write(row)

        # Release the payload immediately; don't keep leg data around.
        del payload

        now = time.time()
        if now - last_report > 5.0 or files_seen % 50 == 0:
            elapsed = now - t0
            rate = stats.total / elapsed if elapsed > 0 else 0
            print(f"  [{files_seen:>5} files | {stats.total:>9,} pairs | "
                  f"{rate:>6.0f} pairs/s | {elapsed:>6.1f}s]")
            last_report = now

    print(f"  Scanned {files_seen} JSON file(s); produced {stats.total:,} OD pairs")

    # --- Phase 2: CSV fallback for any OD pair not seen in JSON ---------------
    if csv_fallback_path and os.path.exists(csv_fallback_path):
        print(f"\nScanning CSV fallback: {csv_fallback_path}")
        # Read in chunks — don't load the full 8.5M-row CSV at once.
        reader = pd.read_csv(csv_fallback_path, chunksize=200_000)
        added = 0
        for chunk in reader:
            col_o = "origin_taz"
            col_d = ("destination_taz" if "destination_taz" in chunk.columns
                     else "dest_taz")
            col_dist = ("travel_distance_miles"
                        if "travel_distance_miles" in chunk.columns
                        else "distance_miles")
            col_time = ("travel_time_mins" if "travel_time_mins" in chunk.columns
                        else "travel_time_min")
            for _, r in chunk.iterrows():
                o, d = r[col_o], r[col_d]
                key = (o, d)
                if key in seen:
                    continue
                seen.add(key)
                ts = summarize_trip(None, metra_stations,
                                    r.get(col_dist), r.get(col_time))
                row = _build_row(o, d, ts, zone_classifications, vot_levels)
                stats.update(row, vot_levels)
                w_full.write(row)
                if row["is_valid"]:
                    w_clean.write(row)
                else:
                    w_inv.write(row)
                added += 1
        print(f"  CSV fallback added {added:,} pairs not seen in JSON")

    w_full.close(); w_clean.close(); w_inv.close()

    print(f"\nFull results       -> {full_path}")
    print(f"Clean results      -> {clean_path}")
    print(f"Invalid pairs      -> {invalid_path}")
    return stats


def print_stats(stats: Stats, vot_levels: Dict[str, float]):
    print("\n" + "=" * 80)
    print("TRANSIT SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total OD pairs:        {stats.total:,}")
    print(f"Valid:                 {stats.valid:,}")
    print(f"Invalid:               {stats.invalid:,}")
    if stats.valid == 0:
        return
    median_fare = float(np.median(stats.fares)) if stats.fares else float("nan")
    print(f"Fare-estimated pairs:  {stats.fare_estimated:,}")
    print(f"Mean boardings/trip:   {stats.boardings_sum / stats.valid:.2f}")
    print(f"Mean transfers/trip:   {stats.transfers_sum / stats.valid:.2f}")
    print(f"Mean fare:             ${stats.fare_sum / stats.valid:.2f}")
    print(f"Median fare:           ${median_fare:.2f}")
    print(f"Max fare:              ${stats.fare_max:.2f}")
    print(f"Mean access time:      {stats.access_sum / stats.valid:.1f} min")
    print(f"Mean travel time:      {stats.travel_sum / stats.valid:.1f} min")
    print(f"Mean modal speed:      {stats.modal_speed_sum / stats.valid:.2f} mph")
    for vot_name, vot in vot_levels.items():
        gt_mean = stats.gt_sum.get(vot_name, 0.0) / stats.valid
        gs_mean = stats.gs_sum.get(vot_name, 0.0) / stats.valid
        print(f"\nVoT {vot_name} (${vot}/hr):")
        print(f"  gen speed mean: {gs_mean:.2f} mph   "
              f"gen time mean:  {gt_mean*60:.1f} min")


def main():
    ap = argparse.ArgumentParser(
        description="Transit bidimensional generalized speed/time calculator")
    ap.add_argument("--taz-file",       default=DEFAULT_TAZ_FILE,
                    help="TAZ reference file (csv or xlsx) with columns "
                         "zone17, chicago, cbd, Lat, Lon. Supplies both the "
                         "destination-zone classification and the centroids "
                         "used for Metra station coordinate lookup.")
    ap.add_argument("--metra-stations", default=DEFAULT_METRA_STATIONS,
                    help="metrastations_taz.xls (STATION_ID, FAREZONE, zone17, ...)")
    ap.add_argument("--transit-csv",    default=None,
                    help="Aggregate transit CSV (origin_taz, destination_taz, "
                         "travel_distance_miles, travel_time_mins). If omitted "
                         "the script searches common locations automatically.")
    ap.add_argument("--json-dir", action="append", default=None,
                    help="Directory of OTP JSON files. Repeat to add multiple "
                         "(earlier dirs take priority on duplicates).")
    ap.add_argument("--output-dir",     default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--resume", action="store_true",
                    help="Continue a previous run that crashed or was interrupted. "
                         "Reads already-processed (origin, dest) pairs from the "
                         "existing full-output CSV and skips them. Output files "
                         "are opened in append mode.")
    args = ap.parse_args()

    json_dirs = args.json_dir or DEFAULT_JSON_DIRS

    # Resolve CSV fallback path: explicit arg wins, else auto-detect
    transit_csv_path: Optional[str] = args.transit_csv
    if transit_csv_path is None:
        for candidate in DEFAULT_TRANSIT_CSV_CANDIDATES:
            if os.path.exists(candidate):
                transit_csv_path = candidate
                break
    if transit_csv_path and os.path.exists(transit_csv_path):
        print(f"[info] Transit CSV fallback: {transit_csv_path}")
    else:
        print("[WARN] No transit CSV fallback found. Pairs with empty/failed "
              "JSON entries will be marked invalid instead of using CSV data.")
        print("       Pass --transit-csv <path/to/travel_time_transit.csv> to "
              "enable the fallback and recover those ~4M extra pairs.")
        transit_csv_path = None

    print("=" * 80)
    print("TRANSIT MODE GENERALIZED METRICS CALCULATOR")
    print("Bidimensional Transportation Model (Khisty & Sriraj)")
    print("=" * 80)
    print(f"\n--- Parameters ---")
    print(f"Access time:        per-trip (first foot leg duration; fallback "
          f"{ACCESS_TIME_MINS_FALLBACK} min for CSV-only rows)")
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
    metra_stations = load_metra_stations(args.metra_stations, args.taz_file)

    if args.resume:
        print("\n--- RESUME MODE: continuing previous run ---")
    print("\n--- Streaming OTP JSON -> CSV ---")
    stats = process_streaming(
        json_dirs=json_dirs,
        csv_fallback_path=transit_csv_path,
        metra_stations=metra_stations,
        zone_classifications=zone_class,
        vot_levels=VOT_LEVELS,
        output_dir=args.output_dir,
        resume=args.resume,
    )

    print_stats(stats, VOT_LEVELS)

    print("\n" + "=" * 80)
    print("Processing complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
