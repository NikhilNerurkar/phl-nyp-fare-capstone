"""Revenue sensitivity under sourced price elasticity (sponsor-requested depth).

Why this isn't "measured elasticity" from our own data: that would need a
real demand/quantity signal, and we checked - we don't have one. Wanderu's
`seats_remaining` field is populated on 225k+ rows but every single value is
the literal integer 1, a placeholder, not a real seat count (see
scraper/sources/wanderu.py:265 and its own comment at line 21-22 admitting
Amtrak's real fare buckets aren't exposed by this source). FlixBus's
`sold_out` status is the only real quantity signal anywhere in this
project, and it's bus-only - no help for the Amtrak pricing question this
analysis is actually for.

So instead of fabricating a quantity series, this module applies SOURCED
price elasticity estimates from the transportation economics literature to
our own real fare data, and reports results as a RANGE under parameter
uncertainty - never a single confident number. That range-under-uncertainty
framing is standard practice, not a workaround.

Sources (both checked live, 2026-11-25):
  - FHWA, "Analysis of Automobile Travel Demand Elasticities With Respect
    To Travel Cost" (literature review table): intercity rail own-price
    elasticity reported in the range -0.32 to -1.20.
    https://www.fhwa.dot.gov/policyinformation/pubs/hpl-15-014/TCElasticities.pdf
  - CBO, "The Past and Future of U.S. Passenger Rail Service": 1970s-era
    studies of Amtrak found demand highly price-elastic EXCEPT for
    business travel in the Northeast corridor - our exact route.
    https://cbo.gov/sites/default/files/cbofiles/ftpdocs/45xx/doc4571/09-26-passengerrail.pdf
    Used only as a qualitative basis for giving Acela (business-heavy) the
    less-elastic end of the FHWA range and Regional/Keystone (more
    price-sensitive, leisure-and-student-heavy) the more-elastic end - we
    are not treating the CBO finding as a separate numeric estimate, and
    we flag it as 1970s/pre-deregulation evidence, which it is.

No credible sourced cross-elasticity (rail <-> bus substitution) estimate
was found in the literature search, so that risk is described qualitatively
in analysis/recommendations.py, never assigned a fabricated number.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd

from . import style

SOURCES = {
    "fhwa_elasticity_range": (
        "FHWA, Analysis of Automobile Travel Demand Elasticities With "
        "Respect To Travel Cost (literature review): intercity rail "
        "own-price elasticity -0.32 to -1.20."
    ),
    "cbo_amtrak_business_travel": (
        "CBO, The Past and Future of U.S. Passenger Rail Service: "
        "1970s Amtrak demand studies found demand elastic except for "
        "business travel in the Northeast corridor (dated, "
        "pre-deregulation evidence - used qualitatively only)."
    ),
}

# (less-elastic end, more-elastic end) - both ends are real points within
# the cited FHWA range; which end we assign to which service is the only
# judgment call, grounded in the CBO finding above.
ELASTICITY_RANGES = {
    "Acela": (-0.50, -0.32),
    "Northeast Regional": (-1.20, -0.80),
    "Keystone Service": (-1.20, -0.80),
}
DEFAULT_RANGE = (-1.20, -0.32)  # full FHWA range, for anything not listed above

DEFAULT_PRICE_CHANGES_PCT = (-10, -5, 5, 10, 15)


def elasticity_range_for(service: str) -> tuple[float, float]:
    return ELASTICITY_RANGES.get(service, DEFAULT_RANGE)


def revenue_impact_pct(price_change_pct: float, elasticity: float) -> float:
    """% revenue change from a % price change under constant elasticity.

    Derivation: Revenue = Price x Quantity. If price moves by dp (fraction)
    and elasticity e means quantity moves by e*dp, new revenue relative to
    old is (1+dp)*(1+e*dp). This only needs the % changes, not an actual
    baseline quantity - which is exactly why it works without the demand
    data we don't have.
    """
    dp = price_change_pct / 100
    dq = elasticity * dp
    return ((1 + dp) * (1 + dq) - 1) * 100


def revenue_scenario_table(services: Iterable[str],
                           price_changes_pct: Iterable[float] = DEFAULT_PRICE_CHANGES_PCT,
                           current_median_fares: dict[str, float] | None = None) -> pd.DataFrame:
    """One row per (service, price-change scenario), with the revenue-impact
    range implied by that service's sourced elasticity range.

    `current_median_fares`, if given (pass real medians computed elsewhere
    in this run - never a separate guess), is attached for context only; it
    plays no role in the revenue-impact math, which is scale-invariant.
    """
    rows = []
    for svc in services:
        lo_e, hi_e = elasticity_range_for(svc)
        for pct in price_changes_pct:
            impacts = sorted([revenue_impact_pct(pct, lo_e), revenue_impact_pct(pct, hi_e)])
            rows.append({
                "service": svc,
                "price_change_pct": pct,
                "elasticity_less_elastic_end": lo_e,
                "elasticity_more_elastic_end": hi_e,
                "revenue_impact_pct_low": round(impacts[0], 2),
                "revenue_impact_pct_high": round(impacts[1], 2),
                "current_median_fare_usd": (
                    round(current_median_fares[svc], 2)
                    if current_median_fares and svc in current_median_fares
                    and current_median_fares[svc] == current_median_fares[svc]
                    else None),
            })
    return pd.DataFrame(rows)


def plot_revenue_scenarios(table: pd.DataFrame, out_path: Path) -> dict:
    """Floating range bars: for each service, the revenue-impact range at
    each hypothetical price change. The range itself (not a point) is the
    finding - collapsing it to one number would misrepresent what sourced,
    uncertain elasticity estimates can actually tell us.
    """
    services = list(table["service"].unique())
    changes = sorted(table["price_change_pct"].unique())
    n = len(services)
    width = 0.8 / n

    style.apply_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, svc in enumerate(services):
        sub = table[table["service"] == svc].set_index("price_change_pct").reindex(changes)
        x = [c + (i - (n - 1) / 2) * width for c in range(len(changes))]
        color = style.SERVICE_COLOR.get(svc, style.CAT["blue"])
        heights = (sub["revenue_impact_pct_high"] - sub["revenue_impact_pct_low"]).to_numpy()
        ax.bar(x, heights, bottom=sub["revenue_impact_pct_low"].to_numpy(),
               width=width * 0.9, color=color, label=svc)

    ax.axhline(0, color=style.BASELINE, linewidth=1)
    ax.set_xticks(range(len(changes)))
    ax.set_xticklabels([f"{c:+d}%" for c in changes])
    ax.set_xlabel("Hypothetical fare change")
    ax.set_ylabel("Revenue impact (%), range across sourced elasticity estimates")
    ax.legend(fontsize=9)
    style.finish(fig, out_path,
                title="Revenue sensitivity to fare changes (sourced elasticity ranges)",
                subtitle="FHWA literature range -0.32 to -1.20; Acela assigned the "
                         "less-elastic end per CBO's business-travel finding")
    return {"services_plotted": services, "price_changes_pct": [int(c) for c in changes]}
