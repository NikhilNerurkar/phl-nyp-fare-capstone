"""Four personas, each a different lens over the same cleaned dataset.

Student and Family were the team's own starting point; Commuter and
Business Traveler were the sponsor mentor's additions. Framing for each
follows the mentor's own words where given (see conversation record):

  Commuter: frequent, recurring WEEKDAY travel, consistent departure times,
            sensitive to the CUMULATIVE cost of repeated trips - lower-cost
            alternatives matter if the schedule works.
  Business: higher value of time, schedule/flexibility first, often a
            short/variable booking window. Mentor was explicit this persona
            is about INTRA-modal competition (Acela vs Regional, which
            departure time, fare vs travel time) - not cross-modal.
  Student & Family: price-sensitive, group/budget scenarios, compared
            against a modeled rental car (see driving.py), split per person.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from . import style
from .clean import same_source_subset
from .driving import rental_vs_rail_table


def commuter_view(df: pd.DataFrame, out_path: Path,
                  rail_service: str = "Northeast Regional",
                  peak_hours=(7, 8, 17, 18)) -> dict:
    """Weekday, peak-hour departures: cumulative cost of 5 round trips/week,
    rail vs the cheapest bus alternative at the same hours.
    """
    same = same_source_subset(df)
    weekday_peak = same[(~same["is_weekend"]) & same["depart_hour"].isin(peak_hours)]

    rail = weekday_peak[weekday_peak["service_name"] == rail_service]
    bus = weekday_peak[weekday_peak["operator_display"].isin(
        ["Greyhound", "FlixBus", "Peter Pan", "OurBus"])]

    rail_fare = rail["price_usd"].median()
    bus_fare = bus.groupby("operator_display")["price_usd"].median()
    cheapest_bus_op = bus_fare.idxmin() if not bus_fare.empty else None
    cheapest_bus_fare = bus_fare.min() if not bus_fare.empty else None

    weekly_trips = 5 * 2  # 5 weekdays, round trip
    options = {rail_service: rail_fare}
    if cheapest_bus_op:
        options[cheapest_bus_op] = cheapest_bus_fare

    style.apply_style()
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    labels = list(options.keys())
    weekly_costs = [v * weekly_trips for v in options.values() if pd.notna(v)]
    colors = [style.SERVICE_COLOR.get(l, style.operator_color(l)) for l in labels]
    ax.bar(labels, weekly_costs, color=colors, width=0.5)
    for i, v in enumerate(weekly_costs):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=10,
                color=style.INK_PRIMARY)
    ax.set_ylabel("Cost per week ($)")
    style.finish(fig, out_path,
                title="Commuter: weekly cost of 10 weekday peak-hour trips",
                subtitle=f"Peak hours {peak_hours}, weekday departures only")

    gap = None
    if cheapest_bus_fare and rail_fare:
        gap = round(100 * (rail_fare - cheapest_bus_fare) / cheapest_bus_fare, 1)
    return {
        "rail_fare_peak_median": round(rail_fare, 2) if pd.notna(rail_fare) else None,
        "cheapest_bus_operator": cheapest_bus_op,
        "cheapest_bus_fare_median": round(cheapest_bus_fare, 2) if cheapest_bus_fare else None,
        "weekly_rail_cost": round(rail_fare * weekly_trips, 2) if pd.notna(rail_fare) else None,
        "weekly_bus_cost": round(cheapest_bus_fare * weekly_trips, 2) if cheapest_bus_fare else None,
        "rail_premium_pct": gap,
    }


def business_traveler_view(df: pd.DataFrame, out_path: Path,
                           max_dbd: int = 5) -> dict:
    """Intra-modal only, per mentor's explicit framing: Acela vs Regional
    at short booking windows (<=5 DBD by default) - fare difference vs
    time saved, expressed as $ per minute.
    """
    same = same_source_subset(df)
    # Intra-modal only, per the mentor's explicit framing: Acela vs Regional,
    # nothing else. Long-distance Amtrak services (Crescent, Pennsylvanian,
    # ...) run the same corridor segment but serve a different trip end to
    # end - plotting them here as unlabeled background noise was a real bug,
    # caught by actually looking at the chart rather than trusting the stats.
    close_in = same[(same["dbd"] <= max_dbd) & (same["mode"] == "rail") &
                    (same["service_name"].isin(["Acela", "Northeast Regional"]))]

    acela = close_in[close_in["service_name"] == "Acela"]
    regional = close_in[close_in["service_name"] == "Northeast Regional"]

    acela_fare, acela_dur = acela["price_usd"].median(), acela["duration_min"].median()
    reg_fare, reg_dur = regional["price_usd"].median(), regional["duration_min"].median()

    fare_premium = acela_fare - reg_fare if pd.notna(acela_fare) and pd.notna(reg_fare) else None
    time_saved = reg_dur - acela_dur if pd.notna(acela_dur) and pd.notna(reg_dur) else None
    usd_per_min_saved = (fare_premium / time_saved
                        if fare_premium and time_saved and time_saved > 0 else None)

    style.apply_style()
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for svc in ["Acela", "Northeast Regional"]:
        sub = close_in[close_in["service_name"] == svc]
        ax.scatter(sub["duration_min"], sub["price_usd"],
                  color=style.SERVICE_COLOR[svc], alpha=0.5, s=18, label=svc)
    ax.legend(fontsize=9)
    ax.set_xlabel("Travel time (minutes)")
    ax.set_ylabel(f"Fare ($), <= {max_dbd} days before departure")
    style.finish(fig, out_path,
                title="Business traveler: paying more to travel faster",
                subtitle=f"Acela vs Northeast Regional, close-in bookings "
                         f"(<= {max_dbd} DBD)")

    return {
        "acela_median_fare": round(acela_fare, 2) if pd.notna(acela_fare) else None,
        "regional_median_fare": round(reg_fare, 2) if pd.notna(reg_fare) else None,
        "acela_median_duration_min": round(acela_dur, 0) if pd.notna(acela_dur) else None,
        "regional_median_duration_min": round(reg_dur, 0) if pd.notna(reg_dur) else None,
        "fare_premium_usd": round(fare_premium, 2) if fare_premium else None,
        "time_saved_min": round(time_saved, 0) if time_saved else None,
        "implied_usd_per_minute_saved": round(usd_per_min_saved, 2) if usd_per_min_saved else None,
    }


def student_or_family_view(df: pd.DataFrame, out_path: Path,
                           persona: str = "Student", group_size: int = 2,
                           days: int = 2) -> dict:
    """Price-sensitive, group travel: modeled rental cost per person vs the
    cheapest rail/bus fare per person, for a weekend trip.

    Student defaults to a small group (2) sharing a rental; Family to a
    larger one (4) - override group_size to match your actual persona def.
    """
    same = same_source_subset(df)
    weekend = same[same["is_weekend"]]

    fares = {}
    for svc in ["Acela", "Northeast Regional", "Keystone Service"]:
        med = weekend.loc[weekend["service_name"] == svc, "price_usd"].median()
        if pd.notna(med):
            fares[svc] = med
    cheapest_bus = (weekend[weekend["operator_display"] != "Amtrak"]
                   .groupby("operator_display")["price_usd"].median())
    if not cheapest_bus.empty:
        fares[f"Bus ({cheapest_bus.idxmin()})"] = cheapest_bus.min()

    table = rental_vs_rail_table(fares, group_sizes=(group_size,), days=days)
    rental_pp = table["rental_per_person"].iloc[0] if not table.empty else None

    def color_for(label: str) -> str:
        # "Bus (OurBus)" should render OurBus's own color, not a lookup
        # of the literal word "Bus" - the color must come from the
        # operator name inside the parens, not the first word.
        if label in style.SERVICE_COLOR:
            return style.SERVICE_COLOR[label]
        if "(" in label:
            return style.operator_color(label.split("(")[1].rstrip(")"))
        return style.operator_color(label)

    style.apply_style()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = list(fares.keys()) + ["Rental (modeled, per person)"]
    values = [v * 2 for v in fares.values()] + ([rental_pp] if rental_pp else [])
    colors = [color_for(l) for l in fares.keys()] + [style.STATUS["warning"]]
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Round-trip cost per person ($)")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    style.finish(fig, out_path,
                title=f"{persona}: per-person weekend cost, rail/bus vs modeled rental",
                subtitle=f"Group of {group_size} sharing one rental, {days}-day trip "
                         f"- rental figures are MODELED, not scraped")

    # .item() / float() strip numpy scalar types (pandas .median() returns
    # numpy.float64) so json.dumps doesn't silently stringify them via
    # default=str - bit us once already: a numpy.bool_ comparison result
    # rendered as the STRING "False" rather than JSON's `false`.
    cheapest_rail_or_bus = min(v * 2 for v in fares.values()) if fares else None
    is_cheapest = bool(rental_pp is not None and cheapest_rail_or_bus is not None
                       and rental_pp < cheapest_rail_or_bus)
    return {"persona": persona, "group_size": group_size,
           "fares_round_trip_per_person": {k: round(float(v) * 2, 2)
                                           for k, v in fares.items()},
           "rental_per_person_modeled": rental_pp,
           "rental_is_cheapest": is_cheapest}
