"""Additional presentation figures beyond the four core questions - each one
answers a specific, concrete question a reader would actually ask, built
from data we already have (no new scraping, no new assumptions beyond
what's already documented elsewhere in this project).

Five figures:
  1. fare_volatility_by_group   - whose pricing moves around the most,
     day to day, holding the booking window constant (same technique as
     signals.py's lead/follower series - isolates real repricing from the
     booking-curve trend).
  2. book_ahead_savings          - concrete $ saved by booking early vs.
     last-minute, per operator/service - the single most actionable chart
     for a rider-facing slide.
  3. fare_distribution_by_group  - box plot of the full fare spread (not
     just the median) at a fixed booking window, per operator/service.
  4. flixbus_sold_out_by_dbd     - the one real demand/availability signal
     anywhere in this project (see elasticity.py's docstring for why nothing
     else qualifies) - how early do price-sensitive bus seats actually sell out.
  5. collection_coverage_by_source - rows collected per day per source, a
     transparency chart showing the scale and reliability of collection
     itself, not a pricing finding.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from . import style
from .clean import load_raw, same_source_subset
from .signals import MIN_DAYS_FOR_SIGNAL, daily_series_at_dbd_band

# Fixed set of groups used across charts 1-3, and their draw order/labels -
# Amtrak split into its three services (the sponsor's own ask), plus the
# bus operators big enough to not be folded into "Other".
GROUPS = ["Acela", "Northeast Regional", "Keystone Service",
         "Greyhound", "FlixBus", "Peter Pan", "OurBus"]


def _group_series(df: pd.DataFrame, group: str) -> pd.Series:
    if group in style.SERVICE_COLOR:
        return df.loc[df["service_name"] == group, "price_usd"]
    return df.loc[df["operator_display"] == group, "price_usd"]


def _group_color(group: str) -> str:
    return style.SERVICE_COLOR.get(group) or style.operator_color(group)


def fare_volatility_by_group(df: pd.DataFrame, out_path: Path,
                             dbd_lo: int = 5, dbd_hi: int = 9) -> dict:
    """Day-over-day fare volatility, holding the booking window constant.

    Same method as signals.py: fix a DBD band so the shrinking set of
    far-out travel dates doesn't masquerade as "the price is moving."
    Volatility = std dev of day-over-day %% change in the median fare at
    that band - whoever reprices the most, the most often.
    """
    same = same_source_subset(df)
    rows = []
    for group in GROUPS:
        col = "service_name" if group in style.SERVICE_COLOR else "operator_display"
        sub = same[same[col] == group]
        band = sub[(sub["dbd"] >= dbd_lo) & (sub["dbd"] <= dbd_hi)]
        series = band.groupby("snapshot_date")["price_usd"].median().sort_index()
        pct = series.pct_change().dropna()
        if len(pct) < 3:
            continue
        rows.append({"group": group, "n_days": len(pct),
                     "volatility_pct": round(100 * pct.std(), 2)})

    table = pd.DataFrame(rows).sort_values("volatility_pct", ascending=True)

    style.apply_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [_group_color(g) for g in table["group"]]
    ax.barh(table["group"], table["volatility_pct"], color=colors)
    ax.set_xlabel("Day-over-day fare volatility (std dev of %% change)")
    style.finish(fig, out_path,
                title="Whose pricing moves around the most, day to day?",
                subtitle=f"Median fare at {dbd_lo}-{dbd_hi} days before departure, "
                         f"{'enough days for a first read' if table['n_days'].min() >= MIN_DAYS_FOR_SIGNAL else 'preliminary - re-run with more days'}")
    return {"table": table.to_dict(orient="records")}


def book_ahead_savings(df: pd.DataFrame, out_path: Path,
                       early_dbd: int = 21, late_dbd: int = 1,
                       tolerance: int = 3) -> dict:
    """$ (and %%) saved booking ~`early_dbd` days out vs. ~`late_dbd` days
    out, per group - the single most actionable finding for a rider.

    Uses the nearest available DBD within `tolerance` of the target on
    each side, since not every group has data at the exact DBD requested.
    """
    same = same_source_subset(df)
    rows = []
    for group in GROUPS:
        col = "service_name" if group in style.SERVICE_COLOR else "operator_display"
        sub = same[same[col] == group]
        curve = sub.groupby("dbd")["price_usd"].median().sort_index()
        if curve.empty:
            continue
        early_candidates = curve.index[(curve.index >= early_dbd - tolerance) &
                                       (curve.index <= early_dbd + tolerance)]
        late_candidates = curve.index[(curve.index >= late_dbd - tolerance) &
                                      (curve.index <= late_dbd + tolerance)]
        if early_candidates.empty or late_candidates.empty:
            continue
        early_price = curve.loc[early_candidates].median()
        late_price = curve.loc[late_candidates].median()
        savings = late_price - early_price
        rows.append({"group": group, "early_price": round(early_price, 2),
                     "late_price": round(late_price, 2),
                     "savings_usd": round(savings, 2),
                     "savings_pct": round(100 * savings / late_price, 1) if late_price else None})

    table = pd.DataFrame(rows).sort_values("savings_usd", ascending=True)

    style.apply_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [style.STATUS["good"] if v > 0 else style.STATUS["critical"]
             for v in table["savings_usd"]]
    ax.barh(table["group"], table["savings_usd"], color=colors)
    ax.axvline(0, color=style.BASELINE, linewidth=1)
    ax.set_xlabel(f"$ saved booking ~{early_dbd}d out vs. ~{late_dbd}d out")
    style.finish(fig, out_path,
                title="Booking ahead pays off - but not evenly across operators",
                subtitle=f"Median fare near {early_dbd} DBD vs. near {late_dbd} DBD "
                         f"(nearest available within +/-{tolerance} days)")
    return {"table": table.to_dict(orient="records"), "early_dbd": early_dbd, "late_dbd": late_dbd}


def fare_distribution_by_group(df: pd.DataFrame, out_path: Path,
                               dbd_lo: int = 5, dbd_hi: int = 9) -> dict:
    """Full fare spread (min/quartiles/median/outliers), not just the
    median - two groups can have the same median and wildly different
    spread, which a line chart alone would hide.
    """
    same = same_source_subset(df)
    band = same[(same["dbd"] >= dbd_lo) & (same["dbd"] <= dbd_hi)]

    data, labels, colors = [], [], []
    for group in GROUPS:
        col = "service_name" if group in style.SERVICE_COLOR else "operator_display"
        vals = band.loc[band[col] == group, "price_usd"].dropna()
        if len(vals) < 5:
            continue
        data.append(vals.values)
        labels.append(group)
        colors.append(_group_color(group))

    style.apply_style()
    fig, ax = plt.subplots(figsize=(9, 5.5))
    bp = ax.boxplot(data, vert=False, patch_artist=True, labels=labels,
                    widths=0.6, showfliers=True,
                    flierprops={"markersize": 3, "alpha": 0.4})
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.85)
    for median_line in bp["medians"]:
        median_line.set_color(style.INK_PRIMARY)
        median_line.set_linewidth(1.5)
    ax.set_xlabel("Fare ($)")
    style.finish(fig, out_path,
                title="Fare spread, not just the median",
                subtitle=f"All observations at {dbd_lo}-{dbd_hi} days before departure, "
                         f"same-source fares only")
    return {"groups_plotted": labels}


def flixbus_sold_out_by_dbd(out_path: Path) -> dict | None:
    """The one real demand/availability signal in this project (see
    elasticity.py's docstring) - how far out do price-sensitive bus seats
    actually sell out. Returns None (not an error) if there isn't enough
    sold_out data yet to plot, same convention as overlap.py.
    """
    raw = load_raw()
    flix = raw[raw["source"] == "global.api.flixbus.com"]
    if flix.empty or "sold_out" not in flix["status"].unique():
        return None

    by_dbd = flix.groupby("dbd")["status"].apply(
        lambda s: 100 * (s == "sold_out").sum() / len(s)).sort_index()
    by_dbd = by_dbd[by_dbd.index <= 28]
    if by_dbd.empty:
        return None

    style.apply_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(by_dbd.index, by_dbd.values, color=style.CAT["orange"], width=0.8)
    ax.invert_xaxis()
    ax.set_xlabel("Days before departure")
    ax.set_ylabel("% of observed departures sold out")
    style.finish(fig, out_path,
                title="How early do price-sensitive bus seats actually sell out?",
                subtitle="FlixBus + Greyhound - the only real availability "
                         "signal collected anywhere in this project")
    return {"peak_sold_out_pct": round(by_dbd.max(), 1),
           "peak_sold_out_dbd": int(by_dbd.idxmax())}


def collection_coverage_by_source(out_path: Path) -> dict:
    """Rows collected per day, per source - a transparency/QA chart on the
    collection process itself, not a pricing finding. Shows the project's
    actual scale and whether any source has gone quiet.
    """
    raw = load_raw()
    pivot = (raw.groupby(["snapshot_date", "source"])
            .size().unstack(fill_value=0).sort_index())

    style.apply_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = None
    source_colors = {"global.api.flixbus.com": style.CAT["aqua"],
                     "us.megabus.com": style.CAT["violet"],
                     "api.wanderu.com": style.CAT["blue"]}
    for src in pivot.columns:
        color = source_colors.get(src, style.INK_MUTED)
        ax.bar(pivot.index, pivot[src], bottom=bottom, color=color,
              width=0.8, label=src)
        bottom = pivot[src] if bottom is None else bottom + pivot[src]

    ax.set_ylabel("Rows collected")
    ax.legend(fontsize=9, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    fig.autofmt_xdate()
    style.finish(fig, out_path,
                title="Collection scale and reliability, by source",
                subtitle=f"{len(pivot)} snapshot days, {int(pivot.values.sum()):,} total rows")
    return {"snapshot_days": len(pivot), "total_rows": int(pivot.values.sum()),
           "sources": list(pivot.columns)}
