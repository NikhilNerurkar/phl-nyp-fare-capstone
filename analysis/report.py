"""Orchestrates every analysis module, writes everything a slide needs.

Re-run any time - today with 17 days of data, later with 40 - and this
regenerates all of it fresh from whatever's in the latest export. Nothing
here hardcodes a date, a row count, or assumes a specific day exists.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import booking_curves, census, dashboard, driving, fare_gap, overlap, personas, signals
from .clean import coverage_summary, load_clean, load_raw

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
TABLES = REPORTS / "tables"


def run() -> dict:
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)

    raw = load_raw()
    df = load_clean()
    findings: dict = {"generated_at": datetime.now(timezone.utc).isoformat(),
                      "rows_raw": len(raw), "rows_clean": len(df),
                      "snapshot_days": raw["snapshot_date"].nunique(),
                      "travel_dates_in_window": raw["travel_date"].nunique()}

    cov = coverage_summary(raw)
    cov.to_csv(TABLES / "coverage_by_day.csv", index=False)
    findings["thin_or_missing_days"] = (
        cov.loc[cov["thin_day"], "snapshot_date"].astype(str).tolist())

    # --- core question 2: booking behavior ---------------------------------
    findings["booking_curve_by_operator"] = booking_curves.booking_curve_by_operator(
        df, FIGURES / "booking_curve_by_operator.png")
    findings["booking_curve_weekday_weekend"] = booking_curves.booking_curve_by_dow(
        df, FIGURES / "booking_curve_weekday_weekend.png")
    findings["amtrak_fare_heatmap"] = booking_curves.fare_heatmap_by_hour_dow(
        df, FIGURES / "amtrak_fare_heatmap.png", operator="Amtrak")

    # --- core question 3: fare gap ------------------------------------------
    gap_table = fare_gap.fare_gap_table(df)
    gap_table.to_csv(TABLES / "fare_gap_table.csv", index=False)
    findings["fare_gap_regional_vs_greyhound"] = fare_gap.fare_gap_by_dbd(
        df, FIGURES / "fare_gap_regional_vs_greyhound.png")

    # --- core question 4: leader/follower signal ----------------------------
    findings["leader_follower_regional_vs_greyhound"] = signals.leader_follower(
        df, FIGURES / "leader_follower_regional_vs_greyhound.png")

    # --- WAS-NYC overlap: designed no-op until that data exists ------------
    findings["was_nyc_overlap_status"] = overlap.overlap_readiness_check()

    # --- personas -------------------------------------------------------------
    findings["persona_commuter"] = personas.commuter_view(
        df, FIGURES / "persona_commuter.png")
    findings["persona_business_traveler"] = personas.business_traveler_view(
        df, FIGURES / "persona_business_traveler.png")
    findings["persona_student"] = personas.student_or_family_view(
        df, FIGURES / "persona_student.png", persona="Student", group_size=2)
    findings["persona_family"] = personas.student_or_family_view(
        df, FIGURES / "persona_family.png", persona="Family", group_size=4)

    # --- census affordability (no-op with a clear reason if no key) --------
    rail_fares = {
        svc: df.loc[df["service_name"] == svc, "price_usd"].median()
        for svc in ["Acela", "Northeast Regional", "Keystone Service"]
    }
    rail_fares = {k: v for k, v in rail_fares.items() if v == v}  # drop NaN
    income = census.fetch_income_brackets()
    findings["census_configured"] = income.get("configured", False)
    if income.get("configured") and income.get("data") is not None:
        afford = census.affordability_table(income, rail_fares)
        if afford is not None:
            afford.to_csv(TABLES / "census_affordability.csv", index=False)
            findings["census_affordability_rows"] = len(afford)
            findings["census_affordability_summary"] = census.affordability_summary(afford)
            findings["census_income_distribution"] = census.plot_income_distribution(
                income, FIGURES / "census_income_distribution.png")
    else:
        findings["census_reason"] = income.get("reason")

    _write_findings_md(findings)
    (REPORTS / "findings.json").write_text(json.dumps(findings, indent=2, default=str))
    dashboard.build(findings, REPORTS / "dashboard.html")
    return findings


def _write_findings_md(f: dict) -> None:
    lines = [
        "# Analysis findings",
        f"_Generated {f['generated_at']} from {f['rows_clean']:,} cleaned rows "
        f"({f['rows_raw']:,} raw), {f['snapshot_days']} snapshot days, "
        f"{f['travel_dates_in_window']} travel dates._",
        "",
    ]
    if f["thin_or_missing_days"]:
        lines += [f"**Data quality note:** thin/partial snapshot days: "
                 f"{', '.join(f['thin_or_missing_days'])}. See "
                 f"docs/DATA_DICTIONARY.md.", ""]

    bc = f["booking_curve_by_operator"]
    lines += ["## Booking curve (core question 2)",
              f"Plotted: {', '.join(bc['operators_plotted'])}. "
              f"Dataset currently reaches {bc['max_dbd_in_data']} DBD.",
              "![](figures/booking_curve_by_operator.png)", ""]

    wd = f["booking_curve_weekday_weekend"]
    lines += [f"Weekday median ${wd['weekday_median']} vs weekend median "
             f"${wd['weekend_median']} ({wd['gap_pct']}% gap).",
             "![](figures/booking_curve_weekday_weekend.png)", ""]

    fg = f["fare_gap_regional_vs_greyhound"]
    lines += ["## Fare gap (core question 3)",
              f"{fg['rail_service']} vs {fg['bus_benchmark']}: median gap "
              f"${fg['median_gap_usd']}. Rail is cheaper at DBD "
              f"{fg['rail_cheaper_at_dbd'] or 'never, in this window'}.",
              "![](figures/fare_gap_regional_vs_greyhound.png)", ""]

    lf = f["leader_follower_regional_vs_greyhound"]
    lines += ["## Leader/follower signal (core question 4)",
              f"{lf['n_snapshot_days']} snapshot days available. "
              f"Reading: **{lf.get('reading', 'n/a')}**.",
              "![](figures/leader_follower_regional_vs_greyhound.png)", ""]

    ov = f["was_nyc_overlap_status"]
    lines += ["## WAS-NYC overlap (deferred)",
              f"Route pairs currently in data: {', '.join(ov['route_pairs_in_data'])}. "
              f"Ready for overlap analysis: {ov['ready_for_overlap_analysis']}. "
              f"Next step: {ov['next_step']}", ""]

    lines += ["## Personas", ""]
    for key, title in [("persona_commuter", "Commuter"),
                       ("persona_business_traveler", "Business Traveler"),
                       ("persona_student", "Student"), ("persona_family", "Family")]:
        p = f[key]
        fig_name = ("persona_business_traveler.png" if key == "persona_business_traveler"
                   else f"{key}.png")
        lines += [f"### {title}", f"```\n{json.dumps(p, indent=2, default=str)}\n```",
                 f"![](figures/{fig_name})", ""]

    lines += ["## Census affordability (Philadelphia vs NYC)", ""]
    if f.get("census_configured") and f.get("census_affordability_rows"):
        dist = f.get("census_income_distribution", {})
        lines += [
            f"Source: ACS 5-year estimates (2023), table B19001 (households "
            f"by income bracket), Philadelphia County PA vs the five NYC "
            f"boroughs summed.",
            f"Philadelphia: {dist.get('phl_pct_households_under_35k')}% of "
            f"households earn under $35k/yr. NYC: "
            f"{dist.get('nyc_pct_households_under_35k')}%.",
            "![](figures/census_income_distribution.png)", "",
            "**% of households in a bracket where a round-trip fare exceeds "
            "2% of monthly income** (affordability lens, not a demand model "
            "- see analysis/census.py):",
            "```\n" + json.dumps(f.get("census_affordability_summary", {}),
                                 indent=2) + "\n```",
            f"Full bracket-level table: tables/census_affordability.csv "
            f"({f['census_affordability_rows']} rows).",
        ]
    else:
        lines += [f"Not run: {f.get('census_reason')}. See analysis/census.py "
                 f"to activate (free API key, 2-minute signup)."]

    (REPORTS / "findings.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import pprint
    pprint.pprint(run())
