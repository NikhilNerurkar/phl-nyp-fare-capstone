"""Smoke-test a single source against a couple of travel dates.

Usage:  python tools/test_source.py flix
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.config import Config
from scraper.sources import build_sources
from scraper.sources.base import Context
from scraper.storage import Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "flix"
    ndays = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    cfg = Config.load()
    today = date.today()

    # Shrink the window so the smoke test is fast.
    cfg.raw["collection"]["travel_date_start"] = (today + timedelta(days=3)).isoformat()
    cfg.raw["collection"]["travel_date_end"] = (today + timedelta(days=2 + ndays)).isoformat()
    cfg.raw["collection"]["directions"] = ["outbound"]

    store = Store(cfg.path("db_path").with_name("test_fares.db"),
                  cfg.path("raw_dir") / "_test",
                  cfg.path("export_dir") / "_test")

    ctx = Context(config=cfg, store=store, snapshot_date=today,
                  snapshot_at=datetime.now(timezone.utc),
                  log=logging.getLogger(which))

    sources = {s.name: s for s in build_sources({which: True})}
    src = sources[which]

    print(f"\nTesting '{which}' for {ndays} travel date(s)...\n")
    rows = src.collect(ctx)

    print(f"--> {len(rows)} observations\n")
    ok = [r for r in rows if r.price_usd is not None]
    for r in rows[:12]:
        print(f"  {r.travel_date} dbd={r.dbd:>2} {r.operator:<18} "
              f"{str(r.service_name)[:20]:<20} {str(r.vehicle_number)[:8]:<8} "
              f"{str(r.fare_class)[:10]:<10} {str(r.fare_bucket)[:8]:<8} "
              f"${str(r.price_usd):<8} {str(r.depart_ts)[11:16]:<6} "
              f"{r.duration_min}min  [{r.status}]")
    if len(rows) > 12:
        print(f"  ... and {len(rows) - 12} more")

    print(f"\n  priced rows: {len(ok)} / {len(rows)}")
    if ok:
        prices = sorted(r.price_usd for r in ok)
        print(f"  price range: ${prices[0]:.2f} - ${prices[-1]:.2f}")
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    print(f"  statuses: {statuses}")

    n = store.write(rows)
    print(f"  wrote {n} rows to test db")
    store.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
