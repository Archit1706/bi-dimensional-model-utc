# Lessons Learned & Hard-Won Debugging Knowledge

**Read this before debugging any OTP or collection script issue.**

---

## 🔴 Critical: The Lat/Lon Swap Bug

**What happened**: In the original collection run, `create_variables()` passed
longitude where OTP expected latitude, and vice versa. This caused all transit routing
to fail completely (0% success for transit/bus/rail) while car/bike/walk returned
partial results because those modes are more tolerant of imprecise coordinates.

**Why car/bike/walk survived**: Direct-mode routing (no transit stops) uses road network
snapping, which is forgiving of nearby coordinates. Transit requires locating actual
stops, which fails completely when coordinates are ocean/arctic.

**The fix**:
```python
# WRONG:
"origin": {"longitude": taz_lat, "latitude": taz_lon}

# CORRECT:
"origin": {"latitude": taz_lat, "longitude": taz_lon}
```

**How to validate**: When you first run any transit query, check a known CBD-to-CBD pair
(e.g., TAZ 1 → TAZ 50). If success rate is 0%, check coordinate order immediately.

---

## 🔴 Critical: ISO 8601 Duration Strings

**What happened**: `searchWindow` and `maxAccessEgressDurationForMode` were passed as
integer seconds. OTP's Transmodel GraphQL API rejected these with a validation error.

**The fix**:
```python
# WRONG:
"searchWindow": 7200,
"maxAccessEgressDurationForMode": {"WALK": 900}

# CORRECT:
"searchWindow": "PT2H",
"maxAccessEgressDurationForMode": {"WALK": "PT15M"}
```

ISO 8601 duration format: `PT{hours}H{minutes}M{seconds}S`
- 15 minutes → `"PT15M"`
- 2 hours → `"PT2H"`
- 1 hour 30 minutes → `"PT1H30M"`

---

## 🔴 Critical: OTP Memory vs. WSL2 Ceiling

**What happened**: Docker was given a 16 GB Java heap (`-Xmx16g`), but WSL2 only
provided ~15.46 GB total memory to Docker (default 50% of 32 GB = 16 GB minus overhead).
OTP ran at 94% heap usage, causing constant GC thrashing, reducing throughput from
~10 pairs/sec to ~1-2 pairs/sec.

**Diagnosis**: Run `docker stats` and watch the MEM USAGE / LIMIT column.
- >90% = emergency, stop and reconfigure
- 60-80% = healthy

**Fix sequence**:
1. Edit `C:\Users\<you>\.wslconfig` → set `memory=24GB`
2. Run `wsl --shutdown` in PowerShell
3. Restart Docker Desktop
4. Restart OTP container with `-Xmx20g`

**Rule of thumb**: Java heap = WSL2 memory − 3 GB (leave room for OS + Python script).

---

## 🟡 OTP 2.9.0-SNAPSHOT Serialization Bug

**What happened**: After building the OTP graph (`--build`) and saving it, loading the
saved graph (`--load`) threw `NullPointerException` in `Vertex.addEdge()`. The vertex
reference `existing` was null during graph reconstruction.

**Root cause**: Known serialization bug in the SNAPSHOT release.

**Fix**: Use stable release `opentripplanner/opentripplanner:2.5.0` with `--build --serve`
(builds and serves in one command, never saves/loads the graph file).

**Trade-off**: Must rebuild on every container restart (~5 minutes). Acceptable for this
project since OTP restarts are infrequent.

---

## 🟡 File I/O Bottleneck at Scale

**What happened**: Writing the entire JSON file on every batch of 55 OD pairs caused
severe I/O degradation as files grew to thousands of entries.

**Fix**: Flush every 10 batches using atomic writes:
```python
import os, json, tempfile

def flush_to_disk(filepath, data):
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, filepath)  # atomic on same filesystem
```

**Why atomic**: If the script crashes mid-write, `.replace()` ensures you never get a
half-written JSON file. The old file stays intact until the new one is fully written.

---

## 🟡 Resume Logic Must Pre-Filter

**What happened**: Checking "is this pair already done?" per-batch inside the main loop
caused O(n²) lookups as the dataset grew. Restart overhead at 5M+ pairs was minutes.

**Fix**: Pre-build a set of completed (origin, dest) pairs **before** entering the loop:
```python
# Load all done pairs upfront
done_pairs = set()
for filepath in glob(output_dir + "/*.json"):
    with open(filepath) as f:
        for record in json.load(f):
            done_pairs.add((record["origin_taz"], record["dest_taz"]))

# Filter the work queue
all_pairs = [(o, d) for o, d in product(taz_ids, taz_ids)
             if (o, d) not in done_pairs]
```

---

## 🟡 Windows cp1252 Encoding Error

**What happened**: Writing Unicode box-drawing characters (─, │, ╔, etc.) to a `.txt`
report file on Windows failed because the default file encoding is `cp1252`, which can't
represent those characters.

**Fix**: Always open output files with explicit UTF-8:
```python
with open("report.txt", "w", encoding="utf-8") as f:
    f.write(report_text)
```

Apply this to every file write in every script — not just reports.

---

## 🟡 Filename Sorting with Non-Standard Names

**What happened**: `combine_json_to_csv.py` sorted JSON files by extracting the numeric
suffix from filenames like `taz_travel_times_otp1234.json`. When files with non-standard
names existed in the directory, `int()` on an empty string raised `ValueError`.

**Fix**: Safe extraction with a fallback:
```python
import re

def extract_file_num(filepath):
    match = re.search(r'(\d+)(?=\.json$)', filepath)
    if not match:
        logger.warning(f"Unexpected filename format: {filepath}")
        return 0
    return int(match.group(1))

files = sorted(glob(pattern), key=extract_file_num)
```

---

## ℹ️ "Partially Isolated" Zone Definition

A zone is **partially isolated** if it is a dead origin OR a dead destination, but not
both. This is different from **fully isolated** (dead in both directions).

Dead origin = zone appears as `origin_taz` in zero rows of the travel time CSV.
Dead destination = zone appears as `dest_taz` in zero rows.

Most partially isolated zones are suburban fringe zones where OSM network connectivity
is incomplete at the region boundary — not true geographic isolation.

---

## ℹ️ The ~38,000 "Suburban Fringe" Residual

After accounting for dead origins, dead destinations, and their overlap, ~38,000 missing
car pairs remain. These are NOT explained by isolated zones. They represent OD pairs where:
- Both origin and destination zones are valid (have some routes)
- But OTP could not find a connected path between them via the OSM road network
- Concentrated at the edges of the 7-county region where OSM coverage thins out

These are a known data quality limitation. The 0.76% missing rate is acceptable for
regional-scale analysis; individual-pair lookups in these fringe areas should be
treated with caution.

---

## ℹ️ Two-Machine Parallelization Strategy

To halve wall-clock collection time:
- **Machine A**: runs collection forward (TAZ 1 → 2926 as origin)
- **Machine B**: runs collection in reverse (TAZ 2926 → 1 as origin)

Both write to the same output directory (shared network drive or sync tool).
The pre-filter resume logic handles deduplication automatically.

Each machine needs its own OTP instance (Docker container on each machine).
