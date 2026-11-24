"""The one command for the analysis layer.

    python tools/run_analysis.py

Reads data/exports/fares_latest.parquet (produced by run_daily.py), writes
every chart, table and finding to reports/. Safe to re-run any time -
reruns regenerate everything fresh from whatever data exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.report import run  # noqa: E402


def main() -> int:
    findings = run()
    root = Path(__file__).resolve().parent.parent
    n_figs = len(list((root / "reports" / "figures").glob("*.png")))
    print(f"\nOpen this in a browser:  reports/dashboard.html")
    print(f"(also wrote findings.md, findings.json, {n_figs} figures, "
         f"and tables to reports/tables/)")
    print(f"rows_clean={findings['rows_clean']:,}  "
         f"snapshot_days={findings['snapshot_days']}  "
         f"census_configured={findings['census_configured']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
