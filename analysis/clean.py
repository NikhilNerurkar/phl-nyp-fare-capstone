"""Load and clean the fare dataset.

This is the one place every analysis module gets its data from. It reads
whatever is in data/exports/fares_latest.parquet right now - there is no
hardcoded date range or row count anywhere here, so this keeps working
unchanged as more days accumulate.

Filters applied, and why, are documented inline rather than silently baked
in, because every one of them was a real finding during collection
(see docs/DATA_DICTIONARY.md "Known comparability caveats").
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "exports" / "fares_latest.parquet"

# A genuine PHL<->NYP city-center trip runs roughly 65-200 minutes on bus or
# rail. Found during collection: Wanderu's city-to-city search also returns
# airport vans (JFK Terminal 4 -> Center City, 228 min) and suburban
# park-and-ride stops that are not substitutes for the 30th St <-> Penn
# Station trip this project is about. Duration is the cleanest signal to
# drop them - see docs/DATA_DICTIONARY.md.
MAX_SURFACE_DURATION_MIN = 210

# Operators seen so rarely, or so narrowly mapped, that they are noise in any
# chart with a legend. Folded into "Other" rather than dropped, so their
# price observations still count in totals.
MINOR_OPERATOR_FOLD_THRESHOLD = 300  # rows, across the whole dataset


def load_raw() -> pd.DataFrame:
    """Every row, unfiltered, exactly as collected. Use for coverage/QA."""
    if not PARQUET.exists():
        raise FileNotFoundError(
            f"{PARQUET} not found - run `python run_daily.py` at least once first.")
    df = pd.read_parquet(PARQUET)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df["travel_date"] = pd.to_datetime(df["travel_date"])
    return df


def load_clean(min_priced_status: str = "ok") -> pd.DataFrame:
    """The dataset every analysis chart should use unless it needs raw rows.

    Filters, applied in order:
      1. status == 'ok'            - a real price was observed (not sold_out/
                                      no_service/error). Those statuses are
                                      real signals, kept in load_raw(), just
                                      not mixed into price statistics.
      2. duration <= 210 min        - drops the airport-van / park-and-ride
                                      contamination documented above. Rows
                                      with duration_min missing are kept
                                      (mostly Amtrak, which doesn't carry one
                                      from every source) rather than dropped.
      3. price_usd not null         - belt-and-suspenders on (1).
    """
    df = load_raw()
    df = df[df["status"] == min_priced_status].copy()
    too_long = df["duration_min"].notna() & (
        df["duration_min"] > MAX_SURFACE_DURATION_MIN)
    df = df[~too_long]
    df = df[df["price_usd"].notna()]
    df["operator_display"] = _fold_minor_operators(df)
    return df


def _fold_minor_operators(df: pd.DataFrame) -> pd.Series:
    counts = df["operator"].value_counts()
    keep = set(counts[counts >= MINOR_OPERATOR_FOLD_THRESHOLD].index)
    return df["operator"].where(df["operator"].isin(keep), "Other")


def same_source_subset(df: pd.DataFrame, source: str = "api.wanderu.com") -> pd.DataFrame:
    """Rows from one source only.

    Measured finding: the same bus fare runs ~19-24% higher on Wanderu than
    on the operator's own API, on the same day. Comparing Amtrak (Wanderu-only
    today) against bus-from-its-own-API would make rail look relatively more
    expensive than it is. Any cross-mode $ comparison should use this, not
    the full mixed-source table.
    """
    return df[df["source"] == source].copy()


def coverage_summary(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per snapshot day: how much data landed. Flags thin/missing days."""
    raw = load_raw() if df is None else df
    g = raw.groupby("snapshot_date").agg(
        rows=("observation_id", "count"),
        travel_dates=("travel_date", "nunique"),
        priced=("price_usd", lambda s: s.notna().sum()),
    ).reset_index()
    median_rows = g["rows"].median()
    g["thin_day"] = g["rows"] < (0.5 * median_rows)
    return g
