# OTP Setup & Docker Configuration

## Overview

OpenTripPlanner (OTP) 2.x is run locally via Docker on Windows with WSL2 backend.
It serves the GraphQL Transmodel API for all routing queries.

---

## WSL2 Memory Configuration (Required First Step)

WSL2 by default caps memory at 50% of system RAM or 8 GB (whichever is smaller).
This will starve OTP of the heap it needs. **Before anything else**, configure WSL2:

Create `C:\Users\<YourUsername>\.wslconfig`:
```ini
[wsl2]
memory=24GB
processors=8
swap=8GB
```

Then restart WSL2:
```powershell
wsl --shutdown
# Wait ~10 seconds, then reopen your terminal
```

---

## Docker Command to Start OTP

Run this in **Windows PowerShell** (not WSL terminal):

```powershell
docker run --rm `
  -e JAVA_OPTS="-Xmx20g" `
  -v "C:\path\to\your\otp-data:/var/opentripplanner" `
  -p 8080:8080 `
  opentripplanner/opentripplanner:2.5.0 `
  --build --serve
```

**Key flags:**
- `-Xmx20g` — Java heap. Must be less than the WSL2 memory ceiling (24 GB above).
  Use 20 GB if WSL2 is set to 24 GB; use 12 GB if WSL2 is at 16 GB.
- `--build --serve` — builds the graph from source files and serves immediately.
  **Do not separate `--build` and `--serve` into two commands** — the stable release
  has serialization issues when saving/loading the graph file between runs.
- Port `8080` maps to OTP's default HTTP port.

### OTP data directory must contain:
- `*.osm.pbf` — OSM road network (Illinois extract clipped to Chicagoland bounding box)
- `*.gtfs.zip` (or `*.zip`) files for each agency:
  - CTA bus + rail GTFS
  - Metra GTFS
  - Pace GTFS
- `build-config.json` (optional tuning)
- `router-config.json` (optional tuning)

---

## Extracting the OSM File for Chicagoland

Use `osmium-tool` to clip the Illinois `.pbf` down to a Chicagoland bounding box:

```bash
osmium extract \
  --bbox=-88.5,41.4,-87.0,42.5 \
  illinois-latest.osm.pbf \
  -o chicagoland.osm.pbf
```

Approximate bounding box for the 7-county region:
- West: -88.5
- South: 41.4
- East: -87.0
- North: 42.5

---

## OTP Version Notes

| Version | Status | Notes |
|---------|--------|-------|
| 2.9.0-SNAPSHOT | ❌ Do not use | NullPointerException on graph load (Vertex.addEdge serialization bug) |
| 2.5.0 | ✅ Recommended | Stable; use `--build --serve` to avoid save/load cycle |

The graph build from IL OSM + 3 GTFS feeds takes ~5 minutes and produces a graph
with ~3M vertices and ~8M edges (~706 MB on disk).

---

## Verifying OTP is Ready

After starting the container, OTP is ready when you see in the logs:
```
Grizzly server running.
```

Or check: `http://localhost:8080/otp/transmodel/v3` should return a GraphQL playground.

Quick health check in Python:
```python
import requests
r = requests.get("http://localhost:8080/otp")
print(r.status_code)  # 200 = ready
```

---

## Memory Monitoring

Watch Docker stats while running collection scripts:
```powershell
docker stats
```

**Warning signs:**
- Memory usage > 90% of allocated heap → GC thrashing, severe slowdown
- The collection script will slow from ~10 pairs/sec to ~1-2 pairs/sec
- Fix: stop container, increase WSL2 `.wslconfig` memory, restart

**Healthy operating range**: 60–80% of allocated Java heap.

---

## Concurrency Settings

These are configured in `taz_otp_matrix_json.py`:
```python
SEMAPHORE_LIMIT = 18    # concurrent OTP requests
BATCH_SIZE = 55         # OD pairs per batch
```

With 20 GB heap and proper WSL2 config, you can push to:
```python
SEMAPHORE_LIMIT = 40
BATCH_SIZE = 100
```

Do not exceed these without monitoring memory — OTP will crash.

---

## Startup Automation

A PowerShell convenience script (`start_otp.ps1`) can automate the startup:
```powershell
# Check Docker is running
if (-not (docker info 2>$null)) {
    Write-Host "Starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Start-Sleep -Seconds 30
}

# Start OTP container
docker run --rm `
  -e JAVA_OPTS="-Xmx20g" `
  -v "C:\path\to\otp-data:/var/opentripplanner" `
  -p 8080:8080 `
  opentripplanner/opentripplanner:2.5.0 `
  --build --serve

Write-Host "OTP is ready at http://localhost:8080"
```
