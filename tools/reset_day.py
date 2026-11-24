"""Delete one snapshot day's rows so it can be re-collected cleanly.

Use when a parsing bug produced wrong labels. Raw payloads under data/raw/
are untouched, so nothing observed is actually lost.

    python tools/reset_day.py 2026-10-29          # whole day
    python tools/reset_day.py 2026-10-29 flix     # one source only
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "fares.db"

SOURCE_HOSTS = {
    "flix": "global.api.flixbus.com",
    "megabus": "us.megabus.com",
    "wanderu": "api.wanderu.com",
}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    day = sys.argv[1]
    src = sys.argv[2] if len(sys.argv) > 2 else None

    conn = sqlite3.connect(DB)
    before = conn.execute("SELECT COUNT(*) FROM fares").fetchone()[0]

    if src:
        host = SOURCE_HOSTS.get(src, src)
        cur = conn.execute(
            "DELETE FROM fares WHERE snapshot_date = ? AND source = ?",
            (day, host))
        what = f"{day} / {host}"
    else:
        cur = conn.execute("DELETE FROM fares WHERE snapshot_date = ?", (day,))
        what = day

    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM fares").fetchone()[0]
    print(f"deleted {cur.rowcount} rows for {what}")
    print(f"rows: {before} -> {after}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
