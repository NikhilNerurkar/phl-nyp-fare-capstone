"""Open the Amtrak depart-date picker and dump the calendar's real DOM."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)

JS = """
() => {
  const vis = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.offsetParent !== null; };
  const out = { headers: [], days: [], navs: [], containers: [] };
  document.querySelectorAll('[class*=calendar], [class*=datepicker], [role=dialog]')
    .forEach(e => { if (vis(e)) out.containers.push(
      (e.className||'').toString().slice(0,70)); });
  document.querySelectorAll('td, button, div[role=gridcell], [aria-label]')
    .forEach(e => {
      if (!vis(e)) return;
      const t = (e.innerText||'').trim();
      const al = e.getAttribute('aria-label') || '';
      if (/^\\d{1,2}$/.test(t) && out.days.length < 12)
        out.days.push({ tag: e.tagName, text: t, aria: al,
                        cls: (e.className||'').toString().slice(0,55) });
      if (/(next|previous|prev)/i.test(al) && out.navs.length < 8)
        out.navs.push({ tag: e.tagName, aria: al,
                        cls: (e.className||'').toString().slice(0,55) });
      if (/(november|october|december)\\s*20\\d\\d/i.test(t) && t.length < 40
          && out.headers.length < 6)
        out.headers.push({ tag: e.tagName, text: t,
                           cls: (e.className||'').toString().slice(0,55) });
    });
  out.containers = out.containers.slice(0, 8);
  return out;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=False, slow_mo=200)
    ctx = b.new_context(viewport={"width": 1440, "height": 950},
                        locale="en-US", timezone_id="America/New_York")
    page = ctx.new_page()
    page.goto("https://www.amtrak.com/home.html",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    try:
        page.locator("#onetrust-accept-btn-handler").click(timeout=4000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    page.locator("input.departed-picker:visible").first.click(force=True)
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "cal_open.png"))
    print(json.dumps(page.evaluate(JS), indent=2)[:5000])
    print(f"\nscreenshot -> {OUT / 'cal_open.png'}")
    b.close()
