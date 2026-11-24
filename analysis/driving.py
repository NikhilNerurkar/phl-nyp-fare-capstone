"""Modeled driving / rental cost for PHL<->NYP.

Per our earlier scoping call (live rental scraping was too high-risk to
build before the deadline - see docs/STATUS.md), this is a documented
formula, not a scrape. Every input is labeled SOURCED (a real, cited
figure) or ASSUMPTION (a reasonable stand-in you can override) in
config.yaml - never presented as an observed fare like the rest of the
dataset. Charts and tables built from this module say "modeled" wherever
they're shown, matching the STATUS_MODELED convention already used in
scraper/models.py.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _assumptions() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    return cfg["driving_assumptions"]


def driving_cost_one_way(round_trip: bool = False) -> dict:
    """Fuel+wear (via IRS mileage rate) + tolls. No rental, no parking -
    this is "driving your own car," the direct substitute for a rail/bus
    ticket, one-way unless round_trip=True.
    """
    a = _assumptions()
    miles = a["distance_miles_one_way"] * (2 if round_trip else 1)
    tolls = a["toll_one_way_usd"] * (2 if round_trip else 1)
    fuel_and_wear = miles * a["irs_mileage_rate_usd"]
    return {
        "miles": miles, "fuel_and_wear_usd": round(fuel_and_wear, 2),
        "tolls_usd": round(tolls, 2),
        "total_usd": round(fuel_and_wear + tolls, 2),
        "basis": "IRS mileage rate + NJ Turnpike toll (see config.yaml for sources)",
    }


def rental_trip_cost(days: int = 1, group_size: int = 1,
                     round_trip: bool = True) -> dict:
    """Full rental scenario: rental car + fuel/wear + tolls + NYC parking,
    split across a group. This is the Student/Family comparison point -
    a rail ticket is per person; a rental is one cost split N ways.
    """
    a = _assumptions()
    drive = driving_cost_one_way(round_trip=round_trip)
    rental = a["rental_car_per_day_usd"] * days
    parking = a["parking_per_day_usd"] * days
    total = drive["total_usd"] + rental + parking
    return {
        "days": days, "group_size": group_size,
        "rental_usd": round(rental, 2), "parking_usd": round(parking, 2),
        "driving_usd": drive["total_usd"],
        "total_usd": round(total, 2),
        "per_person_usd": round(total / max(group_size, 1), 2),
        "status": "modeled",  # never conflate with an observed fare
    }


def rental_vs_rail_table(rail_fares: dict[str, float], group_sizes=(1, 2, 4),
                         days: int = 2) -> "pandas.DataFrame":
    import pandas as pd
    rows = []
    for gs in group_sizes:
        rc = rental_trip_cost(days=days, group_size=gs)
        for service, fare in rail_fares.items():
            rail_group_cost = fare * 2 * gs  # round trip, per person, x group
            rows.append({
                "group_size": gs, "rail_service": service,
                "rail_total_for_group": round(rail_group_cost, 2),
                "rail_per_person": round(fare * 2, 2),
                "rental_total_for_group": rc["total_usd"],
                "rental_per_person": rc["per_person_usd"],
                "rental_cheaper": rc["per_person_usd"] < fare * 2,
            })
    return pd.DataFrame(rows)
