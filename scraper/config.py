"""Config loading and the travel-date / tiering logic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        p = Path(path) if path else ROOT / "config.yaml"
        with open(p, "r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    # --- convenience accessors ---------------------------------------------

    @property
    def market(self) -> dict: return self.raw["market"]

    @property
    def collection(self) -> dict: return self.raw["collection"]

    @property
    def storage(self) -> dict: return self.raw["storage"]

    @property
    def sources(self) -> dict: return self.raw["sources"]

    @property
    def rate_limit(self) -> dict: return self.collection["rate_limit"]

    def rate_limit_for(self, source: str) -> dict:
        """Rate limit for one source: defaults, with any per-source override.

        Keeps a slow, cautious default while letting well-behaved plain JSON
        endpoints run closer to their real speed.
        """
        base = {k: v for k, v in self.rate_limit.items() if k != "per_source"}
        override = (self.rate_limit.get("per_source") or {}).get(source) or {}
        return {**base, **override}

    def path(self, key: str) -> Path:
        return ROOT / self.storage[key]

    # --- dates --------------------------------------------------------------

    @property
    def last_snapshot_date(self) -> date:
        return _d(self.collection["last_snapshot_date"])

    def travel_dates(self, snapshot_date: date) -> list[date]:
        """Every future travel date still in the monitoring window.

        Dates already in the past are dropped - a fare for yesterday is
        meaningless and the source would reject it anyway.
        """
        start = max(_d(self.collection["travel_date_start"]), snapshot_date)
        end = _d(self.collection["travel_date_end"])
        if start > end:
            return []
        n = (end - start).days
        return [start + timedelta(days=i) for i in range(n + 1)]

    def is_full_sweep(self, travel_date: date, snapshot_date: date) -> bool:
        """Near-term dates get every departure; far dates get a sample."""
        dbd = (travel_date - snapshot_date).days
        return dbd <= self.collection["tiering"]["full_sweep_within_dbd"]

    @property
    def sample_hours(self) -> list[int]:
        return self.collection["tiering"]["sample_target_hours"]


def _d(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v))


def sample_by_hour(items: list, hour_of, target_hours: list[int]) -> list:
    """Pick the departure closest to each target hour.

    Used for far-out travel dates. Keeps the shape of the day (early, AM peak,
    midday, PM peak, evening) without querying every single departure.
    """
    chosen: dict[int, Any] = {}
    for it in items:
        h = hour_of(it)
        if h is None:
            continue
        target = min(target_hours, key=lambda t: abs(t - h))
        best = chosen.get(target)
        if best is None or abs(target - h) < abs(target - hour_of(best)):
            chosen[target] = it
    # Preserve original ordering, drop duplicates.
    picked = list(chosen.values())
    seen, out = set(), []
    for it in items:
        if id(it) in {id(x) for x in picked} and id(it) not in seen:
            seen.add(id(it))
            out.append(it)
    return out
