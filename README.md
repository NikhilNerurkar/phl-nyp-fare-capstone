# PHL ↔ NYP competitive fare collection

Team 2 · BUDT770 Capstone · sponsor: Amtrak Revenue Products & Business Planning

Daily fare snapshots for Philadelphia ↔ New York across **rail, bus and
(planned) air and car**, so the sponsor can see how Acela, Northeast Regional,
Keystone, buses and airlines price the same trip across the booking window.

## Run it

```bash
python run_daily.py
```

That's the whole thing. Run it **once a day**. It will:

1. Collect every enabled source for every remaining travel date, both directions
2. Write to `data/fares.db` (SQLite — the system of record)
3. Archive every raw API response under `data/raw/<date>/<source>/`
4. Export `data/exports/fares_latest.csv` + a timestamped immutable copy + Parquet

Takes roughly **20–25 minutes**. A Chrome window opens during the Wanderu
step — that's expected, leave it alone.

### First-time setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### Useful extras

```bash
python tools/qa_report.py            # data-quality report - run after each collection
python tools/test_source.py flix 2   # smoke-test one source on 2 travel dates
python tools/reset_day.py 2026-10-29 # delete a day's rows so it can be re-collected
```

## What gets collected

| Source | Operators | Transport |
|---|---|---|
| `wanderu` | **All Amtrak** (Acela, Northeast Regional, Keystone, Pennsylvanian, Carolinian, Palmetto, Vermonter, Crescent, Cardinal), **OurBus**, + cross-check on all buses | Browser session (Cloudflare) |
| `flix` | FlixBus, Greyhound | Plain JSON API |
| `megabus` | Peter Pan (Megabus's PHL–NYC inventory is Peter Pan-operated) | Plain JSON API |

Not yet implemented: `air` (PHL→EWR/LGA/JFK), `transit` (SEPTA + NJ Transit),
`driving` (rental + modeled cost). See `docs/STATUS.md`.

## Before you analyse the data

Read **`docs/DATA_DICTIONARY.md`** first. Two things will bite you otherwise:

1. **Not every row is downtown-to-downtown.** Wanderu searches city-to-city, so
   results include airport vans and suburban park-and-ride stops. Filter on
   `origin_stop` / `dest_stop` / `duration_min`.
2. **Aggregator prices run ~20% above operator prices** for the same bus on the
   same day. Treat `source` as a dimension, not noise.

`tools/qa_report.py` flags both automatically.

## Configuration

Everything lives in `config.yaml`:

- `travel_date_start` / `travel_date_end` — which travel dates to monitor
- `last_snapshot_date` — the scraper refuses to run past this (one-line change
  to extend collection)
- `tiering.full_sweep_within_dbd` — dates within this many days get *every*
  departure; farther dates get a representative sample across the day
- `sources` — turn individual sources on/off

## Design principles

- **Nothing is invented.** A field we could not observe is `NULL`. A failed
  query is recorded with `status='error'` and a NULL price — never imputed.
- **Raw payloads are kept.** If a parsing rule turns out wrong, rows can be
  re-derived without re-collecting. This already paid for itself once.
- **Clean in layers.** The scraper only normalizes (types, one fare definition,
  explicit status). Outlier rules, cross-source matching and segmentation belong
  in a separate step, *after* you have seen the distribution. A snapshot can
  never be re-collected, so destructive cleaning at scrape time is the one
  irreversible mistake available to us.
- **Sources are isolated.** One broken source does not take down the run.
- **Daily snapshots, derived DBD.** No milestone is hard-coded; 3/5/7/14/21/28
  DBD all fall out of `travel_date − snapshot_date`, and 60/90 DBD come free.

## Collection window caveat

Snapshots stop on `last_snapshot_date` (2026-12-10). Travel dates on or before
that get a complete 0-DBD booking curve. **Dates from Dec 11–31 are long-lead
observations only** — they never reach the short-lead window. Say so in any
chart that mixes them.

## Layout

```
run_daily.py              the one command
config.yaml               all settings
scraper/
  models.py               canonical FareObservation (one row shape for all modes)
  storage.py              SQLite + CSV/Parquet export + raw archive
  config.py               config loading, travel dates, tiering
  http.py                 polite client: jitter, backoff, retry
  sources/                one file per source, behind a common interface
tools/                    qa_report, test_source, reset_day, probes
docs/
  DATA_DICTIONARY.md      every column, and the comparability caveats
  STATUS.md               what works, what's blocked, what was tried
data/
  fares.db                system of record
  raw/                    untouched API responses, by day
  exports/                CSV + Parquet for the team
  logs/                   one log per run
```
