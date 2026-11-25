"""Turns the analysis into the thing a sponsor actually wants: a short list
of concrete pricing recommendations, not just descriptive charts.

Each recommendation follows the framing doc's own format - segment, action,
expected impact, trade-off, risk - and every number in it traces to either
our own real fare data or a cited elasticity estimate (see elasticity.py's
docstring for the sourcing). Where no sourced number exists (rail<->bus
cross-elasticity - we checked the literature and found nothing credible),
the risk is stated qualitatively rather than invented.
"""
from __future__ import annotations

import pandas as pd

from . import elasticity
from .clean import same_source_subset


def _median_fare(df: pd.DataFrame, service: str) -> float | None:
    v = df.loc[df["service_name"] == service, "price_usd"].median()
    return round(v, 2) if v == v else None


_DOW_PLURAL = {"Mon": "Mondays", "Tue": "Tuesdays", "Wed": "Wednesdays",
              "Thu": "Thursdays", "Fri": "Fridays", "Sat": "Saturdays", "Sun": "Sundays"}


def generate_recommendations(df: pd.DataFrame, findings: dict) -> list[dict]:
    recs: list[dict] = []
    same = same_source_subset(df)
    fares = {svc: _median_fare(same, svc)
            for svc in ["Acela", "Northeast Regional", "Keystone Service"]}

    heatmap = findings.get("amtrak_fare_heatmap", {})
    peak_hour, peak_dow = heatmap.get("peak_hour"), heatmap.get("peak_dow")
    gap = findings.get("fare_gap_regional_vs_greyhound", {})
    lf = findings.get("leader_follower_regional_vs_greyhound", {})

    # --- 1. Acela, highest-priced window: inelastic segment, room to raise -
    if fares.get("Acela") is not None:
        scen = elasticity.revenue_scenario_table(["Acela"], price_changes_pct=[10])
        row = scen.iloc[0]
        # Use what the heatmap actually found, not an assumption of "weekday
        # peak" - the highest-median cell in our data is whatever it is,
        # even if that turns out to be a weekend window.
        when = (f"{_DOW_PLURAL.get(peak_dow, peak_dow)} around {peak_hour}:00"
                if peak_hour is not None else "its currently highest-priced window")
        recs.append({
            "segment": "Business/premium travelers, Acela",
            "action": f"Raise Acela fares ~10% during its currently highest-priced "
                     f"window ({when}, current median ${fares['Acela']}).",
            "expected_impact": (f"Revenue change of {row['revenue_impact_pct_low']:+.1f}% to "
                                f"{row['revenue_impact_pct_high']:+.1f}%, using a sourced "
                                f"elasticity of {row['elasticity_less_elastic_end']} to "
                                f"{row['elasticity_more_elastic_end']} for this segment "
                                f"(FHWA literature range, less-elastic end per CBO's "
                                f"Amtrak/business-travel finding)."),
            "trade_off": "Even at the inelastic end, some price-sensitive riders in this "
                        "window are lost - the range above already prices that in; it "
                        "is not pure upside.",
            "risk": "The CBO business-travel-is-inelastic finding is from 1970s, "
                   "pre-deregulation data. If today's Acela riders are more "
                   "price-sensitive than the 1970s Northeast Corridor business "
                   "traveler, realized impact could land outside this range.",
            "evidence": ["amtrak_fare_heatmap", "elasticity.ELASTICITY_RANGES['Acela']"],
        })

    # --- 2. Regional/Keystone: elastic segment, raising is the wrong move -
    elastic_services = [s for s in ["Northeast Regional", "Keystone Service"]
                        if fares.get(s) is not None]
    if elastic_services:
        scen = elasticity.revenue_scenario_table(elastic_services, price_changes_pct=[10])
        worst = scen.loc[scen["revenue_impact_pct_low"].idxmin()]
        recs.append({
            "segment": "Price-sensitive leisure/student riders, Regional & Keystone",
            "action": "Hold base fares flat for these services; keep relying on the "
                     "existing booking-curve ramp (cheap far out, pricier close-in) "
                     "rather than a flat across-the-board increase.",
            "expected_impact": (f"A flat +10% increase risks a revenue change as low as "
                                f"{worst['revenue_impact_pct_low']:+.1f}% "
                                f"({worst['service']}, more-elastic end of the sourced "
                                f"range at elasticity {worst['elasticity_more_elastic_end']}) "
                                f"- i.e. plausibly a net revenue LOSS, not a gain."),
            "trade_off": "Leaving fares flat forgoes the upside captured in recommendation "
                        "#1 for Acela - this segment just doesn't support the same move.",
            "risk": "No sourced cross-elasticity (rail<->bus substitution) estimate exists "
                   "in the literature we could find - this segment's documented "
                   "price-elastic demand (-0.80 to -1.20) is itself the reason to expect "
                   "real share loss to bus at a higher price point, even without a "
                   "precise substitution number.",
            "evidence": ["elasticity.ELASTICITY_RANGES", "fare_gap_regional_vs_greyhound"],
        })

    # --- 3. Fare-gap-driven: protect the close-in window from bus share loss
    if gap.get("median_gap_usd") is not None:
        recs.append({
            "segment": "Regional riders choosing between rail and bus close to departure",
            "action": (f"Keep the Regional-vs-Greyhound fare gap from widening much past "
                      f"its current median of ${gap['median_gap_usd']} in the final "
                      f"booking window, rather than letting near-departure surge pricing "
                      f"run unchecked."),
            "expected_impact": (f"Rail is currently cheaper than Greyhound on "
                                f"{gap.get('rail_cheaper_share_of_window', 'N/A')}% of the "
                                f"DBD window observed - that's the share of the window "
                                f"where this constraint doesn't even bind today."),
            "trade_off": "Capping the gap limits revenue otherwise available from "
                        "inelastic last-minute business travelers who would tolerate "
                        "a wider gap.",
            "risk": "This is a qualitative risk, not a quantified one: we have no "
                   "sourced cross-elasticity number for rail<->bus substitution (checked "
                   "the literature, found nothing usable - see elasticity.py), so the "
                   "size of actual diversion if the gap widens is unknown, only its "
                   "direction.",
            "evidence": ["fare_gap_regional_vs_greyhound"],
        })

    # --- 4. Census-driven: affordability-aware fare-bucket protection ------
    census_summary = findings.get("census_affordability_summary")
    if census_summary:
        worst_key = max(census_summary, key=census_summary.get)
        recs.append({
            "segment": f"Lower-income households - worst case observed: {worst_key}",
            "action": "Preserve a meaningfully-sized low-fare (Saver-equivalent) booking "
                     "bucket on Regional/Keystone rather than letting dynamic pricing "
                     "fill it in first; this is the inventory lever, not a price-level one.",
            "expected_impact": (f"{census_summary[worst_key]}% of households in this "
                                f"metro/service combination are in an income bracket "
                                f"where a round trip already exceeds 2% of monthly "
                                f"income (ACS 5-year estimates, table B19001)."),
            "trade_off": "Directly in tension with recommendation #1: protecting "
                        "low-fare inventory caps the revenue upside available from "
                        "willing-to-pay business travelers in the same departure.",
            "risk": "This is an affordability LENS (share of households in a bracket "
                   "where cost exceeds a threshold), not a demand model - it says "
                   "nothing about how many of those households actually try to book "
                   "this route, which we have no data on.",
            "evidence": ["census_affordability_summary"],
        })

    # --- 5. Leader/follower: only recommend action if the signal earned it
    if lf:
        if lf.get("reading", "").startswith(("Amtrak", "Northeast Regional", "Greyhound")) \
                and "appears to lead" in lf.get("reading", ""):
            recs.append({
                "segment": "Cross-operator pricing response timing",
                "action": f"Monitor and react within the observed lag window: {lf['reading']}.",
                "expected_impact": (f"Correlation {lf.get('strongest_corr')} at lag "
                                    f"{lf.get('strongest_lag')}d, p="
                                    f"{lf.get('strongest_corr_pvalue')}, confirmed to "
                                    f"repeat across both halves of the snapshot window."),
                "trade_off": "Reacting fast to a competitor's move can mean repricing "
                            "before enough of its own demand response is observed.",
                "risk": "Still a correlational signal from a few weeks of data, not a "
                       "causal one - a third factor (e.g. a shared seasonal pattern) "
                       "could produce the same correlation.",
                "evidence": ["leader_follower_regional_vs_greyhound"],
            })
        else:
            recs.append({
                "segment": "Cross-operator pricing response timing",
                "action": "No action yet - do not assume Amtrak needs to react to "
                         "Greyhound's pricing moves (or vice versa) on any particular "
                         "lag.",
                "expected_impact": "N/A - avoiding a false-confidence recommendation is "
                                   "itself the point here.",
                "trade_off": "None - this is explicitly the option that costs nothing "
                            "and claims nothing unsupported.",
                "risk": f"Reading from the data today: \"{lf.get('reading')}\". Re-run "
                       f"this analysis as more snapshot days accumulate; the code is "
                       f"written so that is the only thing that changes.",
                "evidence": ["leader_follower_regional_vs_greyhound"],
            })

    return recs
