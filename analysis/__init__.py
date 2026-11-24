"""Analysis layer for the PHL<->NYP fare dataset.

Every module here reads the live export fresh and makes no assumption about
how many days of data exist. Run `python tools/run_analysis.py` any time -
today, or after weeks more collection - and it regenerates every chart,
table and finding from whatever is actually in data/exports/fares_latest.parquet.

No module hardcodes a date, a row count, or a specific travel date. Several
(see overlap.py) are written against a join that returns nothing today and
will start returning results automatically if a WAS-NYP source is ever added
to the same fares table - that is deliberate, not a TODO.
"""
