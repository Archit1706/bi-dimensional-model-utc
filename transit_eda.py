"""
Transit Bidimensional Model — Descriptive Statistics & EDA
==========================================================
Reads transit_generalized_metrics_full.csv (or _clean.csv) and produces:

  1. transit_eda_stats.txt  — comprehensive descriptive statistics
  2. plots/                 — one PNG per figure (copy into your doc manually)

Run:
    python transit_eda.py
    python transit_eda.py --input output/transit_generalized_metrics_full.csv
                          --output-dir eda_output
"""

import argparse
import os
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
TOTAL_POSSIBLE_PAIRS = 2926 * 2925          # 8,558,550
VOT_LABELS = {"low": "$14.64/hr", "mid": "$30.62/hr", "high": "$80.84/hr"}
ZONE_ORDER  = ["CBD", "City_non_CBD", "Suburb", "Unknown"]
ZONE_COLORS = {"CBD": "#C0392B", "City_non_CBD": "#E67E22",
               "Suburb": "#27AE60", "Unknown": "#95A5A6"}

PALETTE = "Blues_d"
sns.set_theme(style="whitegrid", font_scale=1.1)
plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight"})


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def load(path: str) -> pd.DataFrame:
    """Load the full or clean output CSV; auto-detect separator."""
    sep = "\t" if path.endswith(".tsv") else ","
    df = pd.read_csv(path, sep=sep, low_memory=False)
    # Normalise column types
    for col in ["is_valid", "fare_estimated"]:
        if col in df.columns:
            df[col] = df[col].map(
                {True: True, False: False, "TRUE": True, "FALSE": False,
                 "True": True, "False": False, 1: True, 0: False}
            ).astype(bool)
    for col in ["boardings", "transfers_used"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def savefig(fig, name: str, plot_dir: Path):
    path = plot_dir / name
    fig.savefig(path)
    plt.close(fig)
    print(f"  saved {path.name}")


def section(title: str, width: int = 72) -> str:
    bar = "=" * width
    return f"\n{bar}\n{title.upper()}\n{bar}\n"


def subsection(title: str, width: int = 72) -> str:
    return f"\n{'-' * width}\n{title}\n{'-' * width}\n"


def fmt_pct(num, denom):
    return f"{num:>12,}  ({100*num/denom:5.1f}%)" if denom else f"{num:>12,}"


def pct_label(ax, total=None):
    """Add percentage labels on top of each bar."""
    for p in ax.patches:
        h = p.get_height()
        if h == 0:
            continue
        label = f"{100*h/total:.1f}%" if total else f"{h:,.0f}"
        ax.annotate(label,
                    (p.get_x() + p.get_width() / 2, h),
                    ha="center", va="bottom", fontsize=9)


# ---------------------------------------------------------------------------
# STATISTICS
# ---------------------------------------------------------------------------

def compute_stats(df: pd.DataFrame, total_possible: int) -> str:
    valid  = df[df["is_valid"] == True].copy()
    invalid= df[df["is_valid"] == False].copy()
    n_all  = len(df)
    n_v    = len(valid)
    n_i    = len(invalid)

    lines = []
    lines.append("TRANSIT BIDIMENSIONAL MODEL — DESCRIPTIVE STATISTICS")
    lines.append("Chicago 7-County TAZ Analysis  |  Khisty & Sriraj Model")
    lines.append("=" * 72)

    # --- 1. Coverage ---
    lines.append(section("1. Coverage & Data Availability"))
    lines.append(f"  Total possible OD pairs (2926×2925) : {total_possible:>12,}")
    lines.append(f"  Pairs with any transit record        : {fmt_pct(n_all,  total_possible)}")
    lines.append(f"  Valid (routable) pairs               : {fmt_pct(n_v,   total_possible)}")
    lines.append(f"  Invalid / no-route pairs             : {fmt_pct(n_i,   total_possible)}")
    lines.append(f"  Pairs with fare estimated (CSV-only) : {fmt_pct(valid['fare_estimated'].sum(), n_v)}")

    # By dest zone
    lines.append(subsection("Coverage by Destination Zone Type"))
    for z in ZONE_ORDER:
        sub = df[df["dest_classification"] == z]
        v   = (sub["is_valid"] == True).sum()
        lines.append(f"  {z:<15}: {len(sub):>8,} total  |  {v:>8,} valid ({100*v/len(sub) if len(sub) else 0:.1f}%)")

    # --- 2. Fare ---
    lines.append(section("2. Fare Analysis (one-way, Ventra full fare)"))
    for label, col in [("All valid", valid["fare"]),
                        ("JSON-derived (exact)", valid.loc[~valid["fare_estimated"], "fare"]),
                        ("CSV-estimated",        valid.loc[ valid["fare_estimated"], "fare"])]:
        col = col.dropna()
        if col.empty:
            continue
        lines.append(f"\n  {label} (n={len(col):,})")
        lines.append(f"    Mean   : ${col.mean():.3f}")
        lines.append(f"    Median : ${col.median():.3f}")
        lines.append(f"    Std    : ${col.std():.3f}")
        lines.append(f"    Min    : ${col.min():.3f}")
        lines.append(f"    Max    : ${col.max():.3f}")
        for p in [25, 75, 90, 95]:
            lines.append(f"    P{p:<2}   : ${col.quantile(p/100):.3f}")

    lines.append(subsection("Fare Distribution"))
    fc = valid["fare"].value_counts().sort_index()
    for fare, cnt in fc.items():
        lines.append(f"  ${fare:<6.2f}  : {fmt_pct(cnt, n_v)}")

    lines.append(subsection("Boardings per Trip"))
    bc = valid["boardings"].value_counts().sort_index()
    for b, cnt in bc.items():
        lines.append(f"  {b} boarding(s) : {fmt_pct(cnt, n_v)}")

    lines.append(subsection("Transfers per Trip"))
    tc = valid["transfers_used"].value_counts().sort_index()
    for t, cnt in tc.items():
        lines.append(f"  {t} transfer(s) : {fmt_pct(cnt, n_v)}")

    # --- 3. Travel Time ---
    lines.append(section("3. Travel Time & Distance"))

    def stat_block(series, label, unit):
        s = series.dropna()
        lines.append(f"\n  {label}  (n={len(s):,})")
        lines.append(f"    Mean   : {s.mean():.2f} {unit}")
        lines.append(f"    Median : {s.median():.2f} {unit}")
        lines.append(f"    Std    : {s.std():.2f} {unit}")
        lines.append(f"    Min    : {s.min():.2f} {unit}")
        lines.append(f"    Max    : {s.max():.2f} {unit}")
        for p in [25, 75, 90, 95]:
            lines.append(f"    P{p:<2}   : {s.quantile(p/100):.2f} {unit}")

    stat_block(valid["access_time_mins"],  "Access Time (first walk leg)", "min")
    stat_block(valid["travel_time_mins"],  "In-vehicle + transfer time",   "min")
    total_mins = valid["access_time_mins"] + valid["travel_time_mins"]
    stat_block(total_mins,                 "Total door-to-door time",      "min")
    stat_block(valid["travel_distance_miles"], "Trip Distance",            "miles")
    stat_block(valid["modal_speed_mph"],   "Modal Speed (in-vehicle)",     "mph")

    lines.append(subsection("Travel Time by Destination Zone Type"))
    for z in ZONE_ORDER:
        sub = valid[valid["dest_classification"] == z]
        if sub.empty:
            continue
        t = (sub["access_time_mins"] + sub["travel_time_mins"])
        lines.append(f"  {z:<15}: mean {t.mean():.1f} min  |  median {t.median():.1f} min  |  n={len(sub):,}")

    # --- 4. Generalized Metrics ---
    lines.append(section("4. Generalized Speed & Time  (Khisty & Sriraj)"))
    for vot_key, vot_label in VOT_LABELS.items():
        gs_col = f"generalized_speed_mph_{vot_key}"
        gt_col = f"generalized_time_hours_{vot_key}"
        lines.append(subsection(f"VoT = {vot_label}"))
        stat_block(valid[gs_col], "Generalized Speed", "mph")
        stat_block(valid[gt_col] * 60, "Generalized Time", "min")
        lines.append(f"\n  By destination zone type:")
        for z in ZONE_ORDER:
            sub = valid[valid["dest_classification"] == z]
            if sub.empty:
                continue
            gs = sub[gs_col].dropna()
            lines.append(f"    {z:<15}: gen speed mean {gs.mean():.2f} mph  |  "
                          f"gen time mean {(sub[gt_col].dropna()*60).mean():.1f} min")

    # --- 5. Transit Mode Combinations ---
    lines.append(section("5. Leg Sequence / Transit Mode Combinations"))
    seq = valid["leg_sequence"].dropna()
    seq = seq[seq != ""]
    counts = seq.value_counts()
    lines.append(f"  Unique leg sequences : {len(counts)}")
    lines.append(f"\n  Top 20 sequences:")
    for seq_str, cnt in counts.head(20).items():
        lines.append(f"    {fmt_pct(cnt, len(seq))}   {seq_str}")

    # Agency-level tallies from leg sequences
    lines.append(subsection("Agency Usage (trips containing each agency)"))
    for agency, kw in [("CTA Bus only",  lambda s: "cta_bus"   in s and "metra" not in s and "pace" not in s),
                       ("CTA Rail only", lambda s: "cta_rail"  in s and "metra" not in s and "pace" not in s and "cta_bus" not in s),
                       ("CTA Bus+Rail",  lambda s: "cta_bus"   in s and "cta_rail" in s),
                       ("Pace",          lambda s: "pace_bus"  in s),
                       ("Metra",         lambda s: "metra_rail" in s),
                       ("CTA+Pace",      lambda s: "pace_bus"  in s and ("cta_bus" in s or "cta_rail" in s)),
                       ("Multi-agency",  lambda s: sum(x in s for x in ["cta_bus","cta_rail","pace_bus","metra_rail"]) > 1)]:
        n = seq.apply(kw).sum()
        lines.append(f"  {agency:<20}: {fmt_pct(n, len(seq))}")

    lines.append("\n" + "=" * 72)
    lines.append("END OF REPORT")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PLOTS
# ---------------------------------------------------------------------------

def plot_coverage(df: pd.DataFrame, plot_dir: Path, total_possible: int):
    """Fig 1 — Coverage breakdown."""
    n_v  = (df["is_valid"] == True).sum()
    n_i  = (df["is_valid"] == False).sum()
    n_miss= total_possible - len(df)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Transit OD Pair Coverage — Chicago 7-County TAZ", fontweight="bold")

    # Left: overall pie
    ax = axes[0]
    sizes  = [n_v, n_i, n_miss]
    labels = [f"Routable\n{n_v:,}", f"No route\n{n_i:,}", f"No data\n{n_miss:,}"]
    colors = ["#2ECC71", "#E74C3C", "#BDC3C7"]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors,
        autopct=lambda p: f"{p:.1f}%" if p > 1 else "",
        startangle=90, pctdistance=0.78)
    for at in autotexts:
        at.set_fontsize(10)
    ax.set_title("All Possible OD Pairs")

    # Right: valid pairs by dest zone
    ax2 = axes[1]
    zone_data = (
        df[df["is_valid"] == True]["dest_classification"]
        .value_counts()
        .reindex(ZONE_ORDER, fill_value=0)
    )
    bars = ax2.bar(zone_data.index,
                   zone_data.values,
                   color=[ZONE_COLORS.get(z, "#95A5A6") for z in zone_data.index])
    pct_label(ax2, total=n_v)
    ax2.set_title("Valid (Routable) Pairs by Destination Zone Type")
    ax2.set_ylabel("OD Pair Count")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    savefig(fig, "fig01_coverage.png", plot_dir)


def plot_fare_distribution(valid: pd.DataFrame, plot_dir: Path):
    """Fig 2 — Fare distribution."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("One-Way Transit Fare Distribution", fontweight="bold")

    # Left: histogram of all fares
    ax = axes[0]
    ax.hist(valid["fare"].dropna(), bins=30, color="#2980B9", edgecolor="white")
    ax.axvline(valid["fare"].mean(),   color="red",    linestyle="--", label=f'Mean ${valid["fare"].mean():.2f}')
    ax.axvline(valid["fare"].median(), color="orange", linestyle="--", label=f'Median ${valid["fare"].median():.2f}')
    ax.set_xlabel("Fare ($)")
    ax.set_ylabel("OD Pair Count")
    ax.set_title("Fare Histogram (All Valid Pairs)")
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # Right: fare value counts as bar
    ax2 = axes[1]
    fc = valid["fare"].value_counts().sort_index()
    ax2.bar([f"${f:.2f}" for f in fc.index], fc.values, color="#2980B9", edgecolor="white")
    pct_label(ax2, total=len(valid))
    ax2.set_xlabel("Fare ($)")
    ax2.set_ylabel("OD Pair Count")
    ax2.set_title("Exact Fare Value Breakdown")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    savefig(fig, "fig02_fare_distribution.png", plot_dir)


def plot_fare_by_zone(valid: pd.DataFrame, plot_dir: Path):
    """Fig 3 — Fare boxplot by destination zone."""
    fig, ax = plt.subplots(figsize=(10, 5))
    data = [valid.loc[valid["dest_classification"] == z, "fare"].dropna()
            for z in ZONE_ORDER if not valid.loc[valid["dest_classification"] == z].empty]
    labels = [z for z in ZONE_ORDER
              if not valid.loc[valid["dest_classification"] == z].empty]
    bp = ax.boxplot(data, labels=labels, patch_artist=True, notch=False)
    for patch, lbl in zip(bp["boxes"], labels):
        patch.set_facecolor(ZONE_COLORS.get(lbl, "#95A5A6"))
        patch.set_alpha(0.7)
    ax.set_ylabel("One-Way Fare ($)")
    ax.set_title("Fare Distribution by Destination Zone Type", fontweight="bold")
    ax.set_xlabel("Destination Zone Type")
    savefig(fig, "fig03_fare_by_zone.png", plot_dir)


def plot_travel_time_components(valid: pd.DataFrame, plot_dir: Path):
    """Fig 4 — Access vs travel time stacked distribution."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Travel Time Components", fontweight="bold")

    ax = axes[0]
    ax.hist(valid["access_time_mins"].dropna(), bins=40,
            alpha=0.7, color="#E74C3C", label="Access (first walk)")
    ax.hist(valid["travel_time_mins"].dropna(), bins=40,
            alpha=0.7, color="#3498DB", label="In-vehicle + transfers")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("OD Pair Count")
    ax.set_title("Access vs In-vehicle Time")
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    ax2 = axes[1]
    total = valid["access_time_mins"] + valid["travel_time_mins"]
    ax2.hist(total.dropna(), bins=50, color="#8E44AD", edgecolor="white")
    ax2.axvline(total.mean(),   color="red",    linestyle="--", label=f"Mean {total.mean():.1f} min")
    ax2.axvline(total.median(), color="orange", linestyle="--", label=f"Median {total.median():.1f} min")
    ax2.set_xlabel("Total Door-to-Door Time (minutes)")
    ax2.set_ylabel("OD Pair Count")
    ax2.set_title("Total Door-to-Door Travel Time")
    ax2.legend()
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    savefig(fig, "fig04_travel_time_components.png", plot_dir)


def plot_distance_distribution(valid: pd.DataFrame, plot_dir: Path):
    """Fig 5 — Trip distance histogram + CDF."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Trip Distance Distribution", fontweight="bold")

    dist = valid["travel_distance_miles"].dropna()

    ax = axes[0]
    ax.hist(dist, bins=60, color="#27AE60", edgecolor="white")
    ax.axvline(dist.mean(),   color="red",    linestyle="--", label=f"Mean {dist.mean():.2f} mi")
    ax.axvline(dist.median(), color="orange", linestyle="--", label=f"Median {dist.median():.2f} mi")
    ax.set_xlabel("Distance (miles)")
    ax.set_ylabel("OD Pair Count")
    ax.set_title("Histogram")
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    ax2 = axes[1]
    sorted_d = np.sort(dist)
    cdf = np.arange(1, len(sorted_d)+1) / len(sorted_d)
    ax2.plot(sorted_d, cdf * 100, color="#27AE60", linewidth=2)
    for pct in [25, 50, 75, 90]:
        val = np.percentile(sorted_d, pct)
        ax2.axvline(val, linestyle=":", color="gray", alpha=0.8)
        ax2.text(val + 0.1, pct - 4, f"P{pct}\n{val:.1f}mi", fontsize=8)
    ax2.set_xlabel("Distance (miles)")
    ax2.set_ylabel("Cumulative % of Trips")
    ax2.set_title("Cumulative Distribution (CDF)")
    savefig(fig, "fig05_distance_distribution.png", plot_dir)


def plot_speed_distance_scatter(valid: pd.DataFrame, plot_dir: Path):
    """Fig 6 — Modal speed vs distance (core bidimensional relationship)."""
    # Sample for readability if very large
    sample = valid.dropna(subset=["travel_distance_miles", "modal_speed_mph"])
    if len(sample) > 50_000:
        sample = sample.sample(50_000, random_state=42)

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(
        sample["travel_distance_miles"],
        sample["modal_speed_mph"],
        c=sample["fare"],
        cmap="YlOrRd",
        alpha=0.3, s=6,
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Fare ($)")
    ax.set_xlabel("Trip Distance (miles)")
    ax.set_ylabel("Modal Speed (mph)")
    ax.set_title("Modal Speed vs Distance — Coloured by Fare\n"
                 "(core bidimensional variable space)", fontweight="bold")
    savefig(fig, "fig06_speed_distance_scatter.png", plot_dir)


def plot_generalized_speed_distributions(valid: pd.DataFrame, plot_dir: Path):
    """Fig 7 — Generalized speed distributions for all three VoT levels."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    fig.suptitle("Generalized Speed Distribution by Value of Time (VoT)",
                 fontweight="bold")

    colors = {"low": "#3498DB", "mid": "#E67E22", "high": "#8E44AD"}
    for ax, (vot_key, vot_label) in zip(axes, VOT_LABELS.items()):
        col = f"generalized_speed_mph_{vot_key}"
        data = valid[col].dropna()
        ax.hist(data, bins=60, color=colors[vot_key], edgecolor="white", alpha=0.85)
        ax.axvline(data.mean(),   color="red",   linestyle="--",
                   label=f"Mean {data.mean():.2f}")
        ax.axvline(data.median(), color="black", linestyle="--",
                   label=f"Median {data.median():.2f}")
        ax.set_title(f"VoT = {vot_label}")
        ax.set_xlabel("Generalized Speed (mph)")
        ax.set_ylabel("OD Pair Count")
        ax.legend(fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    savefig(fig, "fig07_gen_speed_distributions.png", plot_dir)


def plot_gen_speed_by_zone(valid: pd.DataFrame, plot_dir: Path):
    """Fig 8 — Generalized speed boxplots by zone type, one panel per VoT."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    fig.suptitle("Generalized Speed by Destination Zone Type", fontweight="bold")

    for ax, (vot_key, vot_label) in zip(axes, VOT_LABELS.items()):
        col = f"generalized_speed_mph_{vot_key}"
        data_by_zone = [
            valid.loc[valid["dest_classification"] == z, col].dropna()
            for z in ZONE_ORDER
            if not valid.loc[valid["dest_classification"] == z].empty
        ]
        labels = [z for z in ZONE_ORDER
                  if not valid.loc[valid["dest_classification"] == z].empty]
        bp = ax.boxplot(data_by_zone, labels=labels,
                        patch_artist=True, notch=False, showfliers=False)
        for patch, lbl in zip(bp["boxes"], labels):
            patch.set_facecolor(ZONE_COLORS.get(lbl, "#95A5A6"))
            patch.set_alpha(0.7)
        ax.set_title(f"VoT = {vot_label}")
        ax.set_ylabel("Generalized Speed (mph)" if ax == axes[0] else "")
        ax.set_xlabel("Destination Zone Type")
        ax.tick_params(axis="x", rotation=15)
    savefig(fig, "fig08_gen_speed_by_zone.png", plot_dir)


def plot_gen_time_vs_distance(valid: pd.DataFrame, plot_dir: Path):
    """Fig 9 — Generalized time vs distance for each VoT (reveals model curvature)."""
    sample = valid.dropna(subset=["travel_distance_miles"])
    if len(sample) > 50_000:
        sample = sample.sample(50_000, random_state=42)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    fig.suptitle("Generalized Time vs Distance by VoT\n"
                 "(steeper = more cost impact relative to time)", fontweight="bold")
    colors = {"low": "#3498DB", "mid": "#E67E22", "high": "#8E44AD"}

    for ax, (vot_key, vot_label) in zip(axes, VOT_LABELS.items()):
        col = f"generalized_time_hours_{vot_key}"
        y = sample[col].dropna() * 60  # → minutes
        x = sample.loc[y.index, "travel_distance_miles"]
        ax.scatter(x, y, alpha=0.15, s=4, color=colors[vot_key])
        # Trend line via 2nd-order poly
        try:
            z = np.polyfit(x, y, 2)
            xfit = np.linspace(x.min(), x.quantile(0.99), 200)
            ax.plot(xfit, np.polyval(z, xfit), color="black", linewidth=1.8,
                    label="Trend (poly-2)")
        except Exception:
            pass
        ax.set_title(f"VoT = {vot_label}")
        ax.set_xlabel("Distance (miles)")
        ax.set_ylabel("Generalized Time (min)" if ax == axes[0] else "")
        ax.legend(fontsize=9)
    savefig(fig, "fig09_gen_time_vs_distance.png", plot_dir)


def plot_leg_sequences(valid: pd.DataFrame, plot_dir: Path):
    """Fig 10 — Top 15 leg sequences (transit mode combinations)."""
    seq = valid["leg_sequence"].dropna()
    seq = seq[seq != ""]
    counts = seq.value_counts().head(15)

    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.barh(counts.index[::-1], counts.values[::-1], color="#2C3E50")
    ax.set_xlabel("Number of OD Pairs")
    ax.set_title("Top 15 Transit Leg Sequences (Transit Mode Combinations)",
                 fontweight="bold")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    for bar, val in zip(bars, counts.values[::-1]):
        ax.text(val + counts.max() * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,}", va="center", fontsize=9)
    savefig(fig, "fig10_leg_sequences.png", plot_dir)


def plot_boardings_transfers(valid: pd.DataFrame, plot_dir: Path):
    """Fig 11 — Boardings and transfers per trip."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Boardings & Transfers per Trip", fontweight="bold")

    for ax, col, title, color in [
        (axes[0], "boardings",      "Boardings per Trip",  "#2980B9"),
        (axes[1], "transfers_used", "Transfers per Trip",  "#27AE60"),
    ]:
        vc = valid[col].value_counts().sort_index()
        ax.bar(vc.index.astype(str), vc.values, color=color, edgecolor="white")
        pct_label(ax, total=len(valid))
        ax.set_xlabel(col.replace("_", " ").title())
        ax.set_ylabel("OD Pair Count")
        ax.set_title(title)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    savefig(fig, "fig11_boardings_transfers.png", plot_dir)


def plot_access_time_by_zone(valid: pd.DataFrame, plot_dir: Path):
    """Fig 12 — Access time violin plot by destination zone."""
    fig, ax = plt.subplots(figsize=(10, 5))
    zones_present = [z for z in ZONE_ORDER
                     if not valid.loc[valid["dest_classification"] == z].empty]
    data = [valid.loc[valid["dest_classification"] == z, "access_time_mins"].dropna()
            for z in zones_present]
    vp = ax.violinplot(data, showmedians=True)
    for i, (body, z) in enumerate(zip(vp["bodies"], zones_present)):
        body.set_facecolor(ZONE_COLORS.get(z, "#95A5A6"))
        body.set_alpha(0.7)
    ax.set_xticks(range(1, len(zones_present) + 1))
    ax.set_xticklabels(zones_present)
    ax.set_ylabel("Access Time (minutes)")
    ax.set_xlabel("Destination Zone Type")
    ax.set_title("Access Time (First Walk Leg) by Destination Zone Type",
                 fontweight="bold")
    savefig(fig, "fig12_access_time_by_zone.png", plot_dir)


def plot_gen_speed_vot_overlay(valid: pd.DataFrame, plot_dir: Path):
    """Fig 13 — Overlay KDE of generalized speed across all three VoT levels."""
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = {"low": "#3498DB", "mid": "#E67E22", "high": "#8E44AD"}
    for vot_key, vot_label in VOT_LABELS.items():
        col = f"generalized_speed_mph_{vot_key}"
        data = valid[col].dropna()
        data = data[data < data.quantile(0.99)]   # trim extreme outliers for plot
        data.plot.kde(ax=ax, label=f"VoT = {vot_label}",
                      color=colors[vot_key], linewidth=2)
    ax.set_xlabel("Generalized Speed (mph)")
    ax.set_ylabel("Density")
    ax.set_title("Generalized Speed — KDE Overlay Across VoT Levels", fontweight="bold")
    ax.legend()
    ax.set_xlim(left=0)
    savefig(fig, "fig13_gen_speed_vot_overlay.png", plot_dir)


def plot_fare_vs_distance(valid: pd.DataFrame, plot_dir: Path):
    """Fig 14 — Fare vs distance to show agency/zone variation."""
    sample = valid.dropna(subset=["travel_distance_miles", "fare"])
    if len(sample) > 50_000:
        sample = sample.sample(50_000, random_state=42)

    fig, ax = plt.subplots(figsize=(10, 5))
    for z in ZONE_ORDER:
        sub = sample[sample["dest_classification"] == z]
        if sub.empty:
            continue
        ax.scatter(sub["travel_distance_miles"], sub["fare"],
                   alpha=0.2, s=5, color=ZONE_COLORS.get(z, "#95A5A6"), label=z)
    ax.set_xlabel("Trip Distance (miles)")
    ax.set_ylabel("Fare ($)")
    ax.set_title("Fare vs Distance by Destination Zone Type", fontweight="bold")
    handles, labels = ax.get_legend_handles_labels()
    # Deduplicate legend
    seen_lbl, hd, lb = set(), [], []
    for h, l in zip(handles, labels):
        if l not in seen_lbl:
            seen_lbl.add(l); hd.append(h); lb.append(l)
    ax.legend(hd, lb, markerscale=3)
    savefig(fig, "fig14_fare_vs_distance.png", plot_dir)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="EDA & descriptive stats for transit_generalized_metrics output")
    ap.add_argument("--input",      default="output/transit_generalized_metrics_full.csv",
                    help="Full output CSV from transit_generalized_metrics.py")
    ap.add_argument("--output-dir", default="eda_output",
                    help="Directory for stats .txt and plot PNGs")
    ap.add_argument("--total-pairs", type=int, default=TOTAL_POSSIBLE_PAIRS,
                    help=f"Total theoretical OD pairs (default {TOTAL_POSSIBLE_PAIRS:,})")
    args = ap.parse_args()

    out = Path(args.output_dir)
    plot_dir = out / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading: {args.input}")
    df    = load(args.input)
    valid = df[df["is_valid"] == True].copy()
    print(f"  Total rows   : {len(df):,}")
    print(f"  Valid rows   : {len(valid):,}")

    # ---- Stats ----
    print("\nComputing descriptive statistics...")
    stats_text = compute_stats(df, args.total_pairs)
    stats_path = out / "transit_eda_stats.txt"
    stats_path.write_text(stats_text, encoding="utf-8")
    print(f"  saved {stats_path}")

    # ---- Plots ----
    print("\nGenerating plots...")
    plot_coverage(df, plot_dir, args.total_pairs)
    plot_fare_distribution(valid, plot_dir)
    plot_fare_by_zone(valid, plot_dir)
    plot_travel_time_components(valid, plot_dir)
    plot_distance_distribution(valid, plot_dir)
    plot_speed_distance_scatter(valid, plot_dir)
    plot_generalized_speed_distributions(valid, plot_dir)
    plot_gen_speed_by_zone(valid, plot_dir)
    plot_gen_time_vs_distance(valid, plot_dir)
    plot_leg_sequences(valid, plot_dir)
    plot_boardings_transfers(valid, plot_dir)
    plot_access_time_by_zone(valid, plot_dir)
    plot_gen_speed_vot_overlay(valid, plot_dir)
    plot_fare_vs_distance(valid, plot_dir)

    print(f"\nDone. All outputs in: {out.resolve()}")
    print(f"  Stats : {stats_path.name}")
    print(f"  Plots : {plot_dir}/fig01..fig14_*.png")


if __name__ == "__main__":
    main()
