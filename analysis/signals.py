"""Core question 4: does one mode lead or follow the other's price changes?

Methodology note (important - read before trusting the number):

We cannot just track "the PHL-NYP fare" day over day, because the set of
travel dates in the window shrinks every day as dates pass (today's run has
fewer long-lead dates than last week's), which would make median fares look
like they're trending on their own even if nothing actually repriced. The
fix: fix a DBD band (default 5-9 days out) and, for each snapshot day,
take the median fare among rows that fall in that band. That holds "how
far out is this booking" constant and isolates real day-to-day repricing.

Then: day-over-day % change in that series, per operator, cross-correlated
at a few lags. A real lead/follower signal would show up as a consistent
nonzero-lag correlation peak that repeats - which needs more than the ~2-3
weeks of snapshots we have today. The framing doc is explicit about this:
"name a leader only if it repeats across dates." With few snapshot days,
the honest read today is "no stable signal yet, re-run as more data lands" -
and the code is written so that re-running it later is the only thing that
changes.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from . import style
from .clean import same_source_subset

MIN_DAYS_FOR_SIGNAL = 10  # below this, cross-correlation is noise dressed as insight


def daily_series_at_dbd_band(df: pd.DataFrame, dbd_lo: int = 5, dbd_hi: int = 9,
                             group_col: str = "operator_display") -> pd.DataFrame:
    """One row per (snapshot_date, group): median fare among rows at dbd_lo..dbd_hi."""
    same = same_source_subset(df)
    band = same[(same["dbd"] >= dbd_lo) & (same["dbd"] <= dbd_hi)]
    out = (band.groupby(["snapshot_date", group_col])["price_usd"]
           .median().reset_index())
    return out.pivot(index="snapshot_date", columns=group_col, values="price_usd")


def leader_follower(df: pd.DataFrame, out_path: Path,
                    rail_service: str = "Northeast Regional",
                    bus_benchmark: str = "Greyhound",
                    max_lag: int = 3) -> dict:
    """Cross-correlate day-over-day %-change series between one rail service
    and one bus operator, at lags -max_lag..+max_lag days.

    Positive lag k: rail's change today correlates with bus's change k days
    later (rail leads). Negative: bus leads. Reported honestly as "too few
    snapshot days" below the threshold rather than naming a winner on noise.
    """
    same = same_source_subset(df)
    rail = same[same["service_name"] == rail_service]
    bus = same[same["operator_display"] == bus_benchmark]

    rail_s = (rail[(rail["dbd"] >= 5) & (rail["dbd"] <= 9)]
              .groupby("snapshot_date")["price_usd"].median().sort_index())
    bus_s = (bus[(bus["dbd"] >= 5) & (bus["dbd"] <= 9)]
             .groupby("snapshot_date")["price_usd"].median().sort_index())

    joined = pd.concat([rail_s.rename("rail"), bus_s.rename("bus")],
                       axis=1).dropna()
    n_days = len(joined)

    result = {"rail_service": rail_service, "bus_benchmark": bus_benchmark,
              "n_snapshot_days": n_days,
              "enough_data": n_days >= MIN_DAYS_FOR_SIGNAL}

    rail_pct = joined["rail"].pct_change().dropna()
    bus_pct = joined["bus"].pct_change().dropna()
    both = pd.concat([rail_pct.rename("rail"), bus_pct.rename("bus")],
                     axis=1).dropna()

    lags = list(range(-max_lag, max_lag + 1))
    corrs = []
    for lag in lags:
        if lag >= 0:
            a, b = both["rail"].iloc[:len(both) - lag or None], \
                   both["bus"].shift(-lag).iloc[:len(both) - lag or None]
        else:
            a, b = both["rail"].shift(lag), both["bus"]
        pair = pd.concat([a, b], axis=1).dropna()
        corrs.append(pair.iloc[:, 0].corr(pair.iloc[:, 1]) if len(pair) >= 3 else float("nan"))

    style.apply_style()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    colors = [style.CAT["blue"] if not pd.isna(c) else style.GRIDLINE for c in corrs]
    ax.bar(lags, [0 if pd.isna(c) else c for c in corrs], color=colors, width=0.6)
    ax.axhline(0, color=style.BASELINE, linewidth=1)
    ax.set_xlabel(f"Lag (days) - positive means {rail_service} leads")
    ax.set_ylabel("Correlation of day-over-day % change")
    ax.set_xticks(lags)

    status_note = ("enough snapshots for a first read" if result["enough_data"]
                   else f"only {n_days} snapshot days - signal is not yet reliable, "
                        f"re-run after {MIN_DAYS_FOR_SIGNAL}+ days")
    style.finish(fig, out_path,
                title=f"{rail_service} vs {bus_benchmark}: who moves first?",
                subtitle=status_note)

    valid = {lag: c for lag, c in zip(lags, corrs) if not pd.isna(c)}
    if valid:
        best_lag = max(valid, key=lambda k: abs(valid[k]))
        result["strongest_lag"] = best_lag
        result["strongest_corr"] = round(valid[best_lag], 2)
        result["reading"] = (
            "inconclusive - too few snapshot days" if not result["enough_data"] else
            f"{rail_service} appears to lead by {best_lag}d" if best_lag > 0 else
            f"{bus_benchmark} appears to lead by {-best_lag}d" if best_lag < 0 else
            "moves together, no lead/lag")
    else:
        result["reading"] = "insufficient overlapping data"
    return result
