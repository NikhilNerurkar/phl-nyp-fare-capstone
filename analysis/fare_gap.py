"""Core question 3: quantify the fare gap - where does rail win or lose on
value against bus?

Uses same_source_subset() throughout: comparing Amtrak-via-Wanderu against
bus-via-Wanderu, never against bus-via-its-own-API, because that cross-
source mix carries a measured ~20% bias against rail (see clean.py).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import style
from .clean import same_source_subset


def fare_gap_by_dbd(df: pd.DataFrame, out_path: Path,
                    rail_service: str = "Northeast Regional",
                    bus_benchmark: str = "Greyhound") -> dict:
    """Rail-minus-bus median fare at each DBD. Positive = rail costs more.

    Regional (not Acela) is the right rail comparator for a bus rider's
    decision - Acela is a different product serving a different persona
    (see personas.py: Business Traveler).
    """
    same = same_source_subset(df)
    rail = same[same["service_name"] == rail_service]
    bus = same[same["operator_display"] == bus_benchmark]

    rail_curve = rail.groupby("dbd")["price_usd"].median()
    bus_curve = bus.groupby("dbd")["price_usd"].median()
    gap = (rail_curve - bus_curve).dropna().sort_index()
    gap = gap[gap.index <= 28]

    style.apply_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [style.STATUS["critical"] if v > 0 else style.STATUS["good"]
             for v in gap.values]
    ax.bar(gap.index, gap.values, color=colors, width=0.8)
    ax.axhline(0, color=style.BASELINE, linewidth=1)
    ax.invert_xaxis()
    ax.set_xlabel("Days before departure")
    ax.set_ylabel(f"{rail_service} minus {bus_benchmark} ($)")

    style.finish(fig, out_path,
                title=f"{rail_service} vs {bus_benchmark}: who costs more, by DBD",
                subtitle="Red = rail costs more | Green = rail is cheaper "
                         "(same-source fares only - see docs/DATA_DICTIONARY.md)")

    crossover = gap[gap <= 0]
    return {
        "rail_service": rail_service, "bus_benchmark": bus_benchmark,
        "median_gap_usd": round(gap.median(), 2),
        "rail_cheaper_at_dbd": sorted(crossover.index.tolist()),
        "rail_cheaper_share_of_window": round(100 * len(crossover) / len(gap), 1)
        if len(gap) else None,
    }


def fare_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (rail service x bus operator): median gap, min/max, n.

    The underlying numbers behind the chart above - built for a slide table
    or an appendix, not a figure.
    """
    same = same_source_subset(df)
    rail_services = ["Acela", "Northeast Regional", "Keystone Service"]
    bus_ops = [o for o in same["operator_display"].unique()
              if o != "Amtrak" and o != "Other"]

    rows = []
    for svc in rail_services:
        rail_med = same.loc[same["service_name"] == svc, "price_usd"].median()
        if pd.isna(rail_med):
            continue
        for op in bus_ops:
            bus_med = same.loc[same["operator_display"] == op, "price_usd"].median()
            if pd.isna(bus_med):
                continue
            rows.append({
                "rail_service": svc, "bus_operator": op,
                "rail_median": round(rail_med, 2), "bus_median": round(bus_med, 2),
                "gap_usd": round(rail_med - bus_med, 2),
                "gap_pct": round(100 * (rail_med - bus_med) / bus_med, 1),
            })
    return pd.DataFrame(rows).sort_values(["rail_service", "gap_usd"])
