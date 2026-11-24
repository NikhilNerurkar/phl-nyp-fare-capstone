"""Core question 2: how does fare behave by days-before-departure, day of
week, and time of day, per mode?

DBD here is always the derived column (travel_date - snapshot_date), never a
fixed milestone list - so a chart made today with DBD 0-27 and a chart made
in three weeks with DBD 0-55 both come out of the same function unchanged.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from . import style


def booking_curve_by_operator(df: pd.DataFrame, out_path: Path) -> dict:
    """Median fare vs DBD, one line per operator (bus) + one per Amtrak
    service (so the internal Acela/Regional/Keystone split survives).
    """
    style.apply_style()
    fig, ax = plt.subplots(figsize=(8, 5))

    lines_drawn = []
    amtrak = df[df["operator_display"] == "Amtrak"]
    for svc, color in style.SERVICE_COLOR.items():
        sub = amtrak[amtrak["service_name"] == svc]
        if sub.empty:
            continue
        curve = sub.groupby("dbd")["price_usd"].median().sort_index()
        curve = curve[curve.index <= 28]  # beyond this, too few dates to be stable
        if len(curve) < 3:
            continue
        ax.plot(curve.index, curve.values, color=color, linewidth=2, label=svc)
        lines_drawn.append(svc)

    bus = df[df["operator_display"] != "Amtrak"]
    for op in ["Greyhound", "FlixBus", "Peter Pan", "OurBus"]:
        sub = bus[bus["operator_display"] == op]
        if sub.empty:
            continue
        curve = sub.groupby("dbd")["price_usd"].median().sort_index()
        curve = curve[curve.index <= 28]
        if len(curve) < 3:
            continue
        ax.plot(curve.index, curve.values, color=style.operator_color(op),
                linewidth=1.5, linestyle="--", alpha=0.85, label=op)
        lines_drawn.append(op)

    ax.set_xlabel("Days before departure")
    ax.set_ylabel("Median fare ($)")
    ax.invert_xaxis()  # departure on the right, booking window reading left-to-right
    ax.legend(loc="upper left", fontsize=9, ncol=2)

    max_dbd = int(df["dbd"].max())
    style.finish(fig, out_path,
                title="Fare rises as departure approaches - rail more than bus",
                subtitle=f"Median fare by days before departure, 0-28 DBD "
                         f"(dataset covers up to {max_dbd} DBD)")
    return {"operators_plotted": lines_drawn, "max_dbd_in_data": max_dbd}


def booking_curve_by_dow(df: pd.DataFrame, out_path: Path, mode_filter=None) -> dict:
    """Median fare vs DBD, split by weekday vs weekend travel.

    Answers the framing doc's weekday-business vs weekend-leisure split
    directly: do the two rider segments see different pricing behavior?
    """
    style.apply_style()
    sub = df if mode_filter is None else df[df["operator_display"] == mode_filter]
    fig, ax = plt.subplots(figsize=(8, 5))

    for is_weekend, label, color in [
        (False, "Weekday travel", style.CAT["blue"]),
        (True, "Weekend travel", style.CAT["orange"]),
    ]:
        part = sub[sub["is_weekend"] == is_weekend]
        curve = part.groupby("dbd")["price_usd"].median().sort_index()
        curve = curve[curve.index <= 28]
        ax.plot(curve.index, curve.values, color=color, linewidth=2, label=label)

    ax.set_xlabel("Days before departure")
    ax.set_ylabel("Median fare ($)")
    ax.invert_xaxis()
    ax.legend(loc="upper left", fontsize=9)

    title_mode = mode_filter or "all modes"
    style.finish(fig, out_path,
                title=f"Weekday vs weekend booking curve - {title_mode}",
                subtitle="Median fare by days before departure")
    weekday_med = sub[~sub["is_weekend"]]["price_usd"].median()
    weekend_med = sub[sub["is_weekend"]]["price_usd"].median()
    return {"weekday_median": round(weekday_med, 2),
           "weekend_median": round(weekend_med, 2),
           "gap_pct": round(100 * (weekday_med - weekend_med) / weekend_med, 1)
           if weekend_med else None}


def fare_heatmap_by_hour_dow(df: pd.DataFrame, out_path: Path,
                             operator: str = "Amtrak") -> dict:
    """Median fare by (departure hour x day of week) for one operator.

    Uses the sequential blue ramp - this is a magnitude encoding, not identity.
    """
    style.apply_style()
    sub = df[(df["operator_display"] == operator) & df["depart_hour"].notna()]
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    pivot = (sub.groupby(["travel_dow", "depart_hour"])["price_usd"]
             .median().unstack(0).reindex(columns=range(7)))
    pivot.columns = dow_labels

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pivot.values, aspect="auto", cmap="Blues",
                  extent=[0, 7, 23, 0])
    ax.set_xticks([i + 0.5 for i in range(7)])
    ax.set_xticklabels(dow_labels)
    ax.set_ylabel("Departure hour")
    ax.invert_yaxis()
    ax.grid(False)
    cbar = fig.colorbar(im, ax=ax, label="Median fare ($)")
    cbar.outline.set_visible(False)

    style.finish(fig, out_path,
                title=f"{operator}: when fares peak, by day and hour",
                subtitle="Darker = higher median fare")
    peak = pivot.stack().idxmax()  # (depart_hour, dow_label)
    return {"peak_hour": int(peak[0]) if isinstance(peak, tuple) else None,
           "peak_dow": peak[1] if isinstance(peak, tuple) else None}
