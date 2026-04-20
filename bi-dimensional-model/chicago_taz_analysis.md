# Chicago TAZ Analysis — Parameters & Zone Classification

## Study Area

Chicago 7-county metropolitan area, Illinois.
Zones are defined by the regional TAZ system. TAZ metadata lives in `taz.xlsx`.

---

## TAZ Zone Classification

Zone type is determined by two boolean columns in `taz.xlsx`:

| `chicago` | `cbd` | Zone Type       | Description                          |
|-----------|-------|-----------------|--------------------------------------|
| 1         | 1     | **CBD**         | Within Chicago city limits AND downtown |
| 1         | 0     | **City non-CBD**| Within Chicago city limits, not downtown |
| 0         | 0     | **Suburb**      | Outside Chicago city limits          |

> Note: `chicago=0, cbd=1` is theoretically impossible and should not appear.

Zone type is applied to the **destination TAZ** for all generalized cost calculations,
because fixed costs (e.g., parking) are incurred at the destination.

---

## Value of Time (VoT) Levels

Three income brackets, each producing a separate set of output columns:

| Label | VoT (H) | Rationale                    |
|-------|---------|------------------------------|
| Low   | $14.64/hr | Lower income bracket       |
| Mid   | $30.62/hr | Middle income bracket      |
| High  | $80.84/hr | Higher income bracket      |

VoT is treated as 70% of average wage rate per income bracket (Khisty & Sriraj).

---

## Mode Parameters — Chicago Application

All scripts use **miles** and **hours** as units.

### Walking Mode
| Parameter        | Value |
|------------------|-------|
| Access time (Tom)| 0 hr  |
| Modal speed (Vm) | (from OTP data — varies by TAZ pair) |
| Fixed cost (Com) | $0    |
| Var. cost (γm)   | $0/mile |

Because all costs are zero, generalized metrics simplify to physical speed/time.
VoT has no effect on walking outputs.

```
generalized_speed_walk = travel_distance_miles / travel_time_hours
generalized_time_walk  = travel_time_hours
```

### Bicycle Mode
| Parameter        | Value      |
|------------------|------------|
| Access time (Tom)| 8 min = 0.1333 hr |
| Modal speed (Vm) | (from OTP data)   |
| Fixed cost (Com) | $0                |
| Var. cost (γm)   | $0.05/mile        |

Bicycle generalized metrics DO vary with VoT due to the variable cost term.

### Car Mode
Car is the most complex because **fixed cost varies by destination zone type**:

| Destination Zone | Fixed Cost (Com) | Rationale              |
|------------------|-----------------|------------------------|
| CBD              | $37.28          | Downtown parking costs |
| City non-CBD     | $20.00          | Off-downtown parking   |
| Suburb           | $0.00           | Free/included parking  |

Other car parameters:
| Parameter        | Value            |
|------------------|-----------------|
| Access time (Tom)| 10 min = 0.1667 hr |
| Modal speed (Vm) | (from OTP data)    |
| Var. cost (γm)   | $0.92/mile         |

The high CBD fixed cost causes CBD generalized speeds to be significantly lower
than suburban destinations — consistent with real-world urban travel behavior.

### Transit Mode (parameters TBD)
Transit analysis includes first-mile walk, last-mile walk, transfer walks,
and in-vehicle time. Walking burden metrics were computed separately.
The transit generalized speed script has not yet been finalized.

---

## Data Loading Pattern

All scripts follow this pattern for zone classification:

```python
import pandas as pd

# Load TAZ classification
taz_df = pd.read_excel('taz.xlsx')

def get_zone_type(taz_id, taz_df):
    row = taz_df[taz_df['taz_id'] == taz_id]
    if row.empty:
        return 'unknown'
    chicago = row['chicago'].values[0]
    cbd = row['cbd'].values[0]
    if chicago == 1 and cbd == 1:
        return 'CBD'
    elif chicago == 1 and cbd == 0:
        return 'city_non_cbd'
    else:
        return 'suburb'

def get_fixed_cost_car(zone_type):
    costs = {'CBD': 37.28, 'city_non_cbd': 20.00, 'suburb': 0.00}
    return costs.get(zone_type, 0.00)
```

---

## Data Validation Rules

Applied in every script before computing any metrics:

1. `travel_distance_miles` must be > 0 and not NaN
2. `travel_time_mins` must be > 0 and not NaN
3. Both origin_taz and destination_taz must be present
4. Rows failing any check are flagged as `invalid=True` with a `reason` column

Typical invalid rates are significant — many TAZ pairs are unreachable by a given mode.

---

## Expected Speed Ranges (for sanity checks)

| Mode     | Typical generalized speed range |
|----------|---------------------------------|
| Walking  | 2.5–3.5 mph (physical speed)    |
| Bicycle  | 4–10 mph (generalized)          |
| Car CBD  | Lower due to high fixed cost    |
| Car Suburb | Higher, no parking penalty   |

---

## Output File Convention

Each script produces three CSVs in the `outputs/` directory:

| File                              | Contents                        |
|-----------------------------------|---------------------------------|
| `{mode}_generalized_full.csv`     | All TAZ pairs, including invalid |
| `{mode}_generalized_clean.csv`    | Valid pairs only, computed metrics |
| `{mode}_generalized_invalid.csv`  | Flagged invalid pairs with reason |

Output columns for clean files (example — car mode):
```
origin_taz, destination_taz, zone_type, travel_distance_miles, travel_time_mins,
gen_speed_low_vot, gen_speed_mid_vot, gen_speed_high_vot,
gen_time_low_vot, gen_time_mid_vot, gen_time_high_vot,
gen_cost_low_vot, gen_cost_mid_vot, gen_cost_high_vot
```
