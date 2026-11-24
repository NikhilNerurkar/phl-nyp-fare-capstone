"""Wanderu aggregator - the Amtrak solution, plus a cross-check on buses.

Why this source exists: Amtrak.com blocks automated fare collection outright
(see docs/STATUS.md). Wanderu resells Amtrak and exposes, in a single call,
every service that stops at both 30th St and Penn Station:

    USACL Acela          USNER Northeast Regional   USKYS Keystone
    USPEN Pennsylvanian  USCLN Carolinian           USPLM Palmetto
    USVTR Vermonter      USCRS Crescent             USSVS Silver Service

It also carries OurBus, which has no public API of its own, and returns
Greyhound/FlixBus/Peter Pan fares that act as an independent cross-check
against the operators' own APIs. Rows carry source='api.wanderu.com', so
disagreement between sources is measurable rather than hidden.

Transport: api.wanderu.com sits behind Cloudflare, so plain HTTP gets a 403
challenge. We open one real browser session per run and let the page issue
its own fetch() calls - exactly what happens when a person searches. No
evasion of any kind; see docs/STATUS.md.

What this source cannot give us: Amtrak's fare buckets (Saver / Value /
Flexible). Those are only on Amtrak.com. fare_bucket stays NULL here.
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..models import (FareObservation, MODE_BUS, MODE_RAIL, STATUS_ERROR,
                      STATUS_NO_SERVICE, STATUS_OK)
from .base import Context, Source
from .flix import _sample_across_day

API = "https://api.wanderu.com/v2/psearch.json"
SEARCH_PAGE = ("https://www.wanderu.com/en-us/depart/"
               "philadelphia-pa/new-york-ny/{date}/")

# carrier code -> (operator, mode, service_name)
CARRIERS: dict[str, tuple[str, str, str]] = {
    # --- Amtrak: every service calling at both stations -------------------
    "USACL": ("Amtrak", MODE_RAIL, "Acela"),
    "USNER": ("Amtrak", MODE_RAIL, "Northeast Regional"),
    "USKYS": ("Amtrak", MODE_RAIL, "Keystone Service"),
    "USPEN": ("Amtrak", MODE_RAIL, "Pennsylvanian"),
    "USCLN": ("Amtrak", MODE_RAIL, "Carolinian"),
    "USPLM": ("Amtrak", MODE_RAIL, "Palmetto"),
    "USVTR": ("Amtrak", MODE_RAIL, "Vermonter"),
    "USCRS": ("Amtrak", MODE_RAIL, "Crescent"),
    "USSVS": ("Amtrak", MODE_RAIL, "Silver Service"),
    "USSIL": ("Amtrak", MODE_RAIL, "Silver Service"),
    "USCRD": ("Amtrak", MODE_RAIL, "Cardinal"),
    "USDWE": ("Amtrak", MODE_RAIL, "Downeaster"),
    # Wanderu's generic Amtrak bucket: a real Amtrak fare whose specific
    # service it did not name. Kept distinct so it never silently inflates
    # the Acela/Regional/Keystone counts.
    "AMT":   ("Amtrak", MODE_RAIL, "Amtrak (service unspecified)"),
    # --- bus --------------------------------------------------------------
    "GLI":   ("Greyhound", MODE_BUS, "Greyhound"),
    "USFLX": ("FlixBus", MODE_BUS, "FlixBus"),
    "USPPL": ("Peter Pan", MODE_BUS, "Peter Pan"),
    "USOUR": ("OurBus", MODE_BUS, "OurBus"),
    "BBB":   ("Best Bus", MODE_BUS, "Best Bus"),
    "USPNY": ("Panda NY", MODE_BUS, "Panda NY"),
    "USTAZ": ("Tripper Bus", MODE_BUS, "Tripper Bus"),
    # Wanderu's label for an itinerary stitched from two carriers.
    "MIX":   ("Mixed carriers", MODE_BUS, "Mixed carriers"),
}

# Issue the search from inside the page so it carries the session the site
# itself established. This is the page's own API, called the page's own way.
FETCH_JS = """
async ([url, body]) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'accept': 'application/json, text/plain, */*',
      'content-type': 'text/plain',
    },
    body: JSON.stringify(body),
    credentials: 'include',
  });
  const text = await r.text();
  return { status: r.status, body: text };
}
"""


class WanderuSource(Source):
    name = "wanderu"
    mode = MODE_RAIL   # mixed; set per row

    def collect(self, ctx: Context) -> list[FareObservation]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            ctx.log.error("playwright not installed; run: pip install playwright "
                          "&& python -m playwright install chromium")
            return []

        out: list[FareObservation] = []
        legs = list(ctx.legs())
        if not legs:
            return out

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            bctx = browser.new_context(
                viewport={"width": 1440, "height": 950},
                locale="en-US", timezone_id="America/New_York")
            page = bctx.new_page()

            template = self._bootstrap(ctx, page, legs[0][0])
            if template is None:
                ctx.log.error("could not bootstrap a Wanderu session")
                browser.close()
                return out

            for travel_date, direction in legs:
                try:
                    out.extend(self._one_leg(ctx, page, template,
                                             travel_date, direction))
                except Exception as e:
                    ctx.log.warning("wanderu %s %s failed: %s",
                                    travel_date, direction, e)
                    out.append(self._status_row(ctx, travel_date, direction,
                                                STATUS_ERROR, note=str(e)[:300]))
            browser.close()
        return out

    # --- session bootstrap --------------------------------------------------

    def _bootstrap(self, ctx: Context, page, first_date: date) -> dict | None:
        """Load one real search page and capture the request body it sends.

        That body carries the anonymous session token and the origin/dest
        place objects, which we then reuse for every other query this run.
        """
        captured: list[str] = []

        def on_request(req):
            if "psearch.json" in req.url and req.method == "POST":
                if req.post_data:
                    captured.append(req.post_data)

        page.on("request", on_request)
        url = SEARCH_PAGE.format(date=first_date.isoformat())
        ctx.log.info("bootstrapping Wanderu session: %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)

        for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept')"]:
            try:
                page.locator(sel).first.click(timeout=3000)
                break
            except Exception:
                pass

        # Wait for the page to fire its own search.
        for _ in range(40):
            if captured:
                break
            page.wait_for_timeout(1000)
        page.remove_listener("request", on_request)

        if not captured:
            return None
        try:
            tmpl = json.loads(captured[0])
        except Exception:
            return None
        ctx.log.info("captured Wanderu session template (%d chars)",
                     len(captured[0]))
        return tmpl

    # --- one (date, direction) ---------------------------------------------

    def _one_leg(self, ctx: Context, page, template: dict,
                 travel_date: date, direction: str) -> list[FareObservation]:
        body = copy.deepcopy(template)
        body["departDatetime"] = travel_date.isoformat()
        body["batchId"] = str(uuid.uuid4())
        if direction == "inbound":
            body["originPlace"], body["destPlace"] = (
                template["destPlace"], template["originPlace"])

        res = page.evaluate(FETCH_JS, [API, body])
        if res["status"] != 200:
            raise RuntimeError(f"HTTP {res['status']}: {res['body'][:160]}")

        payload = json.loads(res["body"])
        raw_ref = ctx.store.save_raw(
            self.name, f"{travel_date}_{direction}", payload, ctx.snapshot_date)

        trips = payload.get("result") or []
        o, d = ("PHL", "NYP") if direction == "outbound" else ("NYP", "PHL")
        rows = [r for r in
                (self._to_observation(ctx, t, travel_date, direction, o, d,
                                      raw_ref) for t in trips)
                if r]

        if not rows:
            rows.append(self._status_row(ctx, travel_date, direction,
                                         STATUS_NO_SERVICE, raw_ref=raw_ref))
            return rows

        # Tiering applies per operator, so Acela doesn't crowd out Regional.
        if not ctx.is_full_sweep(travel_date):
            rail = [r for r in rows if r.mode == MODE_RAIL]
            bus = [r for r in rows if r.mode != MODE_RAIL]
            rows = (_sample_across_day(rail, ctx.config.sample_hours)
                    + _sample_across_day(bus, ctx.config.sample_hours))
        ctx.log.debug("wanderu %s %s -> %d rows", travel_date, direction, len(rows))
        return rows

    # --- mapping ------------------------------------------------------------

    def _to_observation(self, ctx: Context, t: dict, travel_date: date,
                        direction: str, o: str, d: str,
                        raw_ref: str) -> FareObservation | None:
        code = t.get("carrier")
        operator, mode, service = CARRIERS.get(
            code, (code or "Unknown", MODE_BUS, code or "Unknown"))

        # Anything Wanderu sourced from the Amtrak spider is Amtrak rail,
        # even if we haven't mapped the specific train yet.
        spider = t.get("spider_params") or ""
        if spider.startswith("AMT,") and operator not in ("Amtrak",):
            operator, mode = "Amtrak", MODE_RAIL
            service = service or code

        price = _f(t.get("price"))
        depart_ts = _local_iso(t.get("depart_datetime_utc"),
                               t.get("depart_timezone_offset"))
        arrive_ts = _local_iso(t.get("arrive_datetime_utc"),
                               t.get("arrive_timezone_offset"))

        dur = t.get("duration")
        duration_min = int(round(dur * 60)) if isinstance(dur, (int, float)) else None

        transfers = t.get("transfers")
        return FareObservation(
            snapshot_at=ctx.snapshot_at,
            snapshot_date=ctx.snapshot_date,
            travel_date=travel_date,
            direction=direction,
            origin_code=o, origin_name=t.get("depart_cityname") or _city(o),
            dest_code=d, dest_name=t.get("arrive_cityname") or _city(d),
            mode=mode,
            operator=operator,
            source="api.wanderu.com",
            status=STATUS_OK if price is not None else STATUS_NO_SERVICE,
            price_usd=price,
            service_name=service,
            vehicle_number=_train_no(t.get("carrier_trip_id")),
            # Wanderu does not expose Amtrak's Saver/Value/Flexible buckets.
            fare_class=None,
            fare_bucket=None,
            depart_ts=depart_ts,
            arrive_ts=arrive_ts,
            duration_min=duration_min,
            transfers=transfers,
            is_direct=(transfers == 0) if transfers is not None else None,
            seats_remaining=t.get("seats"),
            origin_stop=t.get("depart_name"),
            dest_stop=t.get("arrive_name"),
            source_url=API,
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
            mode=MODE_RAIL, operator="Amtrak", source="api.wanderu.com",
            status=status, source_url=API, raw_ref=raw_ref, notes=note,
        )


# --- helpers ----------------------------------------------------------------

def _city(code: str) -> str:
    return "Philadelphia, PA" if code == "PHL" else "New York, NY"


def _train_no(v: Any) -> str | None:
    """Keep real train numbers; drop opaque carrier hashes.

    Amtrak rows carry a genuine train number (150, 2248). Bus rows carry a
    64-char hash, which is noise in a 'vehicle_number' column.
    """
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= 12 else None


def _local_iso(epoch: Any, offset_hours: Any) -> str | None:
    """Wanderu gives epoch UTC plus the stop's offset; emit local ISO."""
    if epoch is None:
        return None
    try:
        off = int(offset_hours) if offset_hours is not None else 0
        tz = timezone(timedelta(hours=off))
        return datetime.fromtimestamp(int(epoch), tz).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
