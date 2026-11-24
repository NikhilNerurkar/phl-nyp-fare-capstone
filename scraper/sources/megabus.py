"""Megabus journey planner - covers Megabus AND Peter Pan Bus Lines.

Peter Pan sells through the Megabus journey planner, so one endpoint gives
us two of the four operators named in the framing document. The real carrier
is on each leg, so we split them into distinct operators rather than
lumping everything under "Megabus".

Contract (no key, anonymous):
  GET https://us.megabus.com/journey-planner/api/origin-cities
  GET https://us.megabus.com/journey-planner/api/journeys
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..http import PoliteClient
from ..models import (FareObservation, MODE_BUS, STATUS_ERROR,
                      STATUS_NO_SERVICE, STATUS_OK)
from .base import Context, Source
from .flix import _sample_across_day

JOURNEYS = "https://us.megabus.com/journey-planner/api/journeys"

CITY_IDS = {"PHL": "127", "NYP": "123"}  # Philadelphia, PA / New York, NY

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")

# Megabus returns naive local times; this corridor is entirely US/Eastern.
_EASTERN_OFFSET_STD = "-05:00"
_EASTERN_OFFSET_DST = "-04:00"


class MegabusSource(Source):
    name = "megabus"
    mode = MODE_BUS

    def collect(self, ctx: Context) -> list[FareObservation]:
        rl = ctx.config.rate_limit_for(self.name)
        out: list[FareObservation] = []
        headers = {"Accept": "application/json", "Referer": "https://us.megabus.com/"}
        with PoliteClient(
            min_delay=rl["min_delay_seconds"],
            max_delay=rl["max_delay_seconds"],
            max_retries=rl["max_retries"],
            timeout=rl["timeout_seconds"],
            headers=headers,
        ) as client:
            for travel_date, direction in ctx.legs():
                try:
                    out.extend(self._one_leg(ctx, client, travel_date, direction))
                except Exception as e:
                    ctx.log.warning("megabus %s %s failed: %s",
                                    travel_date, direction, e)
                    out.append(self._status_row(
                        ctx, travel_date, direction, STATUS_ERROR,
                        note=str(e)[:300]))
        return out

    def _one_leg(self, ctx: Context, client: PoliteClient,
                 travel_date: date, direction: str) -> list[FareObservation]:
        o, d = ("PHL", "NYP") if direction == "outbound" else ("NYP", "PHL")
        params = {
            "originId": CITY_IDS[o],
            "destinationId": CITY_IDS[d],
            "departureDate": travel_date.isoformat(),
            "totalPassengers": "1",
            "concessionCount": "0",
            "nusCount": "0",
            "otherDisabilityCount": "0",
            "promotionCode": "",
            "days": "1",
        }
        payload = client.get_json(JOURNEYS, params=params)
        raw_ref = ctx.store.save_raw(
            self.name, f"{travel_date}_{direction}", payload, ctx.snapshot_date)

        journeys = (payload or {}).get("journeys") or []
        rows = [self._to_observation(ctx, j, travel_date, direction, o, d, raw_ref)
                for j in journeys]
        rows = [r for r in rows if r]

        if not rows:
            rows.append(self._status_row(ctx, travel_date, direction,
                                         STATUS_NO_SERVICE, raw_ref=raw_ref))
        if not ctx.is_full_sweep(travel_date):
            rows = _sample_across_day(rows, ctx.config.sample_hours)
        return rows

    def _to_observation(self, ctx: Context, j: dict, travel_date: date,
                        direction: str, o: str, d: str,
                        raw_ref: str) -> FareObservation | None:
        legs = j.get("legs") or []
        carrier = (legs[0].get("carrier") if legs else None) or "Megabus"
        origin = j.get("origin") or {}
        dest = j.get("destination") or {}
        price = _f(j.get("price"))

        return FareObservation(
            snapshot_at=ctx.snapshot_at,
            snapshot_date=ctx.snapshot_date,
            travel_date=travel_date,
            direction=direction,
            origin_code=o, origin_name=origin.get("cityName") or _city(o),
            dest_code=d, dest_name=dest.get("cityName") or _city(d),
            mode=MODE_BUS,
            operator=_clean_carrier(carrier),
            source="us.megabus.com",
            status=STATUS_OK if price is not None else STATUS_NO_SERVICE,
            price_usd=price,
            price_with_fees_usd=None,   # checkout fees not exposed here
            service_name=_clean_carrier(carrier),
            vehicle_number=j.get("routeName") or j.get("journeyId"),
            fare_class="Standard",
            depart_ts=_localize(j.get("departureDateTime"), travel_date),
            arrive_ts=_localize(j.get("arrivalDateTime"), travel_date),
            duration_min=_duration_min(j.get("duration")),
            transfers=max(len(legs) - 1, 0) if legs else None,
            is_direct=len(legs) <= 1 if legs else None,
            seats_remaining=j.get("lowStockCount"),
            origin_stop=origin.get("stopName"),
            dest_stop=dest.get("stopName"),
            source_url=JOURNEYS,
            raw_ref=raw_ref,
        )

    def _status_row(self, ctx: Context, travel_date: date, direction: str,
                    status: str, raw_ref: str | None = None,
                    note: str | None = None) -> FareObservation:
        o, d = ("PHL", "NYP") if direction == "outbound" else ("NYP", "PHL")
        return FareObservation(
            snapshot_at=ctx.snapshot_at, snapshot_date=ctx.snapshot_date,
            travel_date=travel_date, direction=direction,
            origin_code=o, origin_name=_city(o),
            dest_code=d, dest_name=_city(d),
            mode=MODE_BUS, operator="Megabus",
            source="us.megabus.com", status=status,
            source_url=JOURNEYS, raw_ref=raw_ref, notes=note,
        )


# --- helpers ----------------------------------------------------------------

def _city(code: str) -> str:
    return "Philadelphia, PA" if code == "PHL" else "New York, NY"


def _clean_carrier(name: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    if "peter pan" in low:
        return "Peter Pan"
    if "megabus" in low:
        return "Megabus"
    if "greyhound" in low:
        return "Greyhound"
    return n or "Megabus"


def _duration_min(iso: str | None) -> int | None:
    """'PT2H30M' -> 150."""
    if not iso:
        return None
    m = _DURATION_RE.fullmatch(iso.strip())
    if not m:
        return None
    h, mins = m.group(1), m.group(2)
    return (int(h) if h else 0) * 60 + (int(mins) if mins else 0)


def _localize(ts: str | None, travel_date: date) -> str | None:
    """Attach the Eastern UTC offset to Megabus's naive timestamps.

    US DST ends the first Sunday in November. Our collection window spans that
    boundary, so we pick the offset from the travel date rather than assuming.
    """
    if not ts:
        return None
    if ts.endswith("Z") or "+" in ts[10:] or ts[10:].count("-") > 0:
        return ts  # already has an offset
    return ts + _eastern_offset(travel_date)


def _eastern_offset(d: date) -> str:
    """DST runs 2nd Sunday of March to 1st Sunday of November."""
    year = d.year
    # first Sunday in November
    nov = date(year, 11, 1)
    first_sun_nov = nov.day + (6 - nov.weekday()) % 7
    dst_end = date(year, 11, first_sun_nov)
    mar = date(year, 3, 1)
    first_sun_mar = mar.day + (6 - mar.weekday()) % 7
    dst_start = date(year, 3, first_sun_mar + 7)
    return _EASTERN_OFFSET_DST if dst_start <= d < dst_end else _EASTERN_OFFSET_STD


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
