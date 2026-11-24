"""FlixBus + Greyhound via the public Flix search API.

One endpoint covers two of the four bus operators, because Flix owns
Greyhound. Verified live against PHL<->NYC: ~47 direct departures per date,
with base price, platform-fee price, times, duration and operator.

Contract (no key, anonymous):
  GET https://global.api.flixbus.com/search/autocomplete/cities
  GET https://global.api.flixbus.com/search/service/v4/search
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..http import PoliteClient
from ..models import (FareObservation, MODE_BUS, STATUS_ERROR, STATUS_NO_SERVICE,
                      STATUS_OK, STATUS_SOLD_OUT)
from .base import Context, Source

BASE = "https://global.api.flixbus.com"
SEARCH = f"{BASE}/search/service/v4/search"
AUTOCOMPLETE = f"{BASE}/search/autocomplete/cities"

# Resolved once and pinned, so a flaky autocomplete call can never silently
# redirect the whole run to the wrong Philadelphia.
CITY_IDS = {
    "PHL": "fd509c08-0a3e-4a44-b933-79f4a9db13da",  # Philadelphia, PA
    "NYP": "c0a47c54-53ea-46dc-984b-b764fc0b2fa9",  # New York, NY
}


class FlixSource(Source):
    name = "flix"
    mode = MODE_BUS

    def collect(self, ctx: Context) -> list[FareObservation]:
        rl = ctx.config.rate_limit_for(self.name)
        out: list[FareObservation] = []
        with PoliteClient(
            min_delay=rl["min_delay_seconds"],
            max_delay=rl["max_delay_seconds"],
            max_retries=rl["max_retries"],
            timeout=rl["timeout_seconds"],
        ) as client:
            for travel_date, direction in ctx.legs():
                try:
                    out.extend(self._one_leg(ctx, client, travel_date, direction))
                except Exception as e:  # one bad date must not kill the source
                    ctx.log.warning("flix %s %s failed: %s",
                                    travel_date, direction, e)
                    out.append(self._error_row(ctx, travel_date, direction, str(e)))
        return out

    # --- one (date, direction) ---------------------------------------------

    def _one_leg(self, ctx: Context, client: PoliteClient,
                 travel_date: date, direction: str) -> list[FareObservation]:
        o, d = ("PHL", "NYP") if direction == "outbound" else ("NYP", "PHL")
        params = {
            "from_city_id": CITY_IDS[o],
            "to_city_id": CITY_IDS[d],
            "departure_date": travel_date.strftime("%d.%m.%Y"),  # DD.MM.YYYY
            "products": '{"adult":1}',
            "currency": "USD",
            "locale": "en",
            "search_by": "cities",
            "include_after_midnight_rides": "1",
        }
        payload = client.get_json(SEARCH, params=params)

        raw_ref = ctx.store.save_raw(
            self.name, f"{travel_date}_{direction}", payload, ctx.snapshot_date)

        operators = payload.get("operators") or {}
        stations = payload.get("stations") or {}
        trips = payload.get("trips") or []

        rows: list[FareObservation] = []
        for trip in trips:
            results = trip.get("results") or {}
            # results is a dict keyed by uid, not a list - documented pitfall.
            for res in results.values():
                row = self._to_observation(
                    ctx, res, operators, stations,
                    travel_date, direction, o, d, raw_ref)
                if row:
                    rows.append(row)

        if not rows:
            rows.append(self._status_row(
                ctx, travel_date, direction, o, d, STATUS_NO_SERVICE, raw_ref))

        # Far-out dates: keep a representative spread instead of all ~47.
        if not ctx.is_full_sweep(travel_date):
            rows = _sample_across_day(rows, ctx.config.sample_hours)
        return rows

    # --- mapping ------------------------------------------------------------

    def _to_observation(self, ctx: Context, res: dict, operators: dict,
                        stations: dict, travel_date: date, direction: str,
                        o: str, d: str, raw_ref: str) -> FareObservation | None:
        price = (res.get("price") or {})
        status_txt = (res.get("status") or "").lower()

        if status_txt in ("available", "") and price.get("total") is not None:
            status = STATUS_OK
        elif status_txt in ("sold_out", "soldout", "full"):
            status = STATUS_SOLD_OUT
        else:
            status = STATUS_SOLD_OUT if price.get("total") is None else STATUS_OK

        legs = res.get("legs") or []
        op_id = (legs[0].get("operator_id") if legs else None) \
            or res.get("operator_id")
        op_name = (operators.get(op_id) or {}).get("name") if op_id else None

        dep = res.get("departure") or {}
        arr = res.get("arrival") or {}
        dur = res.get("duration") or {}
        duration_min = None
        if dur:
            duration_min = (dur.get("hours") or 0) * 60 + (dur.get("minutes") or 0)

        transfer_key = res.get("transfer_type_key") or ""
        is_direct = transfer_key == "direct"
        transfers = 0 if is_direct else (
            len(transfer_key.split("#")) - 1 if transfer_key else None)

        def stop_name(obj: dict) -> str | None:
            sid = obj.get("station_id")
            return (stations.get(sid) or {}).get("name") if sid else None

        return FareObservation(
            snapshot_at=ctx.snapshot_at,
            snapshot_date=ctx.snapshot_date,
            travel_date=travel_date,
            direction=direction,
            origin_code=o, origin_name=_city(o),
            dest_code=d, dest_name=_city(d),
            mode=MODE_BUS,
            operator=_clean_operator(op_id, op_name),
            source="global.api.flixbus.com",
            status=status,
            price_usd=_f(price.get("total")),
            price_with_fees_usd=_f(price.get("total_with_platform_fee")),
            service_name=_clean_operator(op_id, op_name),
            vehicle_number=(legs[0].get("ride_id") if legs else None),
            fare_class="Standard",
            depart_ts=dep.get("date"),
            arrive_ts=arr.get("date"),
            duration_min=duration_min,
            transfers=transfers,
            is_direct=is_direct,
            origin_stop=stop_name(dep),
            dest_stop=stop_name(arr),
            source_url=SEARCH,
            raw_ref=raw_ref,
        )

    # --- fallback rows ------------------------------------------------------

    def _status_row(self, ctx: Context, travel_date: date, direction: str,
                    o: str, d: str, status: str,
                    raw_ref: str | None = None,
                    note: str | None = None) -> FareObservation:
        return FareObservation(
            snapshot_at=ctx.snapshot_at, snapshot_date=ctx.snapshot_date,
            travel_date=travel_date, direction=direction,
            origin_code=o, origin_name=_city(o),
            dest_code=d, dest_name=_city(d),
            mode=MODE_BUS, operator="FlixBus/Greyhound",
            source="global.api.flixbus.com",
            status=status, source_url=SEARCH, raw_ref=raw_ref, notes=note,
        )

    def _error_row(self, ctx: Context, travel_date: date, direction: str,
                   err: str) -> FareObservation:
        o, d = ("PHL", "NYP") if direction == "outbound" else ("NYP", "PHL")
        return self._status_row(ctx, travel_date, direction, o, d,
                                STATUS_ERROR, note=err[:300])


# --- helpers ----------------------------------------------------------------

def _city(code: str) -> str:
    return "Philadelphia, PA" if code == "PHL" else "New York, NY"


# Flix operator ids seen on this corridor. Mapping by id, not by display
# name: an earlier version matched substrings against a "FlixBus/Greyhound"
# fallback string, which contains "greyhound", so every row was labelled
# Greyhound regardless of who actually ran the bus.
OPERATOR_IDS = {"flixus": "FlixBus", "grey": "Greyhound"}


def _clean_operator(op_id: str | None, name: str | None) -> str:
    if op_id and op_id in OPERATOR_IDS:
        return OPERATOR_IDS[op_id]
    n = (name or "").strip()
    low = n.lower()
    if "greyhound" in low:
        return "Greyhound"
    if "flix" in low:
        return "FlixBus"
    return n or (op_id or "unknown")


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _sample_across_day(rows: list[FareObservation],
                       target_hours: list[int]) -> list[FareObservation]:
    """Keep the departure nearest each target hour, per operator.

    Preserves the shape of the day without querying/storing all ~47 rows for
    dates that are still weeks out.
    """
    if not rows:
        return rows
    best: dict[tuple[str, int], FareObservation] = {}
    for r in rows:
        if r.depart_hour is None:
            best[(r.operator, -1)] = r
            continue
        target = min(target_hours, key=lambda t: abs(t - r.depart_hour))
        key = (r.operator, target)
        cur = best.get(key)
        if cur is None or cur.depart_hour is None or \
                abs(target - r.depart_hour) < abs(target - cur.depart_hour):
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.operator, r.depart_ts or ""))
