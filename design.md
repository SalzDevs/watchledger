# WatchLedger — Live Site Improvement Report

## Audit scope

This report is based on a live review of WatchLedger, including the homepage, published-range pages, limited-data pages, zero-data pages, listing tables, related/variant/excluded tabs, public API output, and raw-data browser.

## Overall assessment

WatchLedger is now a substantial improvement over the first proof of concept. The product visibly applies:

- Market eligibility gates
- Exact, variant, related, and excluded listing separation
- Limited-data and zero-data states
- Coverage, diversity, freshness, and confidence dimensions
- Published ranges only for eligible references
- Source provenance and methodology versioning
- A visible `Track this watch` conversion point

The core direction is correct:

> WatchLedger is becoming conservative when evidence is weak.

The next priority is not visual polishing. It is making the **homepage, market labels, comparable grouping, and tracking loop** as rigorous as the market eligibility logic.

---

# Critical improvements

## 1. Never show an invalid range on the homepage

### Problem

Several homepage cards are correctly marked `LIMITED DATA`, but still show a large numeric range. Examples include:

- Nautilus 5712: `$19,500–$144,500`
- Nautilus 5711: `$77,950–$142,000`
- Explorer II: `$11,000–$13,800`
- Royal Oak: `$42,500–$60,000`

Even with a limited-data badge, many people will interpret the large numeric range as a valid market valuation.

### Required change

For every reference where `valid == false`, never show raw low/high asking prices as the main market-range result.

Use this instead:

```text
LIMITED MARKET COVERAGE

5 observed exact-match listings
No published range yet
```

Or:

```text
MARKET COVERAGE DEVELOPING

20 observed listings
Limited source diversity
```

Keep the raw observed price spread only in expanded methodology/evidence details:

```text
Observed asking prices span $19,500–$144,500.
This is not a published market range because the comparison set is insufficient.
```

### Apply this rule everywhere

- Homepage market cards
- Recently updated list
- Homepage hero card
- Search suggestions
- Any consumer-facing API field
- Social/SEO preview cards

Only `state == valid` should use the large green observed-range presentation.

### Acceptance criteria

- Limited and zero-data references never display a consumer-facing price range.
- Homepage cards make the data state more visually prominent than raw observed prices.
- The user can inspect the raw spread only through evidence details.

---

## 2. Fix the confidence contradiction on valid pages

### Problem

The valid Daytona page presents a state similar to:

```text
Coverage: Medium
Diversity: Medium
Freshness: High
Overall: High
```

The overall confidence must not be stronger than the dimensions supporting it.

### Required change

Calculate overall confidence as no stronger than the lowest critical dimension.

| Coverage | Diversity | Freshness | Maximum overall confidence |
|---|---|---|---|
| High | High | High | High |
| Medium | Medium | High | Medium |
| High | Limited | High | Limited |
| Limited | High | High | Limited |

The Daytona state should become:

```text
Overall confidence: Medium

12 unique exact-match listings
4 independent dealers
High freshness
```

### Acceptance criteria

- One weak dimension prevents a stronger overall state.
- High confidence requires high coverage, high diversity, and high freshness.
- The calculation is deterministic and covered by tests.

---

## 3. Deduplicate before allowing a published range

### Problem

The Explorer II page correctly refuses to publish a range because it has only one dealer. However, it still contains many extremely similar rows from that dealer.

Raw source rows are not the same as independent market listings.

### Required change

Before calculating coverage, diversity, or any price range, group duplicate source records into a `listing_cluster`.

Use this data model:

```text
listing_cluster
  id
  canonical_reference_id
  representative_listing_id
  cluster_confidence
  created_at
  updated_at

listing
  id
  source_name
  source_listing_id
  canonical_url
  listing_cluster_id
  listing_fingerprint
```

### Duplicate rules

Treat rows as definite duplicates when they have:

- The same source and source listing ID
- The same canonical URL
- The same dealer inventory identifier

Treat rows as likely duplicates when several signals agree:

- Same dealer
- Same exact configuration
- Same or near-identical price
- Similar normalized title
- Same image URL or permitted image fingerprint
- Similar first-observed timestamp

### Analytics rule

Use one representative per cluster in calculations.

Keep every source record in the evidence view.

### UI example

```text
20 observed source records
12 unique listing clusters
1 independent dealer

No published range yet
```

### Acceptance criteria

- Repeated dealer/source rows do not inflate listing count.
- Repeated rows do not improve confidence.
- Every range stores the representative cluster IDs used.
- The evidence panel exposes duplicate grouping decisions.

---

## 4. Tighten the related-listings experience

### Problem

The Black Bay 58 zero-data page currently shows very broad “related” results, including chronographs, vintage Tudor Submariners, gold variants, Snowflakes, and Monte Carlo chronographs.

That is too broad for the default research experience.

### Required change

Rank related listings into explicit relevance groups:

```text
Closest alternatives
Same model family and similar configuration

Other Black Bay 58 variants
Different metal, dial, or limited edition

Historical Tudor alternatives
Different reference family; not comparable for pricing
```

For Black Bay 58, default related results should prioritise:

- Same Black Bay Fifty-Eight family
- Same material
- Similar dimensions
- Similar bracelet/strap configuration
- Closely related reference numbers

Vintage Submariners and chronographs should appear only under a deliberate broader-research action:

```text
Explore broader Tudor collector references
```

### Acceptance criteria

- The default related tab has a documented relevance threshold.
- Related listings always show why they are related.
- Distant model families are not mixed into close alternatives.

---

## 5. Make variants a real pricing feature

### Problem

The Nautilus Moon Phase page correctly separates a rose-gold reference into a variant, but the product needs to explain configuration differences clearly enough for a buyer to understand why the record is excluded.

### Required change

Show selected configuration prominently:

```text
Selected configuration

5712/1A-001
Stainless steel · Blue dial · Bracelet
```

Then show comparison groups:

```text
Exact configuration: 4 listings
Same reference, other configuration: 1 listing
Related references: 2 listings
Excluded records: 1 listing
```

### Variant label example

```text
5712/1R-001
Rose-gold configuration
Excluded from steel 5712/1A pricing
```

### Acceptance criteria

- A configuration difference is visible before the user studies a raw title.
- Variant records do not influence an exact-configuration range.
- Every variant has a human-readable exclusion reason.

---

# Report-page improvements

## 6. Replace raw source titles in the listing table

### Problem

Listing rows still expose duplicate, raw source titles such as:

```text
Rolex Rolex Daytona | REF. 116500LN | Black Dial...
```

This makes the product feel like an API viewer instead of a market-research product.

### Required change

Render canonical WatchLedger identity first:

```text
Rolex Daytona Ceramic
Ref. 116500LN · 2021 · Black dial · Full set

Excellent · Stainless steel · 40 mm
```

Keep the full unmodified source title only in the listing-analysis drawer:

```text
Original source title
Rolex Rolex Daytona | REF. 116500LN | Black Dial | Box & Papers | 2021
```

### Acceptance criteria

- Brand and model do not repeat in the main title.
- Main rows use structured fields for comparison.
- Raw source title remains available for provenance.

---

## 7. Show relative position for fair-price rows

### Problem

Potential deals and high-above-market listings show percentages. Fair rows show only `Within observed range`, which does not tell the user whether a price is near the lower or upper end.

### Required change

Show a relative position for every valid listing:

```text
Fair price
2.4% below typical
```

```text
Fair price
5.8% above typical
```

```text
Potential deal
17.4% below typical
```

```text
High above market
37.0% above typical
```

### Acceptance criteria

- Every valid classified listing displays its relative position.
- Limited-data listings show no price-position percentage.
- The explanation drawer uses the same calculation result as the table.

---

## 8. Use state-specific evidence language

### Problem

A zero-data page can currently show text such as:

```text
EVIDENCE BEHIND THIS PAGE
0 exact-match listings
0 tracked dealers
Each price links to its live listing
```

The last statement is not applicable when there are no prices.

### Required change

Use different evidence modules by state.

### Valid market

```text
EVIDENCE BEHIND THIS RANGE

12 unique exact-match listings
4 independent dealers
83% observed within the last 72 hours
```

### Limited market

```text
CURRENT MARKET COVERAGE

5 exact-match listings
3 independent dealers
More listing coverage is needed
```

### Zero-data market

```text
CURRENT TRACKING STATUS

No exact-match listings observed yet
24 broader related listings available
```

### Acceptance criteria

- Zero-data pages contain no range-specific language.
- Limited-data pages contain no deal/fair/above-market language.
- Evidence content always reflects the report state.

---

## 9. Make `Track this watch` a real feature

### Problem

The visible tracking section is a good conversion point, but it must lead to an actual alert workflow rather than only a visual CTA.

### First complete flow

```text
Track Rolex Daytona Ceramic
Reference 116500LN

Notify me when:

[ ] A new exact-match listing appears
[ ] A listing is 5% below the typical observed price
[ ] The published range changes by 3% or more
[ ] Market coverage becomes sufficient for a range

Email address
[Start tracking]
```

For a limited-data watch:

```text
Notify me when WatchLedger has enough independent evidence
to publish a market range.
```

### Required basics

- Double opt-in email confirmation
- One-click unsubscribe
- Rate-limited delivery
- Clear privacy notice
- Stored alert preferences
- No account required for the first version

### Acceptance criteria

- The CTA creates an actual saved alert preference.
- Limited-data pages offer coverage-improved alerts.
- Every email supports unsubscribe.

---

## 10. Explain every excluded listing

### Problem

The `Excluded` tab is a strong transparency feature, but it needs explicit reasons.

### Required change

Every excluded row should show one clear reason:

```text
Excluded from market range
Different reference
```

```text
Excluded from market range
Rose-gold variant
```

```text
Excluded from market range
Likely duplicate listing
```

```text
Excluded from market range
Price outlier pending review
```

### Acceptance criteria

- No listing is excluded silently.
- The explanation is visible in both the table and drawer.
- Exclusion reasons are stored in the calculation snapshot.

---

# Homepage improvements

## 11. Lead with published markets only

### Required change

Split homepage discovery into two sections.

```text
Published market ranges
References with enough independent evidence
```

Only show valid market cards here.

Then show:

```text
Coverage developing
References WatchLedger is actively tracking
```

For limited markets, show:

```text
Rolex Explorer II Polar
20 observed listings · 1 dealer
Range not published yet
```

### Acceptance criteria

- Invalid raw price spreads are never visually equal to published ranges.
- Users can discover what WatchLedger can price confidently today.
- Developing markets remain discoverable without being misrepresented.

---

## 12. Add market-discovery filters

Add discovery controls:

```text
[Published ranges] [Coverage developing] [All tracked references]
```

Useful filters:

- Brand
- Published range only
- Price band
- Minimum source diversity
- Recently refreshed
- Most tracked
- Newly covered references

### Acceptance criteria

- Users can find validly priced watches without scanning limited-data cards.
- Filter state is visible and shareable in the URL.

---

## 13. Turn unknown searches into demand capture

For an untracked watch query, do not stop at “no result.”

Show:

```text
We do not track this exact reference yet.

[Request coverage]
[Track this reference]
[Browse similar tracked watches]
```

This creates a demand queue and gives users a reason to return.

---

# Data, transparency, and trust improvements

## 14. Replace “active listing” with “observed listing”

The product currently uses source snapshots. It should not imply independent real-time verification.

Use:

```text
12 exact-reference listings observed
Market snapshot fetched 3 hours ago
Seller-reported availability
```

Do not use `active` or `verified` unless the application has actually checked the listing’s current source state.

---

## 15. Add geography, tax, and currency context

Global watch listings are not perfectly comparable without location and tax context.

### Required listing fields

- Listing country
- Original currency
- Normalised USD amount
- Tax treatment: included / excluded / unknown
- Shipping/import note

### Listing UI example

```text
$23,000 USD
Original price: €21,250
United Kingdom
Tax treatment: not stated
```

### Required filters

```text
[United States] [Europe] [United Kingdom] [Global]
```

### Acceptance criteria

- Users can isolate a geographic market.
- The interface never silently treats tax-included and tax-excluded prices as identical.

---

## 16. Separate dealer information from price confidence

Add dealer/source profiles without using vague trust badges.

```text
Watch Collectors UK

18 listings observed
Country: United Kingdom
Last source check: 3 hours ago
Direct source links available
```

A `Verified` badge may only be used if documented criteria exist.

---

## 17. Publish a normal-person methodology page

The eligibility gate is now visible. The next step is a readable methodology page that explains:

- Exact configuration matching
- Minimum gates for a published range
- Duplicate clustering
- Outlier handling
- Asking prices versus sold prices
- Freshness policy
- Source coverage limits
- Meaning of `Potential deal`
- What WatchLedger does not verify

Every report should link to its exact methodology version:

```text
Methodology v1.0
```

---

# Technical and launch improvements

## 18. Add search-engine fundamentals

The live site currently returns `404` for `robots.txt` and `sitemap.xml`.

Before public launch, add:

- `robots.txt`
- `sitemap.xml`
- Canonical URLs
- Unique title tags per reference
- Unique meta descriptions
- Open Graph metadata
- Social share cards
- JSON-LD structured data where appropriate

### Acceptance criteria

- Every valid reference page appears in the sitemap.
- Search engines receive canonical URLs.
- Shared reference links have a useful title, description, and image.

---

## 19. Review public raw-data exposure

The `/raw/` browser is excellent as a provenance demonstration, but complete payload redistribution can create source-terms, copyright, database-right, or privacy risks.

### Safer public evidence experience

```text
Source evidence

Source: MostExpensiveWatches
Fetched: 20 Aug 2026, 09:15 UTC
Records used: 12
Direct listing links: 12
Methodology: v1.0
```

Keep complete raw payloads internal unless source terms explicitly permit public redistribution.

---

## 20. Test mobile and interactive flows before launch

Test:

- Mobile listing cards rather than compressed desktop tables
- Keyboard search navigation
- Drawer focus management
- Exact/variant/related/excluded filter isolation
- Zero-data and limited-data actions
- Tracking-form validation
- Broken-image fallback
- Slow-network behaviour
- Source-link failures

---

# Recommended roadmap

## Next sprint — make published ranges unbreakable

1. Hide numeric ranges for all `limited` and `zero` homepage cards.
2. Fix overall confidence so it cannot exceed coverage or diversity.
3. Deduplicate repeated listing rows before analytics.
4. Add excluded-listing reasons.
5. Explain configuration differences in variants.
6. Correct zero/limited evidence wording.

### Sprint success condition

Every published range is unmistakably distinct from a raw observed price spread, and no weak market can be mistaken for a valuation.

## Following sprint — make reports decision-ready

1. Canonicalise listing titles.
2. Show price position for fair listings.
3. Add location, original currency, tax state, and region filters.
4. Improve related-listing ranking.
5. Add dealer/source context.
6. Make tracking a functioning alert workflow.

### Sprint success condition

A buyer can compare two listings and understand the specific reason one is better priced.

## Then — make the product discoverable and repeatable

1. Separate homepage sections for published versus developing markets.
2. Add coverage-quality filters.
3. Add request-coverage flow for unknown searches.
4. Add SEO fundamentals.
5. Create shareable reference pages.
6. Publish the methodology page.
7. Build a rights-reviewed provenance experience.

### Sprint success condition

Users can find WatchLedger through search, understand its standards, save a reference, and return when the market changes.

---

# Final product standard

WatchLedger will be exceptional when every displayed price result answers seven questions clearly:

1. Is this watch configuration truly comparable?
2. How many unique listings support the result?
3. How many independent sources support it?
4. How recent is the market snapshot?
5. Which listings were excluded, and why?
6. What does this price label mean?
7. What should the user do if there is not enough evidence yet?

If the product cannot answer one honestly, it must show a limited-data state instead of pretending to know.
