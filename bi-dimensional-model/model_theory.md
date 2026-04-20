# Model Theory — Bidimensional Transportation Model (Khisty & Sriraj, 1995)

## Source

Khisty, C.J. & Sriraj, P.S. (1995). "Use of Scenario-Building Transportation Model
for Developing Countries." *Transportation Research Record 1563*, pp. 16–25.
Illinois Institute of Technology, Chicago.

---

## Model Overview

A **macroscopic, bidimensional** model that identifies the optimal travel mode
for any combination of:
- **D** — physical displacement / trip length (miles or km)
- **H** — value of time ($/hr), a proxy for traveler income

The model generates a 2D matrix where each cell contains the mode with the
highest generalized speed, allowing policy makers to quickly see which modes
dominate under which conditions.

---

## Mode Parameters

Each transportation mode is defined by four parameters:

| Symbol | Parameter            | Units      |
|--------|----------------------|------------|
| Tom    | Access time          | hours      |
| Vm     | Modal speed          | miles/hr   |
| Com    | Fixed modal cost     | $          |
| γm     | Cost per unit distance | $/mile   |

---

## Core Formulas

### Transport Time
```
Tm(D) = Tom + (D / Vm)
```
Access time plus in-vehicle travel time.

### Transport Cost
```
Cm(D) = Com + (γm × D)
```
Fixed cost plus distance-proportional variable cost.

### Generalized Cost
```
Cgm(H, D) = Cm(D) + H × Tm(D)
           = Com + γm×D + H×(Tom + D/Vm)
```
Monetary cost plus the monetary value of travel time.

### Generalized Time
```
Tgm(H, D) = Tm(D) + Cm(D) / H
           = Tom + D/Vm + (Com + γm×D) / H
```
Travel time plus time-equivalent of monetary cost (cost ÷ VoT).

### Generalized Speed  ← the key output metric
```
Vgm(H, D) = D / Tgm(H, D)
           = (H × D) / (H×Tom + H×D/Vm + Com + γm×D)
```
Displacement divided by generalized time. Higher is better.
The optimal mode for any (H, D) pair is the one maximizing Vgm.

---

## Python Implementation (from main.py)

```python
@dataclass
class Mode:
    name             : str
    access_time      : float  # Tom (hours)
    modal_speed      : float  # Vm  (miles/hr)
    fixed_modal_cost : float  # Com ($)
    cost_per_distance: float  # γm  ($/mile)

    def transport_time(self, displacement):
        return self.access_time + (displacement / self.modal_speed)

    def transport_cost(self, displacement):
        return self.fixed_modal_cost + (self.cost_per_distance * displacement)

    def generalized_time(self, value_of_time, displacement):
        return self.transport_time(displacement) + \
               (self.transport_cost(displacement) / value_of_time)

    def generalized_speed(self, value_of_time, displacement):
        return displacement / self.generalized_time(value_of_time, displacement)
```

---

## Value of Time (VoT) — H

VoT represents the monetary value a traveler assigns to saving one hour of travel time.
Empirically approximated as 70% of the wage rate (Khisty & Sriraj).

In this project's Chicago application, three income-bracket VoT levels are used:

| Bracket | VoT ($/hr) |
|---------|-----------|
| Low     | $14.64    |
| Mid     | $30.62    |
| High    | $80.84    |

---

## Key Behavioral Insights from the Model

- **Walking** (zero costs): generalized_speed == average_speed, VoT-independent.
- **Low-cost modes** (bike, walk) dominate short distances at all VoT levels.
- **Higher VoT travelers** prefer faster modes even at higher cost — their time is worth more.
- **Fixed costs** (Com) disadvantage a mode at short distances; the penalty diminishes as D grows.
- **CBD destinations** have high fixed costs (parking) → significantly lower generalized speeds
  vs. suburban destinations for car mode.

---

## Chicago Scenario — Mode Parameters

See `chicago_taz_analysis.md` for the full parameter table used in OTP-based analysis.

The `scenario_new` in `main.py` captures an early Chicago parameterization (miles/hr):

```python
scenario_new = [
    Mode('Walking',     .00, 3., 0.00, 0.0),
    Mode('Bicycles',    .03, 7., 0.00, .25),
    Mode('Automobiles', .03, 11, 0.00, 0.81),
    Mode('Taxis',       .50, 11, 3.25, 2.25),
    Mode('Buses',       .15, 9., 2.25, 0.0),
    Mode('Subway',      .25, 18, 2.50, 0.5),
    Mode('Train',       .33, 30, 3.75, 1.0),
]
```
