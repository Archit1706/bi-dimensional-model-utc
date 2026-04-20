# Scripts Built — Reference & Status

All analysis scripts are in `scripts/`. They were developed iteratively in Claude.ai chat
and follow a consistent structure. This file documents what was built, key logic decisions,
and what remains to be done.

---

## Script 1: `calc_walk_generalized.py`

**Status:** Complete  
**Input:** `data/walk_data.csv`  
**Outputs:** `outputs/walk_generalized_{full|clean|invalid}.csv`

### Parameters
```python
access_time       = 0       # hours
fixed_cost        = 0       # $
variable_cost     = 0       # $/mile
vot_levels        = {'low': 14.64, 'mid': 30.62, 'high': 80.84}
```

### Key insight
With all costs zero, the generalized formulas simplify:
```
generalized_time  = travel_time_hours               (VoT cancels out)
generalized_speed = travel_distance_miles / travel_time_hours  (== physical speed)
```
All three VoT columns will be **identical** for walking. This is expected and correct.

### Logic flow
1. Read CSV, validate rows (distance > 0, time > 0, no NaN)
2. Convert travel_time_mins → travel_time_hours (÷ 60)
3. Compute generalized speed/time (same for all VoT levels)
4. Write three output CSVs
5. Print summary stats: count valid/invalid, speed distribution, avg speed

---

## Script 2: `calc_bike_generalized.py`

**Status:** Complete  
**Input:** `data/bike_data.csv`  
**Outputs:** `outputs/bike_generalized_{full|clean|invalid}.csv`

### Parameters
```python
access_time       = 8 / 60  # 8 minutes → 0.1333 hours
fixed_cost        = 0       # $
variable_cost     = 0.05    # $/mile
vot_levels        = {'low': 14.64, 'mid': 30.62, 'high': 80.84}
```

### Key insight
Unlike walking, bicycle generalized speed DOES vary by VoT because of the
variable cost term. Higher VoT travelers are more penalized by cost (in
time-equivalent terms), but the effect is relatively small given the low
$0.05/mile rate.

### Logic flow
Same as walk script, but:
- Uses non-zero access_time and variable_cost
- Computes three distinct columns per VoT level
- Validates against expected bicycle speed range

---

## Script 3: `calc_car_generalized.py`

**Status:** Complete  
**Input:** `data/car_data.csv`, `data/taz.xlsx`  
**Outputs:** `outputs/car_generalized_{full|clean|invalid}.csv`

### Parameters
```python
access_time       = 10 / 60  # 10 minutes → 0.1667 hours
variable_cost     = 0.92     # $/mile
vot_levels        = {'low': 14.64, 'mid': 30.62, 'high': 80.84}

# Fixed cost by DESTINATION zone type:
fixed_costs = {
    'CBD':          37.28,   # downtown parking
    'city_non_cbd': 20.00,   # off-downtown parking
    'suburb':        0.00,   # free parking
}
```

### Key insight
The **destination-dependent fixed cost** is the defining feature of the car script.
CBD destinations show dramatically lower generalized speeds vs. suburbs, accurately
reflecting real Chicago parking economics. This requires joining TAZ classification
data before computing any metrics.

### Logic flow
1. Load and index `taz.xlsx` by TAZ ID
2. Read and validate `car_data.csv`
3. For each valid row, look up destination TAZ → zone_type → fixed_cost
4. Compute generalized metrics per VoT level using zone-specific fixed cost
5. Write three output CSVs
6. Print summary stats broken down by zone type

---

## Script 4: `calc_transit_generalized.py`

**Status:** NOT YET BUILT  
**Notes from prior analysis:**

Transit involves more complexity than other modes. The OTP transit data includes
multiple leg types:
- **First-mile walk** — walk from origin to first stop
- **In-vehicle time** — time on bus/train
- **Transfer walks** — walks between stops/stations
- **Last-mile walk** — walk from final stop to destination

A dashboard was built (HTML/Chart.js) analyzing transit walking burden metrics:
- First vs. last mile distributions (by percentile)
- Walking legs per trip
- Walk time share distribution
- Transfer leg counts
- Longest walk leg position (first vs. last vs. transfer)
- Component breakdown by walk type

The transit Mode parameters have not been finalized for generalized speed calculation.
Decide whether to treat transit as a single composite mode or model in/out-vehicle
components separately.

---

## Visualization: Car Mode Dashboard

**Format:** Single-file HTML with Chart.js  
**Color scheme:** Gold/amber (`#C9A227`, `#E8C547`, `#A07C1E`) — PowerPoint-ready  
**Charts included:**
1. Grouped bar — generalized speed by zone type × VoT level
2. Grouped bar — generalized time by zone type × VoT level
3. Distribution chart with standard deviation bands
4. Physical trip characteristics comparison

**Key requirements met:**
- Large fonts for screenshot legibility in PowerPoint slides
- Permanent data labels using `chartjs-plugin-datalabels` (values always visible, not hover-only)
- CDN: `https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-datalabels/2.0.0/chartjs-plugin-datalabels.min.js`

---

## Visualization: Transit Walking Burden Dashboard

**Format:** Single-file HTML with Chart.js  
**Same color scheme and font/label requirements as car dashboard**  
**Charts included:**
1. First vs. last mile percentile breakdowns
2. Walking legs per trip (bar)
3. Walk time share distribution
4. Transfer leg counts
5. Donut — longest walk leg position (first / last / transfer)
6. Horizontal stacked percentile bands
7. Stacked component breakdown by walk type

---

## Shared Script Template (pseudocode)

All mode scripts follow this structure:

```python
import pandas as pd
import numpy as np

# ── Parameters ──────────────────────────────────────────────────
ACCESS_TIME   = ...   # hours
FIXED_COST    = ...   # $ (or dict by zone type for car)
VARIABLE_COST = ...   # $/mile
VOT_LEVELS    = {'low': 14.64, 'mid': 30.62, 'high': 80.84}

# ── Formulas ─────────────────────────────────────────────────────
def transport_time(distance, access_time, speed):
    return access_time + (distance / speed)

def transport_cost(distance, fixed_cost, variable_cost):
    return fixed_cost + (variable_cost * distance)

def generalized_time(t_time, t_cost, vot):
    return t_time + (t_cost / vot)

def generalized_speed(distance, gen_time):
    return distance / gen_time

# ── Main ─────────────────────────────────────────────────────────
df = pd.read_csv('data/{mode}_data.csv')

# Validate
df['invalid'] = False
df['reason'] = ''
mask_bad = (df['travel_distance_miles'] <= 0) | (df['travel_time_mins'] <= 0) | df['travel_distance_miles'].isna()
df.loc[mask_bad, 'invalid'] = True
df.loc[mask_bad, 'reason'] = 'zero or missing distance/time'

# Convert time units
df['travel_time_hours'] = df['travel_time_mins'] / 60

valid = df[~df['invalid']].copy()

# Compute per VoT level
for label, vot in VOT_LEVELS.items():
    # ... apply formulas ...
    valid[f'gen_speed_{label}'] = ...
    valid[f'gen_time_{label}'] = ...

# Write outputs
df.to_csv('outputs/{mode}_generalized_full.csv', index=False)
valid.to_csv('outputs/{mode}_generalized_clean.csv', index=False)
df[df['invalid']].to_csv('outputs/{mode}_generalized_invalid.csv', index=False)

# Print summary stats
print(f"Valid: {len(valid)} / Total: {len(df)}")
print(valid[[f'gen_speed_{l}' for l in VOT_LEVELS]].describe())
```
