"""Durable storage: SQLite as the system of record, flat files for humans.

Design rule: a snapshot can never be re-collected, so nothing here ever
destroys an observation. Writes are idempotent upserts keyed on
observation_id, so re-running a day's scrape repairs gaps instead of
duplicating rows.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .models import COLUMNS, FareObservation

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS fares (
    {", ".join(f"{c} TEXT" for c in COLUMNS)},
    PRIMARY KEY (observation_id)
);
CREATE INDEX IF NOT EXISTS idx_fares_travel  ON fares (travel_date, direction);
CREATE INDEX IF NOT EXISTS idx_fares_snap    ON fares (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_fares_mode    ON fares (mode, operator);
CREATE INDEX IF NOT EXISTS idx_fares_dbd     ON fares (dbd);

CREATE TABLE IF NOT EXISTS run_log (
    run_id        TEXT,
    source        TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    status        TEXT,
    rows_written  INTEGER,
    queries_made  INTEGER,
    error         TEXT,
    PRIMARY KEY (run_id, source)
);
"""


class Store:
    def __init__(self, db_path: str | Path, raw_dir: str | Path,
                 export_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.raw_dir = Path(raw_dir)
        self.export_dir = Path(export_dir)
        for p in (self.db_path.parent, self.raw_dir, self.export_dir):
            p.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        # WAL keeps the DB readable (and intact) if a run is interrupted.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- observations -------------------------------------------------------

    def write(self, observations: Sequence[FareObservation]) -> int:
        if not observations:
            return 0
        placeholders = ", ".join("?" for _ in COLUMNS)
        sql = (f"INSERT OR REPLACE INTO fares ({', '.join(COLUMNS)}) "
               f"VALUES ({placeholders})")
        rows = []
        for ob in observations:
            r = ob.to_row()
            rows.append([_as_text(r.get(c)) for c in COLUMNS])
        self.conn.executemany(sql, rows)
        self.conn.commit()
        return len(rows)

    # --- raw payloads -------------------------------------------------------

    def save_raw(self, source: str, key: str, payload, snapshot_date: date) -> str:
        """Persist the untouched response so we can always re-parse it later."""
        day_dir = self.raw_dir / snapshot_date.isoformat() / source
        day_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        path = day_dir / f"{safe}.json"
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.raw_dir.parent.parent)
                   if self.raw_dir.parent.parent in path.parents else path)

    # --- run log ------------------------------------------------------------

    def log_run(self, run_id: str, source: str, started_at: datetime,
                finished_at: datetime, status: str, rows_written: int,
                queries_made: int, error: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO run_log VALUES (?,?,?,?,?,?,?,?)",
            (run_id, source, started_at.isoformat(), finished_at.isoformat(),
             status, rows_written, queries_made, error),
        )
        self.conn.commit()

    # --- exports ------------------------------------------------------------

    def export(self, run_id: str) -> dict[str, str]:
        """Write the human-facing files after every run.

        Three artifacts:
          - fares_latest.csv   full dataset, always the same name (easy to open)
          - fares_<run>.csv    timestamped immutable copy
          - fares_latest.parquet  compact, typed, for pandas analysis
        """
        import pandas as pd

        df = pd.read_sql_query("SELECT * FROM fares", self.conn)
        df = _retype(df)

        out: dict[str, str] = {}
        latest_csv = self.export_dir / "fares_latest.csv"
        stamped_csv = self.export_dir / f"fares_{run_id}.csv"
        parquet = self.export_dir / "fares_latest.parquet"

        df.to_csv(latest_csv, index=False)
        df.to_csv(stamped_csv, index=False)
        try:
            df.to_parquet(parquet, index=False)
            out["parquet"] = str(parquet)
        except Exception:
            pass  # pyarrow missing is not worth failing a run over

        out["latest_csv"] = str(latest_csv)
        out["stamped_csv"] = str(stamped_csv)
        out["rows"] = str(len(df))
        return out

    def summary(self, snapshot_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT mode, operator, status, COUNT(*) AS n,
                   ROUND(AVG(CAST(price_usd AS REAL)), 2) AS avg_price
            FROM fares WHERE snapshot_date = ?
            GROUP BY mode, operator, status
            ORDER BY mode, operator, status
            """,
            (snapshot_date.isoformat(),),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()


def _as_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _retype(df):
    """SQLite stores everything as TEXT; give analysts real types back."""
    import pandas as pd

    numeric = ["price_usd", "price_with_fees_usd", "duration_min", "transfers",
               "seats_remaining", "dbd", "travel_dow", "depart_hour"]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("is_weekend", "is_direct"):
        if c in df.columns:
            df[c] = df[c].map({"1": True, "0": False})
    for c in ("snapshot_date", "travel_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    return df
