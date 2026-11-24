"""Capture one real Amtrak fare response and dump its structure.

The public recon for this endpoint never pinned the response schema, so we
discover it from a live 200 rather than guessing.

Approach: open a genuine Chromium window, let the site set its cookies
normally, then issue the search with fetch() from inside that page context.

No anti-detection measures are used here - no webdriver masking, no
automation-flag stripping, no user-agent spoofing. This is a real browser
making a real request at human pace. If the site declines to serve it, we
take that as an answer and fall back to another source.
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)

ENDPOINT = "https://www.amtrak.com/dotcom/journey-solution-option"


def body(origin: str, dest: str, depart_iso: str) -> dict:
    return {
        "journeyRequest": {
            "fare": {"pricingUnit": "DOLLARS"},
            "type": "OW",
            "journeyLegRequests": [{
                "origin": {"code": origin,
                           "schedule": {"departureDateTime": depart_iso}},
                "destination": {"code": dest},
                "passengers": [{"id": "P1", "type": "F", "initialType": "adult"}],
            }],
            "customer": {"tierStatus": "MEMBER"},
            "isPassRider": False,
            "isCorporateTraveller": False,
            "tripTags": True,
            "singleAdultFare": True,
            "cascadesWSDOTFilter": False,
        },
        "initialJourneyLegOnly": False,
        "reservableAccomodationOptions": "ALL",
    }


JS = """
async ([url, payload, traceId]) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/plain, */*',
      'x-amtrak-trace-id': traceId,
    },
    body: JSON.stringify(payload),
    credentials: 'include',
  });
  const text = await r.text();
  return { status: r.status, body: text.slice(0, 2000000) };
}
"""


def shape(obj, depth=0, max_depth=6):
    """Print a compact structural outline of unknown JSON."""
    pad = "  " * depth
    if depth > max_depth:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            if isinstance(v, (dict, list)):
                n = f"[{len(v)}]" if isinstance(v, list) else ""
                print(f"{pad}{k}{n}:")
                shape(v, depth + 1, max_depth)
            else:
                print(f"{pad}{k} = {str(v)[:70]}")
    elif isinstance(obj, list) and obj:
        shape(obj[0], depth, max_depth)


def main() -> int:
    depart = sys.argv[1] if len(sys.argv) > 1 else "2026-11-15T00:00:00"
    origin = sys.argv[2] if len(sys.argv) > 2 else "PHL"
    dest = sys.argv[3] if len(sys.argv) > 3 else "NYP"

    with sync_playwright() as p:
        # A real, visible browser window. Nothing hidden.
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = ctx.new_page()

        print("opening amtrak.com ...")
        page.goto("https://www.amtrak.com/home.html",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        print("cookies:", len(ctx.cookies()))

        trace_id = secrets.token_hex(28)
        print(f"POST {ENDPOINT}  {origin}->{dest} {depart}")
        res = page.evaluate(JS, [ENDPOINT, body(origin, dest, depart), trace_id])

        print("status:", res["status"], " bytes:", len(res["body"]))
        (OUT / "amtrak_raw.txt").write_text(res["body"][:200000], encoding="utf-8")

        if res["status"] != 200:
            print("--- body head ---")
            print(res["body"][:1200])
            browser.close()
            return 1

        data = json.loads(res["body"])
        (OUT / "amtrak_raw.json").write_text(
            json.dumps(data, indent=2)[:400000], encoding="utf-8")
        print(f"\nsaved -> {OUT / 'amtrak_raw.json'}\n")
        print("=== TOP LEVEL KEYS ===")
        print(list(data.keys()) if isinstance(data, dict) else type(data))
        print("\n=== STRUCTURE ===")
        shape(data)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
