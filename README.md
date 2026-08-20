# watchledger

Data-driven watch market intelligence. Per-reference reports generated
**deterministically from raw data** — no AI, no handwritten copy, no manual
curation anywhere in the pipeline.

## Source of truth

```
data/raw/                          immutable raw payloads (verbatim API responses)
  index/references.json            reference index (MEW)
  index/auctions_full.json         auction dataset, single page (250-lot API cap)
  references/<slug>.json           per-reference detail (listing stats, listings, auction lots)
  manifest.json                    resolved slugs + fetch timestamp
data/ledger.sqlite                 derived, normalized view of the raw files
reports/<slug>.html                deterministic reports
```

Every normalized row in the ledger carries `source_url` and `fetched_at` of
the payload it came from. Every number in a report traces to its raw row.

**Guarantee:** rebuilding reports from an unchanged ledger produces
byte-identical output (verified via md5 in this repo's history). Nothing in
the report is generated, guessed, or LLM-produced.

## Run

```
make all          # fetch -> db -> report
make fetch        # pull raw JSON from MEW public API (keyless, free)
make db           # normalize raw files into data/ledger.sqlite
make report       # generate reports/*.html
make serve        # serve the website (stdlib http.server, port 8040, PORT=... to change)
```

## Website

`make serve` runs a zero-dependency stdlib web server (`src/server.py`):

- `/` — homepage per `design.md`: editorial serif + Inter, warm ivory
  `#F7F6F2`, deep green `#1F5B48` accent. Hero search with live image
  suggestions, how-it-works, markets grid with real listing photos,
  recently-updated list, trust section
- `/reference/<slug>` — market report: observed range with band bar, typical
  price, "how to read this market" panel, live listings table with photos,
  dealer names, and deal / fair / above-market badges, plus auction hammers
- `/api/references.json` — index stats as JSON
- `/api/reference/<slug>.json` — one reference's full report dict as JSON
- `/raw/<path>` — browse the raw payload files: the source of truth, in the browser

Nothing is cached and nothing is generated at build time beyond the ledger:
every page is a deterministic view of `data/ledger.sqlite` at request time
(byte-identical HTML across requests, verified via md5).

Design system (from the page design brief): warm editorial ivory background,
charcoal text, muted deep-green accent used sparingly, DM Serif Display for
watch names / headlines, Inter for all data and UI. The market range is the
visual centrepiece on every model page; deal labels are cautious and
evidence-backed ("potential deal", "within observed range", "above market").

## Data sources (all free, no API key)

- MostExpensiveWatches public API — references (752, of which the API exposes
  250 via `limit`), per-reference listing stats + listings + matched auction
  lots, and a global auction dataset (1,156 documented lots; the API returns
  a single fixed page of 250).

Verified limitations (documented, not hidden):

- `page` / `offset` params on `/api/references` and `/api/auctions` are
  ignored — only the first 250 rows are reachable.
- eBay sold-listings scraping is bot-blocked; third-party sold-data APIs
  (trawl.dev, Parse.bot, Retailed) require API keys, so they are excluded
  from this free-only POC.

## Adding a target reference

Edit `TARGETS` in `src/config.py` — (brand, reference) pairs. Resolution to
MEW slugs happens at fetch time via `/api/references/resolve`, filtered by
normalized brand + reference; unresolved targets are skipped with a message.

## Notes on data quality

- `listing_stats.count` in MEW payloads counts all matching listings
  (e.g. 575 for 126610LN); the per-reference payload only returns a sample
  of 24 listings. The report's medians are computed over the returned
  sample and labeled accordingly.
- Auction lots linked to a reference come from MEW's matched `auction_lots`
  on the reference page; the global 250-lot page is stored for joins but
  never clobbers reference-linked rows (`INSERT OR IGNORE`).