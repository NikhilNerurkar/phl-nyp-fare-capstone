"""Real (cost-of-living-adjusted) household income, Philadelphia vs NYC.

Nominal income alone overstates NYC's advantage and understates
Philadelphia's - a $75k household income does not go nearly as far in New
York as in Philadelphia. This answers "whose households actually have more
spending power," not just "whose households earn more" - directly useful
context for whether a given fare is more or less of a stretch in each
metro, on top of the raw-income affordability lens in census.py.

Real sourced inputs, nothing invented:
  - Median household income: Census ACS 5-year estimates, table B19013.
    Confirmed live to work at the county level - this is in fact the
    table that first confirmed our Census API key/endpoint were working
    correctly, back when B19081 was turning up 404s at county level (see
    census.py's docstring for that history).
  - Total households per county: Census ACS 5-year estimates, table
    B19001, variable B19001_001E (the "total" line census.py already
    pulls for the bracket breakdown but drops before use there).
  - Regional Price Parity (cost-of-living index, national average = 100):
    U.S. Bureau of Economic Analysis, "Regional Price Parities by State
    and Metro Area," all-items index, 2023 vintage (matches the ACS 2023
    5-year vintage used throughout this project). Checked live via FRED
    on 2026-11-25:
      Philadelphia-Camden-Wilmington, PA-NJ-DE-MD (MSA): 102.363
      New York-Newark-Jersey City, NY-NJ-PA (MSA):       112.645
    https://fred.stlouisfed.org/series/RPPALL37980
    https://fred.stlouisfed.org/series/RPPALL35620

New York City itself is five counties (boroughs); the Census Bureau does
not publish one "NYC" median household income. We approximate it as a
household-count-weighted average of the five boroughs' medians - labeled
clearly as an approximation below, never presented as a single Census
figure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import matplotlib.pyplot as plt

from . import style
from .census import BASE, GEOGRAPHIES, _api_key

MEDIAN_INCOME_VAR = "B19013_001E"
TOTAL_HOUSEHOLDS_VAR = "B19001_001E"

# SOURCED: BEA Regional Price Parities, all items, 2023 vintage (see
# docstring above for the exact FRED series and fetch date). 100 = the
# US national average cost level; above/below that is relatively more/
# less expensive than average.
REGIONAL_PRICE_PARITY = {
    "Philadelphia": 102.363,
    "New York City": 112.645,
}
RPP_SOURCE = ("BEA Regional Price Parities, all items, 2023 vintage "
             "(FRED series RPPALL37980, RPPALL35620, fetched 2026-11-25)")


def _fetch_county_income(state_fips: str, county_fips: str) -> dict[str, Any] | None:
    key = _api_key()
    if not key:
        return None
    try:
        r = httpx.get(BASE, params={
            "get": f"NAME,{MEDIAN_INCOME_VAR},{TOTAL_HOUSEHOLDS_VAR}",
            "for": f"county:{county_fips}", "in": f"state:{state_fips}",
            "key": key,
        }, timeout=20, follow_redirects=True)
        r.raise_for_status()
        header, values = r.json()
        row = dict(zip(header, values))
        median = row.get(MEDIAN_INCOME_VAR)
        households = row.get(TOTAL_HOUSEHOLDS_VAR)
        if median is None or int(median) < 0:  # Census uses negative codes for missing
            return None
        return {"name": row.get("NAME"), "median_income": float(median),
               "households": float(households) if households else None}
    except Exception:
        return None


def real_spending_power() -> dict[str, Any] | None:
    """Nominal and cost-of-living-adjusted median household income, per metro.

    Returns None (not an error) if no Census API key is configured, same
    convention as census.fetch_income_brackets().
    """
    if not _api_key():
        return None

    by_metro: dict[str, list[dict]] = {}
    for metro, counties in GEOGRAPHIES.items():
        rows = []
        for state_fips, county_fips in counties:
            row = _fetch_county_income(state_fips, county_fips)
            if row:
                rows.append(row)
        if rows:
            by_metro[metro] = rows

    if "Philadelphia" not in by_metro or "New York City" not in by_metro:
        return None

    result: dict[str, Any] = {"counties": by_metro, "rpp_source": RPP_SOURCE}

    # Philadelphia is a single county - no weighting needed.
    phl = by_metro["Philadelphia"][0]
    nominal = {"Philadelphia": phl["median_income"]}

    # NYC is five counties - weight each borough's median by its household
    # count. This is an approximation of a city-wide figure the Census
    # Bureau does not itself publish, and is labeled as such throughout.
    nyc_rows = by_metro["New York City"]
    total_hh = sum(r["households"] or 0 for r in nyc_rows)
    nominal["New York City"] = (
        sum(r["median_income"] * (r["households"] or 0) for r in nyc_rows) / total_hh
        if total_hh else None)
    result["nyc_is_household_weighted_approximation"] = True

    result["nominal_median_income"] = {k: round(v, 0) if v else None
                                       for k, v in nominal.items()}
    result["real_median_income"] = {
        metro: round(income * 100 / REGIONAL_PRICE_PARITY[metro], 0)
        for metro, income in nominal.items() if income is not None}
    result["regional_price_parity"] = REGIONAL_PRICE_PARITY

    phl_real, nyc_real = result["real_median_income"].get("Philadelphia"), \
                         result["real_median_income"].get("New York City")
    if phl_real and nyc_real:
        result["nyc_real_premium_pct"] = round(100 * (nyc_real - phl_real) / phl_real, 1)
        phl_nom, nyc_nom = nominal["Philadelphia"], nominal["New York City"]
        result["nyc_nominal_premium_pct"] = round(100 * (nyc_nom - phl_nom) / phl_nom, 1)
    return result


def plot_spending_power(result: dict, out_path: Path) -> dict:
    """Grouped bars: nominal vs cost-of-living-adjusted ('real') median
    household income, side by side per metro. One axis (dollars) -
    adjustment is a second bar, never a second y-scale.
    """
    metros = ["Philadelphia", "New York City"]
    nominal = [result["nominal_median_income"][m] for m in metros]
    real = [result["real_median_income"][m] for m in metros]

    style.apply_style()
    fig, ax = plt.subplots(figsize=(7.5, 5))
    x = range(len(metros))
    width = 0.32
    ax.bar([i - width / 2 for i in x], nominal, width=width,
          color=style.INK_MUTED, label="Nominal median household income")
    ax.bar([i + width / 2 for i in x], real, width=width,
          color=style.CAT["blue"], label="Cost-of-living-adjusted ('real') income")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metros)
    ax.set_ylabel("Median household income ($)")
    ax.legend(fontsize=9)

    for i, (n, r) in enumerate(zip(nominal, real)):
        ax.text(i - width / 2, n + 1500, f"${n:,.0f}", ha="center", fontsize=9)
        ax.text(i + width / 2, r + 1500, f"${r:,.0f}", ha="center", fontsize=9)

    style.finish(fig, out_path,
                title="NYC earns more, but Philadelphia's dollar goes further",
                subtitle=f"{RPP_SOURCE} - NYC figure is a household-weighted "
                         f"approximation across its 5 boroughs")
    return {"metros_plotted": metros}
