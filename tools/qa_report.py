"""Data-quality report. Run after any collection to see what landed.

    python tools/qa_report.py

Shows coverage, per-service price distributions, and flags values that look
implausible for this market. Sanity-check this before trusting an export.
"""
from __future__ import annotations

import sqlite3
import statistics as st
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "fares.db"

# Rough plausibility envelope for a ~90 mile city-pair, USD one-way.
PLAUSIBLE = {"bus": (5, 90), "rail": (10, 400), "air": (40, 800),
             "car": (20, 400)}


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("=" * 78)
    print("COVERAGE")
    print("=" * 78)
    for r in conn.execute("""
        SELECT snapshot_date, COUNT(*) n,
               COUNT(DISTINCT travel_date) dates,
               SUM(price_usd IS NOT NULL AND price_usd != '') priced
        FROM fares GROUP BY snapshot_date ORDER BY snapshot_date"""):
        print(f"  {r['snapshot_date']}  rows={r['n']:<6} "
              f"travel_dates={r['dates']:<4} priced={r['priced']}")

    print()
    print("=" * 78)
    print("BY SERVICE  (priced rows only)")
    print("=" * 78)
    print(f"  {'mode':<5} {'operator':<12} {'service':<22} {'n':>5} "
          f"{'min':>7} {'med':>7} {'max':>7}")
    rows = conn.execute("""
        SELECT mode, operator, service_name, CAST(price_usd AS REAL) p
        FROM fares
        WHERE status='ok' AND price_usd IS NOT NULL AND price_usd != ''
    """).fetchall()

    groups: dict[tuple, list[float]] = {}
    for r in rows:
        groups.setdefault((r["mode"], r["operator"], r["service_name"] or ""),
                          []).append(r["p"])

    flags: list[str] = []
    for (mode, op, svc), ps in sorted(groups.items(),
                                      key=lambda kv: (kv[0][0], -len(kv[1]))):
        ps.sort()
        lo, hi = PLAUSIBLE.get(mode, (0, 10**9))
        med = st.median(ps)
        mark = ""
        if med < lo or med > hi:
            mark = "  <-- median outside plausible range"
            flags.append(f"{op}/{svc}: median ${med:.2f} outside ${lo}-${hi}")
        print(f"  {mode:<5} {op:<12} {svc[:22]:<22} {len(ps):>5} "
              f"{ps[0]:>7.2f} {med:>7.2f} {ps[-1]:>7.2f}{mark}")

    print()
    print("=" * 78)
    print("STATUS MIX BY SOURCE")
    print("=" * 78)
    for r in conn.execute("""
        SELECT source, status, COUNT(*) n FROM fares
        GROUP BY source, status ORDER BY source, n DESC"""):
        print(f"  {r['source']:<26} {r['status']:<12} {r['n']}")

    print()
    print("=" * 78)
    print("UNMAPPED CARRIERS  (operator == service_name, all-caps code)")
    print("=" * 78)
    for r in conn.execute("""
        SELECT operator, COUNT(*) n FROM fares
        WHERE operator = service_name AND operator = UPPER(operator)
          AND LENGTH(operator) <= 6
        GROUP BY operator ORDER BY n DESC"""):
        print(f"  {r['operator']:<10} {r['n']}")

    print()
    print("=" * 78)
    print("CROSS-SOURCE AGREEMENT  (same operator, two sources, same day)")
    print("=" * 78)
    for r in conn.execute("""
        SELECT operator, source, COUNT(*) n,
               ROUND(AVG(CAST(price_usd AS REAL)), 2) avg
        FROM fares WHERE status='ok' AND operator IN
              ('FlixBus','Greyhound','Peter Pan')
        GROUP BY operator, source ORDER BY operator, source"""):
        print(f"  {r['operator']:<12} {r['source']:<26} n={r['n']:<6} "
              f"avg=${r['avg']}")

    if flags:
        print()
        print("!" * 78)
        print("FLAGS")
        for f in flags:
            print(f"  - {f}")
        print("!" * 78)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
