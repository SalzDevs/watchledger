# WatchLedger

Data-driven watch market intelligence built from traceable public listings.

WatchLedger shows the market for a specific watch reference, separates exact matches from related watches, calculates a conservative observed asking-price range when evidence is sufficient, and refuses to classify prices when the evidence is weak.

> The product rule: **a polished price range is never more important than an honest one.**

---

## Current product behaviour

For each tracked reference, WatchLedger currently provides:

- Exact-reference and related-listing tabs
- Seller images, prices, availability, and direct source links
- A displayed asking-price range when minimum coverage is available
- Potential-deal, fair-price, and above-market labels for range-eligible listings
- A limited-data state when exact coverage is insufficient
- Source URL and fetch-time provenance
- A deterministic raw JSON → SQLite ledger → HTML report pipeline

The current implementation is a proof of concept. The next work must focus on **market-data quality before new visual features or broader source coverage**.

---

# Product truth rules

These rules are mandatory. They prevent WatchLedger from overstating what the data can support.

1. **Only strict, non-duplicate, sufficiently fresh configuration matches may influence a range.**
2. **Related watches never influence an exact-reference range.**
3. **A text-search result is not automatically an exact match.**
4. **A low listing count or low source diversity must produce a limited-data state.**
5. **Active asking prices are not completed sale prices.**
6. **Every classification must explain the evidence used.**
7. **Every displayed number must be traceable to a source observation and methodology version.**
8. **When evidence is insufficient, WatchLedger must say so clearly rather than guess.**

---

# Implementation roadmap

Complete these phases in order.

## Phase 1 — Secure and safe rendering

Before accepting more source data, protect the interface from untrusted third-party listing data.

### Required changes

- Add a central security helper module.
- Validate outbound listing and image URLs.
- Stop using `innerHTML` with source-provided values.
- Move inline JavaScript into static files.
- Use safe JSON data blocks for browser data.
- Add a strict Content Security Policy.
- Add XSS, unsafe-URL, and route-safety tests.

### Acceptance criteria

- A listing title containing `<script>alert(1)</script>` displays as text and never executes.
- `javascript:`, `data:`, `file:`, malformed, and credential-bearing URLs never render as links or images.
- The listing drawer and homepage search use DOM nodes plus `textContent`, never `innerHTML` for source data.
- HTML responses contain CSP, `X-Content-Type-Options`, `Referrer-Policy`, clickjacking protection, and a restrictive permissions policy.
- Server errors never expose SQLite paths, SQL, stack traces, or source internals.

See the security implementation guide for step-by-step code changes.

---

## Phase 2 — Canonical watch matching

### Problem

A reference string alone is not enough to establish a comparable market. Broad references can include materially different watches, including different dial, bracelet, material, case size, generation, and special configurations.

A current example of a bad result is a very broad exact-match range for a complicated reference family. A range spanning from a low five-figure price to several hundred thousand dollars should not be published as one market.

### Required data model

Create canonical reference and configuration entities.

```text
watch_reference
  id
  brand
  family
  model_name
  reference_number
  reference_normalized
  production_start_year
  production_end_year

watch_configuration
  id
  reference_id
  configuration_key
  case_material
  dial
  bracelet
  bezel
  case_size_mm
  production_variant
  active
```

Add matching fields to every listing.

```text
listing
  ...existing fields...
  canonical_reference_id
  canonical_configuration_id
  match_level
  match_confidence
  match_reason
  review_state
```

### Allowed match levels

| Match level | Meaning | Can affect the range? |
|---|---|---|
| `exact_configuration` | Exact reference and matching material/dial/bracelet configuration | Yes |
| `exact_reference_variant` | Exact reference but meaningful configuration difference | Only in a separate segmented range |
| `related_reference` | Same model family, different reference | No |
| `unverified` | Search/title suggests a match but source evidence is incomplete | No |
| `rejected` | Wrong watch, parts listing, unclear data, or bad match | No |

### Matching process

For every source listing:

1. Normalize its brand and reference value.
2. Prefer structured source reference fields over title text.
3. Compare normalized source reference to canonical reference exactly.
4. Parse supporting configuration fields: material, bracelet, dial, bezel, case size, year.
5. Assign a `match_level`.
6. Save the reason, for example:

```text
Exact source reference matched 126610LN; steel Oyster bracelet; black dial.
```

7. Send ambiguous listings to a manual-review queue.

### Acceptance criteria

- A related reference cannot appear in the exact-listings table.
- A related reference cannot influence an exact-reference range.
- The report displays exact configuration count separately from related listings.
- An exact reference with multiple configurations either shows segmented markets or a limited-data result.
- Every listing has a stored match reason.

---

## Phase 3 — Deduplicate listings before analytics

### Problem

The same watch can appear multiple times:

- Several source pages for the same dealer
- A dealer website and marketplace mirror
- Repeated API records
- Reposts after an asking-price change

Treating repeated rows as independent listings inflates supply, confidence, and the range calculation.

### Required data model

```text
listing_cluster
  id
  canonical_reference_id
  representative_listing_id
  cluster_confidence
  created_at
  updated_at

listing
  ...existing fields...
  source_name
  source_listing_id
  canonical_url
  listing_cluster_id
  listing_fingerprint
```

### Duplicate rules

#### Definite duplicate

Cluster immediately when one of these is true:

- Same `source_name` and same `source_listing_id`
- Same canonical URL
- Same dealer inventory identifier

#### Likely duplicate

Calculate a duplicate score when several signals agree:

- Same dealer
- Same exact configuration
- Same price, or price within 1%
- Same year
- Similar normalized title
- Same image URL or permitted image fingerprint
- Similar first-observed timestamp

### Analytics rule

Use only one representative listing per cluster in market calculations.

Keep all cluster members available in the evidence view.

### UI rule

Show users:

```text
1 unique listing
Also observed on 3 tracked source pages
```

Do not present the same watch as four competing market listings.

### Acceptance criteria

- Repeated dealer rows do not increase the market listing count.
- Repeated rows do not increase confidence.
- Every market calculation records the cluster representative IDs used.
- The evidence panel shows duplicate-grouping decisions.

---

## Phase 4 — Market eligibility and confidence gates

### Problem

A count alone does not make a market trustworthy. Twenty listings from one dealer should not be labelled `High confidence`. Five listings across four dealers may be diverse but still too small for a reliable range.

### Minimum eligibility gate

A report may publish an observed price range only if all requirements are met.

| Gate | Initial minimum |
|---|---:|
| Exact configuration clusters | 8 |
| Independent tracked dealers/sources | 3 |
| Listings with numeric asking price | 80% |
| Recently observed listings | 70% within 72 hours |
| Valid configuration match | 100% of calculation set |
| Duplicate clustered | Required |
| Outlier review complete | Required |

If a gate fails, show `Limited exact-match data` instead of a range.

### Confidence dimensions

Do not show one unexplained confidence label. Store and display three dimensions.

```text
Market coverage
  Number of valid non-duplicate exact configuration clusters

Source diversity
  Number of independent dealer/source entities

Freshness
  Percentage of calculation-set listings observed recently
```

Calculate an overall state using the lowest important dimension.

| Overall state | Example |
|---|---|
| High | 20+ clusters, 5+ sources, fresh, low dispersion |
| Medium | 8–19 clusters, 3+ sources, acceptable freshness |
| Limited | Adequate count but poor diversity, stale data, or high dispersion |
| Insufficient | Fewer than 8 usable exact configuration clusters |

### UI example

```text
Market coverage
High · 20 exact configuration listings

Source diversity
Limited · 1 tracked dealer

Overall confidence
Limited
```

### Acceptance criteria

- A one-dealer market can never show `High confidence`.
- Fewer than eight clusters cannot show a market range.
- The evidence panel includes coverage, diversity, and freshness.
- Every confidence result is reproducible from stored inputs.

---

## Phase 5 — Outlier handling and conservative pricing

### Problem

A raw minimum-to-maximum range is not a fair market range. It can be distorted by wrong configuration matches, stale listings, rare variants, missing accessories, typing errors, and outliers.

### Required calculation pipeline

For each target configuration:

1. Select active, fresh, exact-configuration listing clusters.
2. Exclude listings with missing/invalid prices.
3. Separate known tax states where possible.
4. Split into condition/completeness groups when sufficient data exists.
5. Calculate an initial median.
6. Calculate median absolute deviation (MAD).
7. Flag extreme deviations for exclusion or manual review.
8. Calculate a weighted median and weighted percentiles from the remaining clusters.
9. Save the complete calculation snapshot.

### Initial outlier rule

Use MAD rather than a normal average/standard deviation because watch prices are not normally distributed.

```text
median_price = median(prices)
mad = median(abs(price - median_price) for price in prices)
robust_z = 0.6745 * (price - median_price) / mad
```

Initial policy:

- Flag an item if absolute robust z-score is greater than `3.5`.
- Do not silently delete it.
- Save an exclusion reason.
- Allow manual review to restore it if the listing is a valid rare configuration.

### Weighted pricing

Start simple and documented.

```text
weight = freshness_weight
       × match_quality_weight
       × source_diversity_weight
       × data_completeness_weight
```

Possible initial weights:

| Factor | Weight |
|---|---:|
| Observed within 24h | 1.00 |
| Observed 24–72h ago | 0.85 |
| Observed 3–7 days ago | 0.60 |
| Exact configuration | 1.00 |
| Exact-reference variant | 0.00 for the strict range |
| Condition and set known | 1.00 |
| Important fields unknown | 0.75 |

### Displayed values

Use careful terminology:

```text
Observed exact-match asking-price range
Typical observed asking price
```

Do not call active listing prices `sale prices`, `true value`, or `guaranteed value`.

### Acceptance criteria

- A grossly broad range caused by an extreme outlier becomes limited-data or excludes the outlier with an explanation.
- Every excluded listing has a stored reason.
- Every report stores methodology version, input cluster IDs, excluded IDs, and output range.
- A report can be regenerated exactly from one snapshot.

---

## Phase 6 — Persist market history

### Problem

Rebuilding the ledger from scratch destroys the historical signals that make a market product valuable.

Without history, WatchLedger cannot accurately show:

- Price drops
- New listings
- Days on market
- Supply changes
- Listing removal
- 30/90-day price movement
- Coverage improvement

### Required data model

```text
source_fetch
  id
  source_name
  fetched_at
  source_url
  payload_hash
  fetch_status

listing_observation
  id
  listing_id
  source_fetch_id
  observed_at
  price_original
  currency
  price_usd
  availability
  content_hash

market_snapshot
  id
  configuration_id
  calculated_at
  methodology_version
  input_cluster_ids_json
  excluded_cluster_ids_json
  exclusion_reasons_json
  lower_range
  typical_price
  upper_range
  coverage_score
  diversity_score
  freshness_score
  confidence_state
```

### Required behaviour

- Never overwrite the only record of a previous asking price.
- Insert a new `listing_observation` on every source fetch.
- Mark a listing stale after a defined period without observation.
- Mark a listing removed only after repeat checks confirm it disappeared.
- Create one `market_snapshot` after each successful calculation run.

### Acceptance criteria

- The product can show a real 30/90-day range trend.
- The product can show when a listing was first and last observed.
- The product can send price-drop and new-listing alerts.
- Historical reports can be reproduced from stored snapshots.

---

## Phase 7 — State-specific user experience

The page must adapt to the amount and quality of evidence.

## Valid-market state

Show:

- Observed exact-match asking-price range
- Typical asking price
- Coverage, diversity, freshness, and confidence
- Price-position labels
- Exact configuration and related tabs
- Comparable-listing evidence
- Filters and sorting

Example:

```text
Observed exact-match asking-price range
$21,500–$31,500

Typical asking price: $23,275

12 configuration matches · 4 tracked dealers · 83% checked in 72h
Overall confidence: Medium
```

## Limited-data state

Show:

- Exact match count
- Related listing count
- Why a range is unavailable
- Clear next actions
- Neutral listing labels only

Do not show:

- Market range
- Potential-deal/fair/above-market legend
- Price-position percentages
- `Evidence behind this range` copy
- Empty exact-listing filters/table as the main destination

Example:

```text
Limited exact-match coverage

We found 4 exact configuration listings across 1 tracked dealer.
That is not enough independent evidence to publish a market range.

[View 4 exact listings] [Browse 24 related listings] [Track this reference]
```

## Zero-data state

Show related research directly instead of an empty exact-listings table.

```text
No exact listings currently tracked

We found 24 related listings, but none match this exact configuration closely enough
for a responsible market range.

[Browse related listings] [Request coverage] [Track this reference]
```

### Acceptance criteria

- A zero-data report has no empty filter row or empty exact table as its primary content.
- Limited-data reports never display incomplete range labels.
- Evidence wording changes from `Evidence behind this range` to `Current coverage` when no range exists.

---

## Phase 8 — Listing-table normalization

Do not expose raw, duplicated source titles as the main listing identity.

### Main row design

```text
Rolex Explorer II Polar
Ref. 226570 · 2024 · Excellent · Full set

$12,450
2.4% below typical
Fair price

Dealer name
United Kingdom · Observed 14 min ago

[View analysis]
```

### Keep raw source details in the drawer

```text
Original source title
Rolex Rolex Explorer II 226570 | Box & Papers | 2024

Source page
View original listing ↗
```

### Required filters

- Condition
- Box and papers
- Country/region
- Price
- Availability
- Seller/dealer
- Year
- Source
- Freshness
- Full set only

### Required sort options

- Best value
- Lowest price
- Highest price
- Closest to typical
- Most recently observed
- Newest listing
- Highest data completeness

### Acceptance criteria

- Canonical brand/model title is shown once, not repeated from raw source text.
- Every listing has enough structured context to distinguish it from another listing.
- Related rows never move into the exact table during filtering/sorting.

---

## Phase 9 — Make tracking a real product feature

`Track a watch` must become a real action rather than a navigation link.

### First tracking flow

```text
Track Rolex Explorer II Polar
Reference 226570

Notify me when:
[ ] A new exact-match listing appears
[ ] A listing is at least 5% below the typical price
[ ] The observed market range moves by at least 3%
[ ] Market coverage becomes sufficient for a range

Email address
[Start tracking]
```

### Required entities

```text
user
watchlist_item
alert_preference
alert_delivery
```

### First useful alerts

- New exact listing
- Price drop on a saved listing
- Potential deal detected
- Coverage changed from limited to valid
- Market range changed materially

### Acceptance criteria

- The CTA creates a saved watch or alert preference.
- Limited-data pages can notify a user when coverage improves.
- Users can unsubscribe from alerts.

---

## Phase 10 — Expand data sources only after quality gates work

The main product advantage will not come from one source or more styling. It will come from permissioned, diverse, traceable data coverage.

### Source policy

Prioritize sources in this order:

1. Licensed dealer inventory feeds
2. Official APIs
3. Partner marketplace feeds
4. Dealer-submitted inventory
5. Public discovery data only where terms explicitly permit it

### Every source must store

```text
source
  id
  name
  domain
  access_method
  permission_status
  image_usage_status
  attribution_requirements
  last_terms_reviewed_at
```

### Do not claim

- “Every listing on the internet”
- “All dealer listings”
- “Verified sale price” when showing an active ask
- “True value” or a guaranteed investment result

Use:

- “Tracked public listings”
- “Observed asking-price range”
- “Seller-reported availability”
- “Market snapshot fetched at …”

---

# Implementation order for the next four sprints

## Sprint 1 — Data truth gate

1. Implement strict reference/configuration matching.
2. Implement listing clusters and duplicate exclusion.
3. Implement confidence dimensions and market eligibility gate.
4. Make limited-data and zero-data pages state-specific.
5. Add automated tests for matching, duplicate isolation, and range eligibility.

**Sprint success:** A range cannot be published from repeated listings, one dealer alone, or clearly mixed configurations.

## Sprint 2 — Pricing correctness

1. Implement MAD outlier detection.
2. Add exclusion reasons and review state.
3. Add weighted median/percentile calculation.
4. Store methodology version and calculation inputs.
5. Update drawer explanations to use real calculation facts.

**Sprint success:** An extreme mixed market, such as a broad six-listing range, is limited or explained rather than presented as a normal market.

## Sprint 3 — Historical market value

1. Add fetch records and listing observations.
2. Add market snapshots.
3. Track stale/removed listing state.
4. Add price-change and supply history.
5. Show absolute snapshot timestamps and precise freshness language.

**Sprint success:** The product can show a real 30/90-day range and tell users when each listing was observed.

## Sprint 4 — Retention and research

1. Build watchlists.
2. Implement coverage-improved and new-listing alerts.
3. Normalize table titles and listing details.
4. Add advanced filters/sorts.
5. Build shareable report URLs.

**Sprint success:** A collector can save a watch, receive a useful alert, and return to a clear evidence-backed market view.

---

# Testing requirements

Add automated tests before expanding reference coverage.

## Data tests

- Strict reference match accepts the correct configuration.
- Related references cannot influence exact-market calculations.
- Duplicate clusters count once.
- One-dealer coverage cannot result in high confidence.
- Fewer than eight valid clusters cannot show a range.
- Outliers are flagged with a saved reason.
- Limited-data reports have no deal/fair/above-market labels.
- Exact and related tabs remain isolated after filtering and sorting.

## Rendering tests

- Raw source titles are escaped.
- Unsafe URLs do not render.
- Range evidence count matches the exact clusters used.
- A zero-data page directs the user to related listings.
- Raw source URLs are hidden behind a methodology interaction.

## Browser tests

- The search works by keyboard.
- The listing-analysis drawer opens, traps focus, closes with Escape, and restores focus.
- Filters work independently per exact/related tab.
- Mobile listing cards remain usable.
- Tracking flow validates email, confirms subscription, and supports unsubscribe.

---

# Product language rules

Use these terms consistently.

| Avoid | Use instead |
|---|---|
| Market value | Observed asking-price range |
| Every listing | Tracked public listings |
| Active listing | Listing observed in the latest market snapshot |
| Verified availability | Seller-reported availability / last observed |
| Exact match | Exact configuration match, only when verified |
| Deal | Potential deal |
| Overpriced | Above observed comparable range |
| True value | Typical observed asking price |

---

# Final standard

WatchLedger becomes an exceptional product when its interface is as conservative as its visual design is polished.

A user should be able to answer these questions on every reference page:

1. Is this watch configuration truly comparable?
2. How many unique listings support the result?
3. How many independent sources support it?
4. How recent is the data?
5. Which listings were excluded, and why?
6. What does this price label mean?
7. What should I do if there is not enough evidence yet?

If the system cannot answer a question honestly, it must show a limited-data state instead of pretending to know.
