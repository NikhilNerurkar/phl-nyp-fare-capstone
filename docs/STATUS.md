# Source status — what works, what doesn't

Last updated: 2026-10-29

## Working and verified against live endpoints

| Source | Operators | Endpoint | Evidence |
|---|---|---|---|
| `flix` | **FlixBus**, **Greyhound** | `global.api.flixbus.com/search/service/v4/search` | 47 priced rows for one date; $17.49–$63.99 |
| `megabus` | **Peter Pan** (see note) | `us.megabus.com/journey-planner/api/journeys` | 33 priced rows over 2 dates; $18.99–$31.99 |
| `wanderu` | **All Amtrak services**, **OurBus**, + cross-check on all buses | `api.wanderu.com/v2/psearch.json` | 491 rows over 2 dates; $8.50–$240.00; 441 priced |

### Amtrak — solved via Wanderu

Amtrak.com itself is unusable (below), but Wanderu resells Amtrak and returns
**every service calling at both 30th St and Penn Station**, with real train
numbers:

| Code | Service | Example trains | Observed range |
|---|---|---|---|
| `USACL` | Acela | 2216, 2218, 2248 | $131–240 |
| `USNER` | Northeast Regional | 66, 144, 150, 160 | $11–157 |
| `USKYS` | Keystone Service | 626, 656, 662 | $54–200 |
| `USPEN` | Pennsylvanian | 42 | $104 |
| `USCLN` | Carolinian | 80 | $104 |
| `USPLM` | Palmetto | 90 | $75 |
| `USVTR` | Vermonter | 54 | $157 |
| `USCRS` | Crescent | 20 | $127 |

This directly serves the sponsor's **internal Amtrak comparison** (Acela vs
Regional vs Keystone by booking window).

**What it does not give us:** Amtrak's fare buckets (Saver / Value /
Flexible). Those exist only on Amtrak.com, so `fare_bucket` is NULL on these
rows. If the sponsor can supply bucket data, that gap closes.

**Transport note:** `api.wanderu.com` is behind Cloudflare, so plain HTTP gets
a 403 challenge. The source opens one real browser session per run and lets
the page issue its own `fetch()` calls — what happens when a person searches.
No evasion.

### Bonus findings

- **OurBus** has no public API of its own, but Wanderu carries it (88 trips on
  one date) — so all intercity bus operators are covered after all.
- **Megabus PHL→NYC is operated by Peter Pan.** Every journey on the Megabus
  planner returns `carrier: "Peter Pan Bus Lines"` with Peter Pan route codes
  (PP04, PP0E). This is a real market fact, not a parsing bug.
- **Cross-source price comparison** now exists for free: Greyhound, FlixBus and
  Peter Pan fares arrive from both the operator API and Wanderu. The `source`
  column makes any disagreement measurable.

### Fixed bugs

- **Flix operator mis-labelling (found and fixed 2026-10-29).** Operator was
  derived by substring-matching a `"FlixBus/Greyhound"` fallback string, which
  contains `"greyhound"` — so all 1,870 rows in the first run were labelled
  Greyhound. Now mapped by operator id (`flixus` → FlixBus, `grey` →
  Greyhound). The affected day was deleted and re-collected; raw payloads were
  untouched throughout, which is exactly why the raw archive exists.

## Blocked

### Amtrak direct (amtrak.com) — not usable, and no longer needed

**What was tried**

1. **Direct fare API.** `POST www.amtrak.com/dotcom/journey-solution-option`
   with the documented request body. Returned **403** (Akamai block page), even
   from a real Chromium window that had already loaded the homepage and held
   90 cookies. A bare `fetch()` lacks the interaction telemetry Akamai expects.
2. **Driving the real booking form.** A visible browser fills the form
   correctly — From = `Philadelphia, PA – William H Gray III 30th St. Sta (PHL)`,
   To = `New York, NY – Moynihan Train Hall at Penn Sta. (NYP)`, depart date
   selected from the ng-bootstrap calendar. The FIND TRAINS button
   (`amt-auto-test-id="fare-finder-findtrains-button"`) is present and enabled.
   **Clicking it silently does nothing** — no navigation, no network call, no
   validation error.

**Read on this:** Amtrak detects the automated session and no-ops the submit.
`robots.txt` does not disallow `/dotcom/`, so this is bot protection rather
than a crawling policy.

**Explicitly not done:** no `navigator.webdriver` masking, no
`--disable-blink-features=AutomationControlled`, no user-agent spoofing, no
fingerprint patching. Defeating a bot check is out of scope for this project,
and a scraper built on evasion would break constantly anyway.

**Resolution:** superseded by the `wanderu` source above, which supplies every
Amtrak service and fare on this route. Amtrak.com is no longer on the critical
path.

**One gap remains:** fare buckets (Saver / Value / Flexible). Worth raising at
the next sponsor check-in, since Amtrak Revenue Products owns that data
directly and a sanctioned feed beats any scraper.

### Not yet implemented

- `air` — PHL → EWR/LGA/JFK. Google Flights is heavily protected; expect the
  same class of problem. The framing doc already flags air as a thin sample.
- `transit` — SEPTA + NJ Transit via Trenton. Fares are fixed and published,
  so these rows will be `status='modeled'`, not scraped.
- `driving` — rental scrape attempt with a documented driving-cost fallback.

## Collection-window note

Snapshots stop on `last_snapshot_date` (2026-12-10 in config). Travel dates on
or before that get a complete 0-DBD booking curve. Dates from Dec 11–31 are
**long-lead observations only** — they never reach the short-lead window. Say
so in any chart that mixes them. Extending collection is a one-line change.
