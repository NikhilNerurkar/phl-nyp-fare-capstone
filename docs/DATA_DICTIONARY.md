# Data dictionary — PHL ↔ NYP fare observations

Team 2 · BUDT770 Capstone · sponsor: Amtrak Revenue Products & Business Planning

One row = **one price, for one departure, observed at one moment**. Every
source normalizes into this shape, which is what makes cross-mode comparison
defensible.

## Governing rules

1. **Nothing is invented.** A field we could not observe is `NULL`. A failed
   query is recorded with `status='error'` and a `NULL` price — never imputed.
2. **`status` is a signal, not an error flag.** `sold_out` in particular is a
   demand observation the sponsor asked us to keep.
3. **Raw payloads are retained** under `data/raw/<snapshot_date>/<source>/`, so
   any row can be re-derived if a parsing rule turns out wrong.
4. **Re-running a day repairs it.** `observation_id` excludes price, so a second
   run the same day updates rows in place instead of duplicating them.

## Columns

### When we looked
| Column | Type | Notes |
|---|---|---|
| `snapshot_at` | ISO8601 UTC | Exact instant of collection |
| `snapshot_date` | date | Local calendar date of the run |
| `observation_id` | text | SHA1 of the identity tuple; primary key |

### Which trip
| Column | Type | Notes |
|---|---|---|
| `travel_date` | date | Date of departure |
| `direction` | text | `outbound` = PHL→NYP, `inbound` = NYP→PHL |
| `origin_code` / `dest_code` | text | `PHL` / `NYP` |
| `origin_name` / `dest_name` | text | City as the source reported it |
| `origin_stop` / `dest_stop` | text | Actual terminal or station used |

### Which service
| Column | Type | Notes |
|---|---|---|
| `mode` | text | `rail` · `bus` · `air` · `car` |
| `operator` | text | Normalized: `Amtrak`, `FlixBus`, `Greyhound`, `Megabus`, `Peter Pan` |
| `service_name` | text | **Key for internal Amtrak comparison**: `Acela`, `Northeast Regional`, `Keystone`, … |
| `vehicle_number` | text | Train number, flight number, or carrier ride id |
| `fare_class` | text | `Coach`, `Business`, `First`, `Standard` |
| `fare_bucket` | text | Amtrak yield bucket: `Saver`, `Value`, `Flexible` |

### The price
| Column | Type | Notes |
|---|---|---|
| `price_usd` | float | **Base fare, fees excluded — use this for comparisons** |
| `price_with_fees_usd` | float | Checkout price where the source exposes it |
| `currency` | text | Always `USD` |
| `status` | text | See below |

`status` values: `ok` (real bookable price) · `sold_out` (service runs, no seats)
· `no_service` (source says nothing runs) · `error` (we failed to observe;
price is NULL) · `modeled` (computed from documented inputs, **not scraped**).

> Any row with `status='modeled'` is a calculation, not an observation. Filter
> these out of "observed fare" analysis, and label them in any chart.

### Schedule
| Column | Type | Notes |
|---|---|---|
| `depart_ts` / `arrive_ts` | ISO8601 + offset | Local time with UTC offset. Megabus returns naive times; we attach the Eastern offset, DST-aware |
| `duration_min` | int | Minutes |
| `transfers` | int | 0 = direct |
| `is_direct` | bool | |
| `seats_remaining` | int | Only where exposed (low-stock hints) |

### Derived (computed at write time, never scraped)
| Column | Type | Notes |
|---|---|---|
| `dbd` | int | **Days before departure** = `travel_date − snapshot_date` |
| `travel_dow` | int | 0 = Monday … 6 = Sunday |
| `is_weekend` | bool | `travel_dow >= 5` |
| `depart_hour` | int | Hour of departure, local |

Because we snapshot **daily**, the standard milestones (3, 5, 7, 14, 21, 28 DBD)
are all present, and 60/90 DBD come free — no milestone is hard-coded.

### Provenance
| Column | Type | Notes |
|---|---|---|
| `source` | text | Host actually read, e.g. `global.api.flixbus.com` |
| `source_url` | text | Endpoint called |
| `raw_ref` | text | Path to the saved raw payload |
| `notes` | text | Error text or caveat |

## Known comparability caveats

### Not every row is a downtown-to-downtown trip — filter before comparing

Your framing document assumes 30th St ↔ Penn Station. Wanderu searches
**city to city**, so its results include products that are not substitutes for
that trip. Confirmed example from 2026-10-29:

| `origin_stop` → `dest_stop` | `price_usd` | `duration_min` |
|---|---|---|
| `JFK Airport - Terminal 4 Arrivals (Van)` → `Center City (Service is provided with a Van)` | 132.00 | 228 |
| `11th Ave (btw. 35th & 36th St.)` → `Philadelphia Mills - RED Lot` | 9.50 | 81 |

The first is an airport shuttle van; the second is the intercity bus. Both are
real OurBus products and both are correctly recorded — but averaging them
together produced a nonsense OurBus median of **$132**.

**Use `origin_stop` / `dest_stop` and `duration_min` to scope your analysis.**
A PHL↔NYP city-center trip runs roughly 75–180 minutes. Anything materially
longer is almost certainly a different product. This is exactly the kind of
decision that belongs in the cleaning layer, not the scraper — the scraper
records what the source said, and `tools/qa_report.py` surfaces the outliers.

### Aggregator prices run higher than operator prices

Same operator, same day, two sources (2026-10-29):

| Operator | Operator API | Wanderu | Gap |
|---|---|---|---|
| FlixBus | $23.14 | $27.61 | +19% |
| Greyhound | $22.61 | $28.04 | +24% |

Treat `source` as a dimension, not noise. For "what does a traveller pay on the
operator's own site", prefer the operator API rows. The gap itself is a finding
worth reporting.

### Other caveats

- **`price_usd` is the base fare.** Flix exposes a `+$3.99` platform fee
  separately; Megabus does not expose fees at all. Compare base-to-base.
- **Bus terminals differ.** Peter Pan/Greyhound use Port Authority; some Flix
  departures use other curbside stops. Not all "New York" arrivals are equal.
- **Megabus timestamps are naive.** We attach the Eastern offset ourselves. The
  collection window crosses the 1 Nov DST change, so the offset is derived per
  travel date rather than assumed.
- **Sampling is tiered.** Travel dates ≤14 DBD capture every departure; farther
  dates keep the departure nearest each of 06, 08, 12, 17, 19, 21h per operator.
  `dbd` tells you which regime a row came from — account for it before
  comparing counts across dates.

## Coverage status

See `docs/STATUS.md` for which sources are live and which are still blocked.
