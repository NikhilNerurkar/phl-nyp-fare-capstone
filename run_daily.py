"""Daily fare snapshot. The one command you run.

    python run_daily.py

Collects every enabled source for every remaining travel date, writes to
SQLite, and drops a timestamped CSV in data/exports/.

Sources are isolated: if one breaks, the others still complete and the run
still exports. Nothing is ever imputed - a failed query is recorded with
status='error' and a NULL price.
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from scraper.config import Config
from scraper.sources import build_sources
from scraper.sources.base import Context
from scraper.storage import Store

LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"


def setup_logging(run_id: str, verbose: bool) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)-10s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_DIR / f"{run_id}.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # httpx logs every request at INFO; too noisy for a 1000-query run.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return logging.getLogger("run")


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily PHL<->NYP fare snapshot")
    ap.add_argument("--only", help="comma-separated source names to run")
    ap.add_argument("--config", default=None)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="run even after last_snapshot_date")
    ap.add_argument("--parallel", action="store_true",
                    help="collect all sources at once (faster, but measured "
                         "to cost Wanderu data - watch the log if you use it)")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    snapshot_at = datetime.now(timezone.utc)
    today = date.today()
    run_id = snapshot_at.strftime("%Y%m%d_%H%M%S")
    log = setup_logging(run_id, args.verbose)

    log.info("=" * 68)
    log.info("PHL<->NYP fare snapshot  run=%s  date=%s", run_id, today)

    if today > cfg.last_snapshot_date and not args.force:
        log.warning("Past last_snapshot_date (%s). Collection window is closed.",
                    cfg.last_snapshot_date)
        log.warning("Use --force to collect anyway, or extend the date in "
                    "config.yaml.")
        return 0

    travel_dates = cfg.travel_dates(today)
    if not travel_dates:
        log.warning("No travel dates remaining in the window. Nothing to do.")
        return 0

    directions = cfg.collection["directions"]
    log.info("travel dates: %s .. %s (%d days) x %d directions",
             travel_dates[0], travel_dates[-1], len(travel_dates), len(directions))

    enabled = dict(cfg.sources)
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        enabled = {k: (k in wanted) for k in enabled}
    sources = build_sources(enabled)
    log.info("sources: %s", ", ".join(s.name for s in sources) or "(none)")

    store = Store(cfg.path("db_path"), cfg.path("raw_dir"), cfg.path("export_dir"))

    # Sources hit entirely different hosts, so they run concurrently - each
    # still rate-limits itself against its own host, so nobody sees extra load.
    #
    # Threads only *collect*. Every database write happens back on the main
    # thread below, because a SQLite connection is not safe to share across
    # threads. Sources touch the store only via save_raw(), which writes files
    # into its own per-source directory.
    def collect_one(src):
        slog = logging.getLogger(src.name)
        sctx = Context(config=cfg, store=store, snapshot_date=today,
                       snapshot_at=snapshot_at, log=slog)
        started = datetime.now(timezone.utc)
        slog.info("starting")
        try:
            rows = src.collect(sctx)
            return src.name, rows, started, datetime.now(timezone.utc), None
        except Exception as e:
            slog.exception("FAILED: %s", e)
            return src.name, [], started, datetime.now(timezone.utc), e

    # Sequential by default. Running all three at once was measured on
    # 2026-10-29 and was worse, not better: Wanderu's browser session died
    # about 3 minutes in and lost 91 of 126 legs of Amtrak data. Opt in with
    # --parallel only if you are watching the run and will check the log.
    workers = len(sources) if (args.parallel and sources) else 1
    log.info("-" * 68)
    log.info("collecting %d source(s), %s", len(sources),
             f"{workers} at a time" if workers > 1 else "one at a time")

    results = []
    if sources:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(collect_one, s) for s in sources]
            for fut in as_completed(futures):
                results.append(fut.result())

    total = 0
    for name, rows, started, finished, err in results:
        elapsed = (finished - started).total_seconds()
        if err is not None:
            store.log_run(run_id, name, started, finished, "failed", 0, 0,
                          str(err)[:500])
            log.error("[%s] failed after %.1fs: %s", name, elapsed, err)
            continue
        written = store.write(rows)
        total += written
        priced = sum(1 for r in rows if r.price_usd is not None)
        log.info("[%s] %d rows (%d priced) in %.1fs",
                 name, written, priced, elapsed)
        store.log_run(run_id, name, started, finished, "ok", written, 0)

    log.info("=" * 68)
    log.info("today's collection, by source:")
    for row in store.summary(today):
        log.info("   %-6s %-16s %-10s n=%-5d avg=$%s",
                 row["mode"], row["operator"], row["status"], row["n"],
                 row["avg_price"] if row["avg_price"] is not None else "-")

    paths = store.export(run_id)
    log.info("-" * 68)
    log.info("wrote %d rows this run; %s rows total", total, paths["rows"])
    log.info("CSV  -> %s", paths["latest_csv"])
    log.info("copy -> %s", paths["stamped_csv"])
    if "parquet" in paths:
        log.info("parq -> %s", paths["parquet"])
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
