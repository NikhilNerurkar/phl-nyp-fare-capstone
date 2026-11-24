"""The WAS-NYC overlap question, deferred per your instruction but written
to need zero changes once that data exists.

Mentor's framing: PHL-NYP and WAS-NYP share physical seats on the same
through-train, so a PHL-NYP fare should move with WAS-NYP demand on that
same departure, even though WAS-PHL (no shared inventory) should not.
We cannot see seat counts, so the proxy is: do the two markets' fares on
the SAME vehicle_number/travel_date move together, aggregated by
day-of-week/time-of-day to cut noise (the mentor's own suggestion)?

This only works if a second source is ever added to the same `fares` table
with origin_code/dest_code = WAS/NYP (or NYP/WAS). The join below asks the
data "do both markets exist for this train today?" rather than assuming
they do. Right now the answer is no for every row, so this module runs,
finds nothing, and says so - it does not need to be touched when that
changes, only re-run.
"""
from __future__ import annotations

import pandas as pd

from .clean import load_raw


def overlap_readiness_check() -> dict:
    """Is WAS-NYP data present yet? If not, say exactly what's missing."""
    df = load_raw()
    pairs = set(zip(df["origin_code"], df["dest_code"]))
    has_phl_nyp = ("PHL", "NYP") in pairs or ("NYP", "PHL") in pairs
    has_was_nyp = ("WAS", "NYP") in pairs or ("NYP", "WAS") in pairs
    return {
        "route_pairs_in_data": sorted({f"{o}-{d}" for o, d in pairs}),
        "has_phl_nyp": has_phl_nyp,
        "has_was_nyp": has_was_nyp,
        "ready_for_overlap_analysis": has_phl_nyp and has_was_nyp,
        "next_step": (
            "none - run overlap_fare_comovement() below" if has_was_nyp else
            "add a WAS<->NYP source writing into the same fares table "
            "(same train numbers, same vehicle_number field) - no code "
            "change needed here once that exists"
        ),
    }


def overlap_fare_comovement(dow_bucket: bool = True) -> pd.DataFrame | None:
    """Self-join fares to itself on (vehicle_number, travel_date) across
    different origin/dest, to compare PHL-NYP and WAS-NYP fares on the
    SAME physical train.

    Returns None (not an error) if WAS-NYP isn't in the data yet - this is
    the designed no-op state, not a failure.
    """
    df = load_raw()
    df = df[(df["status"] == "ok") & df["price_usd"].notna()
           & df["vehicle_number"].notna()]
    df = df[df["mode"] == "rail"]

    phl_nyp = df[df["origin_code"].isin(["PHL", "NYP"]) &
                df["dest_code"].isin(["PHL", "NYP"])]
    was_nyp = df[df["origin_code"].isin(["WAS", "NYP"]) &
                df["dest_code"].isin(["WAS", "NYP"]) &
                (df["origin_code"] == "WAS")]

    if was_nyp.empty:
        return None  # designed no-op: see overlap_readiness_check()

    key = ["vehicle_number", "travel_date", "snapshot_date"]
    merged = phl_nyp.merge(was_nyp, on=key, suffixes=("_phlnyp", "_wasnyp"))
    if merged.empty:
        return None

    group_cols = key[:1]
    if dow_bucket:
        merged["dow_bucket"] = pd.to_datetime(merged["travel_date"]).dt.weekday
        group_cols = ["dow_bucket"]

    return (merged.groupby(group_cols)
           .apply(lambda g: g["price_usd_phlnyp"].corr(g["price_usd_wasnyp"]))
           .rename("fare_comovement_corr").reset_index())
