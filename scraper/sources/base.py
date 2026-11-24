"""The contract every fare source implements.

A source knows how to turn (travel_date, direction) into FareObservations.
It does NOT know about storage, scheduling, or other sources. That isolation
is what lets one broken source fail without taking the run down.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterator

from ..config import Config
from ..models import FareObservation
from ..storage import Store


@dataclass
class Context:
    """Everything a source needs, and nothing it doesn't."""
    config: Config
    store: Store
    snapshot_date: date
    snapshot_at: datetime
    log: logging.Logger

    def travel_dates(self) -> list[date]:
        return self.config.travel_dates(self.snapshot_date)

    def is_full_sweep(self, travel_date: date) -> bool:
        return self.config.is_full_sweep(travel_date, self.snapshot_date)

    def legs(self) -> Iterator[tuple[date, str]]:
        """Every (travel_date, direction) pair this run should collect."""
        for td in self.travel_dates():
            for direction in self.config.collection["directions"]:
                yield td, direction


class Source(ABC):
    """Base class for all fare sources."""

    name: str = "unnamed"
    mode: str = "unknown"

    @abstractmethod
    def collect(self, ctx: Context) -> list[FareObservation]:
        """Return every observation this source can make for this snapshot.

        Must not raise for a single failed query - record an error-status
        observation or skip, and keep going. Raising aborts only this source.
        """
        raise NotImplementedError

    # --- helpers shared by concrete sources --------------------------------

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
