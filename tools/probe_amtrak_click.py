"""Click the From field, then screenshot + dump what actually appeared."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
OUT.mkdir(parents=True, exist_ok=True)

JS = """
() => {
  const vis = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.offsetParent !== null;
  };
  const out = { inputs: [], listish: [] };
  document.querySelectorAll('input').forEach(e => {
    if (vis(e)) out.inputs.push({
      id: e.id || null, name: e.getAttribute('name'),
      aria: e.getAttribute('aria-label'),
      cls: (e.className || '').toString().slice(0, 70),
    });
  });
  document.querySelectorAll('li, [role=option], [role=listbox], mat-option')
    .forEach(e => {
      if (vis(e) && (e.innerText || '').trim())
        out.listish.push({
          tag: e.tagName, role: e.getAttribute('role'),
          cls: (e.className || '').toString().slice(0, 60),
          text: (e.innerText || '').trim().slice(0, 45),
        });
    });
  out.listish = out.listish.slice(0, 25);
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

    print("=== BEFORE CLICK ===")
    page.screenshot(path=str(OUT / "step0_home.png"))

    page.locator('input[aria-label="From"]:visible').first.click()
    page.wait_for_timeout(2500)
    print("=== AFTER CLICKING 'From' ===")
    page.screenshot(path=str(OUT / "step1_from_clicked.png"))
    print(json.dumps(page.evaluate(JS), indent=2)[:4000])

    # Now type and see what the suggestion list looks like.
    page.keyboard.type("Philadelphia", delay=150)
    page.wait_for_timeout(3000)
    print("\n=== AFTER TYPING 'Philadelphia' ===")
    page.screenshot(path=str(OUT / "step2_typed.png"))
    print(json.dumps(page.evaluate(JS), indent=2)[:4000])

    print(f"\nscreenshots -> {OUT}")
    b.close()
