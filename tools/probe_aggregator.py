"""Load an aggregator search page in a real browser and log its JSON calls.

Aggregators render results client-side, so the useful contract is whatever
XHR the page makes. We watch the network, keep every JSON response, and
report which ones look like they carry fares.

Usage:
    python tools/probe_aggregator.py wanderu
    python tools/probe_aggregator.py omio
    python tools/probe_aggregator.py <any-url>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)

PRESETS = {
    "wanderu": "https://www.wanderu.com/en-us/depart/philadelphia-pa/new-york-ny/2026-11-15/",
    "omio": "https://www.omio.com/search-frontend/results/"
            "?departurePosition=Philadelphia&arrivalPosition=New%20York"
            "&departureDate=15%2F11%2F2026&adults=1",
    "rome2rio": "https://www.rome2rio.com/map/Philadelphia/New-York",
}

# Words that suggest a payload actually carries fares.
FARE_HINTS = re.compile(
    r'"(price|fare|amount|totalPrice|priceInCents|cheapest)"', re.I)
RAIL_HINTS = re.compile(r'amtrak|acela|northeast regional|keystone', re.I)


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "wanderu"
    url = PRESETS.get(arg, arg)
    name = arg if arg in PRESETS else "custom"

    hits: list[dict] = []

    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        ctx = b.new_context(viewport={"width": 1440, "height": 950},
                            locale="en-US", timezone_id="America/New_York")
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct.lower():
                    return
                body = resp.text()
                if len(body) < 200:
                    return
                req = resp.request
                hits.append({
                    "url": resp.url,
                    "method": req.method,
                    "post_data": req.post_data or "",
                    "req_headers": {k: v for k, v in req.headers.items()
                                    if k.lower() not in ("cookie",)},
                    "status": resp.status,
                    "bytes": len(body),
                    "fare": bool(FARE_HINTS.search(body)),
                    "rail": bool(RAIL_HINTS.search(body)),
                    "body": body,
                })
            except Exception:
                pass

        page.on("response", on_response)

        print(f"loading {url[:100]} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=90000)

        for sel in ["#onetrust-accept-btn-handler",
                    "button:has-text('Accept')",
                    "button:has-text('Agree')"]:
            try:
                page.locator(sel).first.click(timeout=3000)
                print(f"  dismissed banner via {sel}")
                break
            except Exception:
                pass

        # Results stream in; give the page time to finish searching.
        print("  waiting for results to load ...")
        page.wait_for_timeout(35000)
        page.screenshot(path=str(OUT / f"{name}_results.png"), full_page=False)

        b.close()

    print(f"\n{len(hits)} JSON responses captured\n")
    interesting = [h for h in hits if h["fare"] or h["rail"]]
    interesting.sort(key=lambda h: -h["bytes"])

    for h in interesting[:12]:
        flags = ("FARE " if h["fare"] else "") + ("RAIL" if h["rail"] else "")
        print(f"  [{flags:<9}] {h['status']} {h['bytes']:>8}b  {h['url'][:95]}")

    if interesting:
        best = interesting[0]
        path = OUT / f"{name}_best.json"
        path.write_text(best["body"][:1500000], encoding="utf-8")
        print(f"\nlargest fare/rail payload -> {path}")
        print(f"\n=== HOW TO REPRODUCE THIS CALL ===")
        print(f"  {best['method']} {best['url']}")
        if best["post_data"]:
            bp = OUT / f"{name}_request_body.json"
            bp.write_text(best["post_data"], encoding="utf-8")
            print(f"  full body -> {bp}  ({len(best['post_data'])} chars)")
            try:
                pd = json.loads(best["post_data"])
                print("  body top-level keys:", list(pd.keys()))
                for k, v in pd.items():
                    if not isinstance(v, (dict, list)):
                        print(f"    {k} = {v}")
            except Exception:
                print(f"  body head: {best['post_data'][:400]}")
        print("  headers:")
        for k, v in sorted(best["req_headers"].items()):
            if k.lower().startswith((":", "sec-", "accept-encoding")):
                continue
            print(f"    {k}: {v[:110]}")
        try:
            data = json.loads(best["body"])
            print("\n=== TOP LEVEL KEYS ===")
            print(list(data.keys())[:40] if isinstance(data, dict)
                  else f"list[{len(data)}]")
        except Exception as e:
            print(f"  (not parseable: {e})")
    else:
        print("  no fare-looking JSON found")
        print(f"  screenshot -> {OUT / f'{name}_results.png'}")

    return 0 if interesting else 1


if __name__ == "__main__":
    raise SystemExit(main())
