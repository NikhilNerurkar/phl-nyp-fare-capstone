"""Core question 5 (sponsor-suggested): income-based affordability framing.

As of May 2026 the Census Data API requires a free key for every request
(api.census.gov/data/key_signup.html - instant signup, arrives by email).
Before that, this module tried QuickFacts as a keyless fallback; QuickFacts
returns 403 to automated requests. Per this project's own rule (nothing is
invented - see docs/DATA_DICTIONARY.md), this module returns a clear
"not configured" status rather than a plausible-looking number no one can
verify, if no key is set.

Table choice: B19081 (mean income by quintile) looked like the natural
table for this, but it is NOT published at the county level - only for
states and the largest metro areas (confirmed live: every county-level
query 404s even though the table exists in Census's metadata). B19001
(households by 16 income bracket) IS published at county level and is
what this module actually uses. We report real household counts per
bracket rather than reconstructing quintiles from them, because inventing
a within-quintile average would be exactly the kind of fabricated number
this project has avoided everywhere else.

To activate: get a free key, then either
    set CENSUS_API_KEY=<key>          (environment variable), or
    add `census_api_key: <key>` to config.yaml
No other code changes needed - report.py already calls this module and
will pick up real numbers the next time it runs.

What this model is, and is not: an AFFORDABILITY LENS, not a fitted demand
curve. We have no real booking/elasticity data (a documented limitation of
this whole project). It answers "what share of Philadelphia/NYC households
fall in an income bracket where this fare costs more than X% of a month's
income" - a defensible, bounded claim - not "how many more tickets Amtrak
would sell at this price."
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import matplotlib.pyplot as plt
import yaml

from . import style

ROOT = Path(__file__).resolve().parent.parent
ACS_YEAR = 2023  # most recent 5-year ACS vintage at time of writing
BASE = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
TABLE = "B19001"  # households by income bracket - confirmed county-level

# (state FIPS, county FIPS) - NYC is five counties (boroughs), summed into
# one "New York City" figure.
GEOGRAPHIES = {
    "Philadelphia": [("42", "101")],
    "New York City": [
        ("36", "005"),  # Bronx
        ("36", "047"),  # Kings (Brooklyn)
        ("36", "061"),  # New York (Manhattan)
        ("36", "081"),  # Queens
        ("36", "085"),  # Richmond (Staten Island)
    ],
}

# The bracket's lower bound, used only to order brackets and to estimate a
# bracket midpoint for the monthly-income-% calculation below. The top
# bracket ("$200,000 or more") has no real upper bound; we treat its
# midpoint as $250,000, labeled as an assumption, not a Census figure.
BRACKET_FLOOR_USD = {
    "Less than $10,000": 0, "$10,000 to $14,999": 10_000,
    "$15,000 to $19,999": 15_000, "$20,000 to $24,999": 20_000,
    "$25,000 to $29,999": 25_000, "$30,000 to $34,999": 30_000,
    "$35,000 to $39,999": 35_000, "$40,000 to $44,999": 40_000,
    "$45,000 to $49,999": 45_000, "$50,000 to $59,999": 50_000,
    "$60,000 to $74,999": 60_000, "$75,000 to $99,999": 75_000,
    "$100,000 to $124,999": 100_000, "$125,000 to $149,999": 125_000,
    "$150,000 to $199,999": 150_000, "$200,000 or more": 200_000,
}
BRACKET_MIDPOINT_USD = {  # ASSUMPTION for the open-ended top bracket only
    **{k: v + 2_500 if v < 200_000 else v for k, v in BRACKET_FLOOR_USD.items()},
    "$200,000 or more": 250_000,
}

# Compact x-axis labels for the chart only - the full Census wording stays
# in every CSV/table for traceability. The full strings ("$10,000 to
# $14,999") at 45-degree rotation read as illegible run-together text on a
# slide-sized chart; this is purely a presentation fix, not a data change.
BRACKET_SHORT_LABEL = {
    "Less than $10,000": "<$10k", "$10,000 to $14,999": "$10-15k",
    "$15,000 to $19,999": "$15-20k", "$20,000 to $24,999": "$20-25k",
    "$25,000 to $29,999": "$25-30k", "$30,000 to $34,999": "$30-35k",
    "$35,000 to $39,999": "$35-40k", "$40,000 to $44,999": "$40-45k",
    "$45,000 to $49,999": "$45-50k", "$50,000 to $59,999": "$50-60k",
    "$60,000 to $74,999": "$60-75k", "$75,000 to $99,999": "$75-100k",
    "$100,000 to $124,999": "$100-125k", "$125,000 to $149,999": "$125-150k",
    "$150,000 to $199,999": "$150-200k", "$200,000 or more": "$200k+",
}


def _api_key() -> str | None:
    if os.environ.get("CENSUS_API_KEY"):
        return os.environ["CENSUS_API_KEY"]
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return cfg.get("census_api_key") or None
    return None


def is_configured() -> bool:
    return bool(_api_key())


def _bracket_labels() -> dict[str, str]:
    """Real variable labels from Census metadata - no memorized guesses.

    Found live: `code.endswith("E")` is not enough to mean "this is an
    estimate variable" - the metadata response also lists the "NAME"
    pseudo-variable (label "Geographic Area Name"), and "NAME" itself ends
    in the letter E, so it slipped through and rendered as a fake 17th
    income bracket. Filtering on the table's own prefix instead.
    """
    try:
        r = httpx.get(f"{BASE}/groups/{TABLE}.json", timeout=15)
        r.raise_for_status()
        out = {}
        for code, v in r.json().get("variables", {}).items():
            if code.startswith(f"{TABLE}_") and code.endswith("E") \
                    and code != f"{TABLE}_001E":
                label = v.get("label", code).split("!!")[-1]
                out[code] = label
        return out
    except Exception:
        return {}


def fetch_income_brackets() -> dict[str, Any]:
    """Households per income bracket, Philadelphia vs NYC (summed boroughs).

    Returns {"configured": False, ...} with no numbers if no API key is set.
    """
    key = _api_key()
    if not key:
        return {"configured": False,
               "reason": "no CENSUS_API_KEY set - see analysis/census.py docstring",
               "data": None}

    labels = _bracket_labels()
    if not labels:
        return {"configured": True,
               "reason": "could not fetch B19001 bracket labels from Census metadata",
               "data": None}

    rows: list[dict] = []
    errors: list[str] = []
    for metro, counties in GEOGRAPHIES.items():
        for state_fips, county_fips in counties:
            try:
                r = httpx.get(BASE, params={
                    "get": f"NAME,group({TABLE})",
                    "for": f"county:{county_fips}", "in": f"state:{state_fips}",
                    "key": key,
                }, timeout=20, follow_redirects=True)
                r.raise_for_status()
                header, values = r.json()
                row = dict(zip(header, values))
                row["_metro"] = metro
                rows.append(row)
            except Exception as e:
                errors.append(f"{metro} ({state_fips}{county_fips}): {e}")

    if not rows:
        return {"configured": True, "reason": f"all requests failed: {errors}",
               "data": None}

    import pandas as pd
    df = pd.DataFrame(rows)
    bracket_cols = [c for c in df.columns if c in labels]
    tidy = df.melt(id_vars=["_metro"], value_vars=bracket_cols,
                   var_name="variable", value_name="households")
    tidy["bracket"] = tidy["variable"].map(labels)
    tidy["households"] = pd.to_numeric(tidy["households"], errors="coerce")
    # Sum the five NYC boroughs into one city-level count; Philadelphia is
    # already one county so this is a no-op for it.
    by_metro = (tidy.groupby(["_metro", "bracket"])["households"]
               .sum().reset_index())
    by_metro["bracket_floor_usd"] = by_metro["bracket"].map(BRACKET_FLOOR_USD)
    by_metro = by_metro.sort_values(["_metro", "bracket_floor_usd"])
    by_metro["pct_of_metro_households"] = (
        100 * by_metro["households"] /
        by_metro.groupby("_metro")["households"].transform("sum"))
    return {"configured": True, "reason": None, "data": by_metro,
           "errors": errors or None}


def affordability_table(income_result: dict, fares: dict[str, float],
                        monthly_income_threshold_pct: float = 2.0) -> Any:
    """For each (metro income bracket, named rail service), does a round
    trip exceed `monthly_income_threshold_pct`% of that bracket's MONTHLY
    income (using the bracket midpoint, flagged as an estimate)?

    `fares` is e.g. {"Acela": 131.0, "Northeast Regional": 75.0} - pass the
    medians computed elsewhere in this run, never a separate guess.
    """
    if not income_result.get("configured") or income_result.get("data") is None:
        return None
    import pandas as pd
    df = income_result["data"].copy()
    df["bracket_midpoint_usd"] = df["bracket"].map(BRACKET_MIDPOINT_USD)
    df["monthly_income_est"] = df["bracket_midpoint_usd"] / 12

    rows = []
    for _, r in df.iterrows():
        for service, fare in fares.items():
            round_trip = fare * 2
            pct = (100 * round_trip / r["monthly_income_est"]
                  if r["monthly_income_est"] else None)
            rows.append({
                "metro": r["_metro"], "income_bracket": r["bracket"],
                "pct_of_metro_households": round(r["pct_of_metro_households"], 2),
                "monthly_income_est": round(r["monthly_income_est"], 0),
                "service": service, "round_trip_fare": round(round_trip, 2),
                "pct_of_monthly_income": round(pct, 2) if pct else None,
                "exceeds_threshold": (pct or 0) > monthly_income_threshold_pct,
            })
    return pd.DataFrame(rows)


def plot_income_distribution(income_result: dict, out_path: Path) -> dict:
    """Share of households per income bracket, Philadelphia vs NYC.

    One chart, two series (categorical, fixed colors) - shows directly
    whether the two metros this corridor connects have different income
    profiles, before any fare-affordability claim is made on top of it.
    """
    df = income_result["data"].copy()
    order = sorted(BRACKET_FLOOR_USD, key=BRACKET_FLOOR_USD.get)
    pivot = (df.pivot(index="bracket", columns="_metro",
                      values="pct_of_metro_households")
             .reindex(order))

    style.apply_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(order))
    width = 0.38
    ax.bar([i - width / 2 for i in x], pivot["Philadelphia"], width=width,
          color=style.CAT["blue"], label="Philadelphia")
    ax.bar([i + width / 2 for i in x], pivot["New York City"], width=width,
          color=style.CAT["orange"], label="New York City")
    ax.set_xticks(list(x))
    ax.set_xticklabels([BRACKET_SHORT_LABEL[b] for b in order],
                       rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("% of households")
    ax.legend(fontsize=9)
    style.finish(fig, out_path,
                title="Household income distribution: Philadelphia vs NYC",
                subtitle="Source: ACS 5-year estimates (2023), table B19001")

    phl_under_35k = pivot["Philadelphia"].loc[
        [b for b in order if BRACKET_FLOOR_USD[b] < 35_000]].sum()
    nyc_under_35k = pivot["New York City"].loc[
        [b for b in order if BRACKET_FLOOR_USD[b] < 35_000]].sum()
    return {"phl_pct_households_under_35k": round(phl_under_35k, 1),
           "nyc_pct_households_under_35k": round(nyc_under_35k, 1)}


def affordability_summary(afford_df) -> dict:
    """One-line-per-metro-per-service rollup: what share of households in
    that metro are in a bracket where this fare exceeds the threshold -
    the number that actually belongs on a slide, not the full bracket table.
    """
    if afford_df is None or afford_df.empty:
        return {}
    out = {}
    for (metro, service), g in afford_df.groupby(["metro", "service"]):
        exceeded = g.loc[g["exceeds_threshold"], "pct_of_metro_households"].sum()
        out[f"{metro} / {service}"] = round(exceeded, 1)
    return out
