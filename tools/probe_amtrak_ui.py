"""Explore the Amtrak booking widget and capture the fare response it makes.

Rather than forging an API call, we drive the real search form the way a
traveller does and listen for the response the page itself fetches. No
evasion: a real browser, real interaction, human-paced.

Pass --dump to print the form controls instead of searching.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)


def dump_controls(page) -> None:
    info = page.evaluate("""
    () => {
      const pick = el => ({
        tag: el.tagName,
        type: el.type || null,
        id: el.id || null,
        name: el.getAttribute('name'),
        cls: (el.className || '').toString().slice(0, 80),
        ph: el.getAttribute('placeholder'),
        aria: el.getAttribute('aria-label'),
        text: (el.innerText || '').trim().slice(0, 50),
      });
      const vis = el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && el.offsetParent !== null;
      };
      const out = { visible_inputs: [], visible_buttons: [], tabs: [] };
      document.querySelectorAll('input').forEach(e => {
        if (vis(e)) out.visible_inputs.push(pick(e));
      });
      document.querySelectorAll('button, a[role=button]').forEach(e => {
        const p = pick(e);
        if (vis(e) && (p.text || p.aria)) out.visible_buttons.push(p);
      });
      document.querySelectorAll('[role=tab], .tab, [class*=tab]').forEach(e => {
        if (vis(e) && (e.innerText || '').trim())
          out.tabs.push((e.innerText || '').trim().slice(0, 40));
      });
      return out;
    }
    """)
    print(json.dumps(info, indent=2)[:9000])


def main() -> int:
    dump = "--dump" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=250)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 950},
            locale="en-US", timezone_id="America/New_York")
        page = ctx.new_page()

        captured: list[dict] = []

        def on_response(resp):
            if "journey-solution-option" in resp.url or "journey" in resp.url.lower():
                try:
                    captured.append({"url": resp.url, "status": resp.status,
                                     "body": resp.text()[:1500000]})
                    print(f"  [captured] {resp.status} {resp.url[:90]}")
                except Exception:
                    pass

        page.on("response", on_response)

        print("opening amtrak.com ...")
        page.goto("https://www.amtrak.com/home.html",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        # Dismiss a cookie/consent banner if one is in the way.
        for sel in ["#onetrust-accept-btn-handler",
                    "button:has-text('Accept')",
                    "button:has-text('I Accept')"]:
            try:
                if page.locator(sel).first.is_visible(timeout=1500):
                    page.locator(sel).first.click()
                    print(f"  dismissed banner via {sel}")
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

        if dump:
            dump_controls(page)
            page.wait_for_timeout(2000)
            browser.close()
            return 0

        depart = sys.argv[1] if len(sys.argv) > 1 else "11/15/2026"
        frm = sys.argv[2] if len(sys.argv) > 2 else "PHL"
        to = sys.argv[3] if len(sys.argv) > 3 else "NYP"

        CITY = {"PHL": "Philadelphia", "NYP": "New York"}

        def fill_station(label: str, code: str) -> None:
            """Typing goes into the same input; suggestions are div[role=option].

            The autocomplete matches on city name, not the station code, so we
            type the city and then select the option carrying the code.
            """
            box = page.locator(f'input[aria-label="{label}"]:visible').first
            box.click()
            page.wait_for_timeout(1000)
            box.fill("")
            box.type(CITY.get(code, code), delay=150)   # human-paced
            page.wait_for_timeout(2800)

            opts = page.locator('[role="option"]:visible')
            n = opts.count()
            for i in range(n):
                txt = (opts.nth(i).inner_text() or "").strip()
                if f"({code})" in txt:
                    opts.nth(i).click()
                    print(f"  {label}: picked '{txt[:50]}'")
                    page.wait_for_timeout(1200)
                    return
            if n:
                txt = (opts.first.inner_text() or "").strip()
                opts.first.click()
                print(f"  {label}: fell back to '{txt[:50]}'")
                page.wait_for_timeout(1200)
                return
            raise RuntimeError(f"no station suggestions for {code}")

        print(f"searching {frm} -> {to} on {depart}")
        fill_station("From", frm)
        fill_station("To", to)

        # Typing never reached the Angular model, so pick the day from the
        # ng-bootstrap calendar instead. Day cells carry a full aria-label.
        from datetime import datetime as _dt
        target = _dt.strptime(depart, "%m/%d/%Y").date()
        label = f"{target:%A}, {target:%B} {target.day}, {target.year}"

        # The floating <label> overlaps this input, so force past that quirk.
        page.locator("input.departed-picker:visible").first.click(force=True)
        page.wait_for_timeout(1800)

        picked = False
        for _ in range(14):                      # walk forward a month at a time
            cell = page.locator(
                f'div.ngb-dp-day[aria-label="{label}"]').first
            try:
                if cell.count() and cell.is_visible(timeout=800):
                    cell.click()
                    picked = True
                    print(f"  date: clicked '{label}'")
                    break
            except Exception:
                pass
            try:
                page.locator(
                    'button[aria-label="Next month"]:visible').first.click()
                page.wait_for_timeout(700)
            except Exception:
                break
        if not picked:
            print(f"  !! could not find calendar cell for '{label}'")
        page.wait_for_timeout(1200)

        # Show every candidate search button with its real test hooks.
        cands = page.evaluate("""
        () => {
          const vis = el => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && el.offsetParent !== null; };
          const out = [];
          document.querySelectorAll('button, input[type=submit], a').forEach(e => {
            const t = (e.innerText || e.value || '').trim();
            if (vis(e) && /find\\s*trains/i.test(t))
              out.push({ text: t.slice(0, 30), tag: e.tagName,
                         testid: e.getAttribute('amt-auto-test-id'),
                         julie: e.getAttribute('data-julie'),
                         disabled: e.disabled === true,
                         cls: (e.className || '').toString().slice(0, 70) });
          });
          return out;
        }
        """)
        print("  search button candidates:", json.dumps(cands))

        clicked = False
        for sel in ['[amt-auto-test-id*="find-trains" i]',
                    'button:has-text("FIND TRAINS")',
                    '[data-julie*="search" i]']:
            try:
                b = page.locator(f"{sel}:visible").first
                if b.is_visible(timeout=2000):
                    b.scroll_into_view_if_needed()
                    b.click(force=True)
                    clicked = True
                    print(f"  clicked search via {sel}")
                    break
            except Exception as e:
                print(f"  ({sel} -> {type(e).__name__})")
        if not clicked:
            print("  !! could not click the search button")

        # Let the results page load and make its fare call.
        page.wait_for_timeout(22000)
        print(f"  url now: {page.url[:110]}")

        if captured:
            best = max(captured, key=lambda c: len(c["body"]))
            (OUT / "amtrak_ui_raw.json").write_text(best["body"], encoding="utf-8")
            print(f"\n  captured {len(captured)} response(s); "
                  f"largest {len(best['body'])} bytes -> amtrak_ui_raw.json")
            print(f"  status={best['status']} url={best['url'][:110]}")
            try:
                data = json.loads(best["body"])
                print("\n=== TOP LEVEL KEYS ===")
                print(list(data.keys()) if isinstance(data, dict) else type(data))
                print("\n=== STRUCTURE ===")
                shape(data)
            except Exception as e:
                print(f"  (not JSON: {e})")
        else:
            print("\n  no fare response captured")
            page.screenshot(path=str(OUT / "amtrak_ui.png"), full_page=True)
            print(f"  screenshot -> {OUT / 'amtrak_ui.png'}")

        browser.close()
        return 0 if captured else 1


def shape(obj, depth=0, max_depth=5):
    pad = "  " * depth
    if depth > max_depth:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:30]:
            if isinstance(v, (dict, list)):
                n = f"[{len(v)}]" if isinstance(v, list) else ""
                print(f"{pad}{k}{n}:")
                shape(v, depth + 1, max_depth)
            else:
                print(f"{pad}{k} = {str(v)[:60]}")
    elif isinstance(obj, list) and obj:
        shape(obj[0], depth, max_depth)


if __name__ == "__main__":
    raise SystemExit(main())
