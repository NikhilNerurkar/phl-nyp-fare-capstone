"""The canonical fare observation.

Every source, no matter how different its API, normalizes into this one row
shape. That is what makes cross-mode comparison honest: one definition of
"price", one definition of "departure time", one definition of "status".

Nothing in here is ever invented. A field we could not observe stays None.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict, fields
from datetime import date, datetime, timezone
from typing import Optional

# --- controlled vocabularies ------------------------------------------------

# Status is a first-class signal, not an error flag. "sold_out" in particular
# is a demand observation the sponsor explicitly asked us to keep.
STATUS_OK = "ok"                 # a real, bookable price was observed
STATUS_SOLD_OUT = "sold_out"     # service exists, no seats for sale
STATUS_NO_SERVICE = "no_service" # source answered: nothing runs that day
STATUS_ERROR = "error"           # we failed to observe; price stays NULL
STATUS_MODELED = "modeled"       # not scraped - computed from documented inputs

MODE_RAIL = "rail"
MODE_BUS = "bus"
MODE_AIR = "air"
MODE_CAR = "car"

DIR_OUTBOUND = "outbound"   # PHL -> NYP
DIR_INBOUND = "inbound"     # NYP -> PHL


@dataclass
class FareObservation:
    """One price, for one departure, seen at one moment in time."""

    # --- when we looked -----------------------------------------------------
    snapshot_at: datetime          # UTC instant of collection
    snapshot_date: date            # local calendar date of collection

    # --- what trip ----------------------------------------------------------
    travel_date: date
    direction: str                 # DIR_OUTBOUND | DIR_INBOUND
    origin_code: str
    origin_name: str
    dest_code: str
    dest_name: str

    # --- which service ------------------------------------------------------
    mode: str                      # MODE_RAIL | MODE_BUS | MODE_AIR | MODE_CAR
    operator: str                  # "Amtrak", "FlixBus", "Greyhound", ...
    source: str                    # host we actually read, for traceability

    # --- the price ----------------------------------------------------------
    status: str = STATUS_OK
    price_usd: Optional[float] = None            # base fare, fees excluded
    price_with_fees_usd: Optional[float] = None  # checkout price if known
    currency: str = "USD"

    # --- service detail (this is what powers the internal Amtrak comparison) -
    service_name: Optional[str] = None   # "Acela", "Northeast Regional", "Keystone"
    vehicle_number: Optional[str] = None # train number / flight number
    fare_class: Optional[str] = None     # "Coach", "Business", "First"
    fare_bucket: Optional[str] = None    # "Saver", "Value", "Flexible"

    # --- schedule -----------------------------------------------------------
    depart_ts: Optional[str] = None      # ISO 8601 with UTC offset
    arrive_ts: Optional[str] = None
    duration_min: Optional[int] = None
    transfers: Optional[int] = None
    is_direct: Optional[bool] = None

    # --- extras -------------------------------------------------------------
    seats_remaining: Optional[int] = None
    origin_stop: Optional[str] = None    # actual terminal/station used
    dest_stop: Optional[str] = None
    source_url: Optional[str] = None
    raw_ref: Optional[str] = None        # path to the saved raw payload
    notes: Optional[str] = None

    # --- derived (filled by __post_init__) ----------------------------------
    dbd: Optional[int] = None            # days before departure
    travel_dow: Optional[int] = None     # 0=Mon .. 6=Sun
    is_weekend: Optional[bool] = None
    depart_hour: Optional[int] = None
    observation_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.dbd = (self.travel_date - self.snapshot_date).days
        self.travel_dow = self.travel_date.weekday()
        self.is_weekend = self.travel_dow >= 5

        if self.depart_ts and self.depart_hour is None:
            try:
                self.depart_hour = datetime.fromisoformat(self.depart_ts).hour
            except ValueError:
                self.depart_hour = None

        if self.observation_id is None:
            self.observation_id = self._fingerprint()

    def _fingerprint(self) -> str:
        """Stable id for one (snapshot, trip, service) tuple.

        Deliberately excludes price: re-running the scraper on the same day
        updates the price in place instead of creating a duplicate row.
        """
        parts = [
            self.snapshot_date.isoformat(),
            self.travel_date.isoformat(),
            self.direction,
            self.mode,
            self.operator,
            self.service_name or "",
            self.vehicle_number or "",
            self.depart_ts or "",
            self.fare_class or "",
            self.fare_bucket or "",
            self.origin_stop or "",
            self.dest_stop or "",
            self.source,
        ]
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]

    def to_row(self) -> dict:
        d = asdict(self)
        d["snapshot_at"] = self.snapshot_at.astimezone(timezone.utc).isoformat()
        d["snapshot_date"] = self.snapshot_date.isoformat()
        d["travel_date"] = self.travel_date.isoformat()
        return d


COLUMNS: list[str] = [f.name for f in fields(FareObservation)]
