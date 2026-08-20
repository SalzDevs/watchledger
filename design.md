# WatchLedger — Screenshot Review and Design Improvements

## Overall assessment

The visual foundation is strong. The warm ivory background, restrained borders, editorial serif headings, and deep-green accent make the product feel premium, calm, and collector-focused.

The next design iteration should focus less on added decoration and more on **readability, trust, and pricing clarity**. The site must constantly prove:

> This market range is credible, these listings are comparable, and every price label has a clear explanation.

---

## What is working well

- The ivory, charcoal, and deep-green visual system feels refined and trustworthy.
- The homepage hero clearly communicates that the product is about live watch-market data.
- The serif heading style creates a collector/editorial personality rather than a generic marketplace look.
- The three-step explainer is understandable at a glance.
- The model-page hierarchy is sound: watch identity, range, interpretation, then listings.
- Real listing imagery creates authenticity and helps the product feel less abstract than a valuation calculator.
- Cards, borders, spacing, and shadows are restrained; this supports a serious market-research tone.

---

# Highest-priority improvements

## 1. Make the displayed data internally credible

The screenshot shows a Rolex Submariner Date reference `126610LN`, while the table contains different vintage and special references, including `5513`, `5512`, `6205`, `1680`, and Kermit-related listings.

A displayed range of `$10,300–$175,000` makes the page feel unreliable because these are not like-for-like comparables. The interface claims confidence while displaying evidence that contradicts it.

### Design rule

Show exact-reference listings by default. If the result set is broadened, make that explicit.

```text
24 exact-reference listings

[Exact matches]  [Related Submariners]  [Vintage references]
```

A credible default market card:

```text
OBSERVED MARKET RANGE

$12,100 — $13,450

Typical asking price: $12,760
Based on 24 exact-reference listings
Updated 44 minutes ago
```

If exact comparison data is limited, show an honest state rather than a misleading broad range:

```text
Limited exact-match data

We found 4 listings for reference 126610LN.
20 related Submariner listings are available for broader research.

[View related listings]
```

---

## 2. Make the market range card the strongest page element

The market card is in the correct place, but it needs stronger structure and more legible supporting evidence.

The user should understand immediately:

1. The observed range
2. The typical price
3. The amount and freshness of the supporting evidence

### Recommended hierarchy

```text
CURRENT OBSERVED MARKET RANGE

$12,100 — $13,450

Typical asking price
$12,760

Based on 24 exact-reference active listings · Updated 44 min ago
```

### Recommended range visual

```text
$11.5k        $12.1k          $12.76k          $13.45k         $14k
──────────────[─────────────────●─────────────────]──────────────
               Lower range      Typical price      Upper range
```

Use a soft gray full line, pale-green observed-range band, deep-green typical-price marker, and labels large enough to read without zooming.

---

## 3. Make price-position labels meaningful

The screenshots show the same `Within observed range` badge across listings at dramatically different prices. This weakens the central value proposition.

| Listing position | Label | Visual treatment |
|---|---|---|
| Materially below the comparable range | Potential deal | Pale green background, deep green text |
| Inside the comparable range | Fair price | Pale blue background, slate-blue text |
| Slightly above the range | Above market | Pale amber background, amber text |
| Materially above the range | High above market | Pale red background, berry text |
| Wrong reference or incomplete comparison data | Not comparable / Limited data | Neutral gray background |

Use specific explanations:

```text
↓ 6.1% below typical
Potential deal
```

```text
Within observed range
Fair price
```

```text
↑ 8.4% above typical
Above comparable range
```

```text
Different reference
Not included in the exact-match range
```

Avoid generic badges that do not explain why the listing has that status.

---

## 4. Increase text size and contrast

The interface is polished, but several parts are too small or too faint for normal laptop use.

Most affected areas:

- Top navigation labels
- Hero supporting copy
- Search placeholder and example searches
- Listing metadata
- Listing-table headings
- Seller/source names
- Range-chart labels
- Small market-card details
- Raw data/source information

### Minimum readability rules

| Element | Recommended size |
|---|---:|
| Standard body copy | 15–16px |
| Navigation labels | 13–14px |
| Listing metadata | 13–14px |
| Table headers | 11–12px with stronger contrast |
| Price in a listing row | 18–20px |
| Supporting market text | 13–14px |

Use available whitespace to improve readability rather than fitting more text into the page.

---

## 5. Simplify the model-header metric cards

The four small top-level metric cards are visually tidy but feel fragmented.

`Active listings: 24` and `In stock now: 24` are potentially redundant. `Auction results: 0` gives an unhelpful zero-value fact the same visual importance as useful signals.

### Recommended replacement

```text
24
Exact-match listings

9
Tracked dealers

High
Data confidence
```

Place freshness nearby:

```text
Last checked 44 minutes ago
```

Only show auction results when meaningful auction data is available.

---

# Homepage improvements

## 6. Strengthen the hero search

Search is the homepage’s primary action, but the current search box is visually quieter than the watch image.

### Improve it

- Increase width by approximately 15–25%.
- Increase height to 60–64px.
- Use darker placeholder text.
- Make the search icon clearer.
- Replace inline example text with tappable/clickable example chips.

```text
Search brand, model, or reference number

Popular searches
[Rolex 126610LN] [Omega Speedmaster] [Patek Philippe 5711]
```

---

## 7. Rebalance the hero image and floating market card

The hero image is attractive but visually dominates the product explanation. It can make the page feel more like a dealer/editorial site than a pricing-research tool.

The floating price card is a good idea, but it is too small and overlaps a visually important part of the watch image.

### Improve it

- Reduce the image scale slightly.
- Increase the card width and internal padding.
- Align the card with the lower-left edge of the image rather than covering the centre of the watch.
- Include a clear evidence line: `24 active listings · Updated 44 min ago`.

The card should feel like a compact evidence panel, not decorative overlay content.

---

## 8. Reduce empty transition space after the hero

The whitespace between the hero and `How it works` is calm but slightly delays the journey to supporting proof.

Bring the next section upward by approximately 48–80px, or use the space for a compact trust strip:

```text
Live dealer listings     Reference-level comparison     Transparent market ranges
```

---

## 9. Replace placeholder mini-panels in the three-step cards

The gray blocks at the bottom of the explainer cards look unfinished. They should visually explain each step.

| Step | Visual |
|---|---|
| We collect visible market listings | Three small listing cards entering one collection |
| We compare like-for-like watches | Similar listings grouped around one reference number |
| You see where each price sits | Listing dots distributed around a market-range bar |

Use simple line drawings or lightweight data illustrations. Avoid decorative graphics that do not communicate meaning.

---

## 10. Replace the `JSON API` link

`JSON API →` feels out of place in a consumer-facing section. It introduces developer language into a premium collector experience.

Use one of the following instead:

- `Explore all markets →`
- `View all tracked watches →`
- `Browse market data →`

If an API exists, keep it in the footer or on a dedicated developer page.

---

## 11. Give market cards one more useful data point

The market cards are visually strong but need a quick trend signal to make them more useful.

```text
Omega Speedmaster Professional
Reference 310.30.42.50.01.002

€5,800–€6,450
↑ 2.8% over 90 days
42 active listings · Updated 42 min ago
```

Use muted green for positive movement, muted berry for negative movement, and neutral gray when trend data is unavailable.

Do not show `Potential deal` badges on the homepage; deal discovery should remain on the model page.

---

# Model page and listing-table improvements

## 12. Add a clear filter and sorting row

Users need to refine listings before scanning a long table. The current table begins too abruptly.

```text
Live listings                                      Sort: Best value ▾

[Condition ▾] [Box & papers ▾] [Location ▾] [Price ▾] [More filters ▾]

24 exact-reference listings · Updated 44 minutes ago
```

Primary filters:

- Condition
- Box & papers
- Location
- Price
- Seller type
- Availability

Default sort: **Best value**.

Tooltip copy:

> Ranks listings by price position after comparing condition, completeness, freshness, and market relevance.

---

## 13. Improve listing-row scanability

The current listing rows are clean but too compressed. Watch identity, price, price position, seller details, and actions need stronger separation.

```text
[Photo]  Rolex Submariner Date                    $12,450       Potential deal       Dealer name
         126610LN · 2023 · Excellent · Full set  $620 below    ↓ 4.8% below         London, UK

                                                                    [View analysis]
```

### Changes

- Increase row height slightly.
- Make the watch title and price visually stronger.
- Keep percentage and price-position label together.
- De-emphasize secondary seller/source metadata.
- Rename the far-right action from `View` to `View analysis`.
- Place `View original listing ↗` inside the analysis drawer rather than making the table action ambiguous.

---

## 14. Replace visible raw source URLs with a provenance summary

A raw source URL above the table reads as debug information. It is valuable but should not be visually noisy.

```text
24 exact-match listings from tracked public sources · Last checked 20 Jun 2026, 08:03 UTC

[See sources and methodology]
```

Put direct raw links inside an expandable evidence/source panel.

---

## 15. Add visible evidence near the market range

The site claims it uses verifiable public data. Make that proof visible beside or below the market range.

```text
EVIDENCE BEHIND THIS RANGE

24 exact-match active listings
9 tracked dealers
24 listings checked in the last 48 hours

[Inspect comparable listings]
```

This makes the product’s core differentiator tangible without cluttering the page.

---

# Visual refinements

## Spacing and card treatment

Keep the existing visual direction, with small adjustments:

- Maintain the ivory page background and white card surfaces.
- Use borders as the default separation mechanism rather than shadows.
- Keep card radii around 12–16px.
- Use 24–32px padding for key market cards.
- Increase vertical rhythm around important sections; reduce unnecessary blank gaps.
- Keep hover shadows extremely soft.

## Colour rules

| State | Background | Text |
|---|---|---|
| Potential deal | `#E6F1EC` | `#1F5B48` |
| Fair price | `#E8F0F4` | `#36566C` |
| Above market | `#FCF1DC` | `#A96816` |
| High above market | `#F8E7E7` | `#9B3436` |
| Not comparable / limited data | `#F1F0EB` | `#696862` |

Do not use bright green or red. The interface should communicate careful analysis, not trading-app urgency.

---

# Final priority list

1. Show only genuine exact-reference comparables by default.
2. Replace the extreme range with a credible exact-match market range, or show a limited-data state.
3. Make deal, fair, above-market, and not-comparable statuses visibly different and specifically explained.
4. Increase small-text size and contrast across navigation, tables, charts, and metadata.
5. Simplify top summary metrics to exact matches, sources/dealers, confidence, and freshness.
6. Make search more dominant on the homepage.
7. Improve filtering, sorting, and scanability in the live-listings area.
8. Turn visible data provenance into a polished evidence module rather than a raw URL.
9. Replace placeholder explainer-card visuals with meaningful mini-diagrams.
10. Remove developer-oriented language such as `JSON API` from consumer-facing areas.

## Final design direction

> Preserve the current premium editorial aesthetic, but make it more legible and evidential. The page should never make a user wonder whether listings are truly comparable, whether a price label is justified, or whether the displayed market range is reliable.
