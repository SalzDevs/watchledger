"""watchledger web server — stdlib only, no dependencies.

Serves the ledger live:
  /                          homepage: hero search, markets, how it works
  /reference/<slug>          per-reference market report (deterministic renderer)
  /api/references.json       index stats as JSON
  /api/reference/<slug>.json one reference's report dict as JSON
  /raw/<path>                raw payload files (the source of truth, browsable)
  /methodology               readable methodology page
  /sources                   source registry
  /robots.txt, /sitemap.xml  search-engine fundamentals
  /static/<path>             shared CSS, JS, fonts

Security rules (from the security guide):
  - External URLs validated with safe_external_url before rendering.
  - Text values escaped with safe_text.
  - Homepage search data shipped as a type=application/json block, rendered
    by /static/home.js with DOM nodes — never innerHTML.
  - Security headers (CSP, nosniff, frame denial) on every response.
  - Slugs validated before routing to the database.
  - SQLite errors logged server-side only; visitors get a generic page.

Design brief improvements applied:
  - Only valid references ever show a consumer-facing price range; limited and
    zero states show coverage status instead (#1, #11).
  - Homepage is split into Published ranges and Coverage developing (#11).
  - Market-discovery filters are URL-shareable (#12).
  - Unknown searches offer request-coverage demand capture (#13).
  - All listing language uses "observed" not "active"/"verified" (#14).
"""

import datetime
import http.server
import json
import os
import secrets
import sqlite3
import statistics
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from config import DB_PATH, RAW_DIR, STATIC_DIR
from report import build_report, price_fmt, q, render
from security import safe_external_url, safe_json_script, safe_slug, safe_text
import market

PORT = int(os.environ.get("PORT", "8040"))

SITE_BASE = "https://watchledger-delta.vercel.app"


def open_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def fmt_ago(ts):
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} d ago"


def index_stats(db):
    """Per-reference summary rows for the homepage.

    Ranges come from the stored market_snapshot (Phase 5), not recomputed on
    the fly, so the homepage and the report page can never disagree. Each row
    carries the eligibility state (valid/limited/zero) from Phase 4. Only
    valid references carry a published_range; limited/zero states never expose
    a consumer-facing numeric range (design brief #1).
    """
    rows = q(db, """SELECT DISTINCT m.slug, m.brand, m.ref, m.model, m.case_material
                    FROM references_meta m
                    LEFT JOIN listings l ON l.slug = m.slug
                    LEFT JOIN auction_lots a ON a.ref_slug = m.slug
                    WHERE l.slug IS NOT NULL OR a.ref_slug IS NOT NULL
                    ORDER BY m.brand, m.ref""")
    out = []
    for r in rows:
        slug = r["slug"]
        cfg = q(db, "SELECT id FROM watch_configuration WHERE reference_id=? "
                    "AND active=1", (slug,))
        snap = market.latest_snapshot(db, cfg[0][0]) if cfg else None
        elig = market.eligibility(db, slug)
        n_exact = elig["n_clusters"]
        prices = [x[0] for x in q(db,
                   "SELECT l.price_usd FROM listings l "
                   "JOIN listing_cluster c ON c.representative_listing_id=l.id "
                   "WHERE l.slug=? AND l.match_level='exact_configuration'",
                   (slug,)) if x[0] is not None]
        images = [x[0] for x in q(db,
                  "SELECT l.image_url FROM listings l "
                  "JOIN listing_cluster c ON c.representative_listing_id=l.id "
                  "WHERE l.slug=? AND l.match_level='exact_configuration' "
                  "AND l.image_url IS NOT NULL LIMIT 1", (slug,))]
        stamps = [x[0] for x in q(db,
                  "SELECT l.fetched_at FROM listings l "
                  "JOIN listing_cluster c ON c.representative_listing_id=l.id "
                  "WHERE l.slug=? AND l.match_level='exact_configuration' "
                  "AND l.fetched_at IS NOT NULL", (slug,))]
        auc_prices = [x[0] for x in q(db,
                      "SELECT hammer_usd FROM auction_lots WHERE ref_slug=?",
                      (slug,)) if x[0] is not None]
        if snap:
            band_low, band_high = snap[7], snap[9]
            typical = snap[8]
        else:
            band_low, band_high, typical = None, None, None
        state = "valid" if elig["range_eligible"] else (
            "zero" if n_exact == 0 else "limited")
        published = {
            "low": band_low,
            "high": band_high,
            "typical": typical,
        } if state == "valid" else None
        out.append({
            "slug": slug, "brand": r["brand"], "ref": r["ref"],
            "model": r["model"] or "", "material": r["case_material"] or "",
            "n_listings": n_exact,
            "n_dealers": elig["n_dealers"],
            "observed_low": min(prices) if prices else None,
            "observed_high": max(prices) if prices else None,
            "observed_count": len(prices),
            "published_range": published,
            "n_auction": len(auc_prices),
            "median_hammer": statistics.median(auc_prices) if auc_prices else None,
            "image": images[0] if images else None,
            "updated": max(stamps) if stamps else None,
            "confidence": elig["overall"],
            "coverage": elig["coverage"],
            "diversity": elig["diversity"],
            "freshness_dim": elig["freshness_dim"],
            "state": state,
            "valid": elig["range_eligible"],
        })
    return out


def img_html(url, alt, cls=None):
    """Render an external image only when the URL is approved."""
    safe = safe_external_url(url)
    if not safe:
        return '<div class="image-placeholder" aria-hidden="true"></div>'
    cls_attr = f' class="{safe_text(cls)}"' if cls else ""
    return (f'<img{cls_attr} src="{safe_text(safe)}" alt="{safe_text(alt)}" '
            f'loading="lazy" referrerpolicy="no-referrer">')


PAGE_HEAD = """<!doctype html>
<html><head><meta charset="utf-8"><title>watchledger — know what a watch is worth, today</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="WatchLedger computes market ranges for watches deterministically from traceable public dealer listings. No AI, no guesswork.">
<meta property="og:type" content="website">
<meta property="og:title" content="WatchLedger — know what a watch is worth, today">
<meta property="og:description" content="Published market ranges computed deterministically from traceable dealer listings.">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="https://watchledger-delta.vercel.app/">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head><body>
<header class="nav"><div class="nav-inner">
<a href="/" class="logo">watch<span>ledger</span></a>
<nav class="nav-links"><a href="/#markets">Explore Watches</a><a href="/#how">Market Trends</a><a href="/#trust">How It Works</a></nav>
<div class="nav-actions">
<button class="nav-icon" type="button" data-focus-search aria-label="Search">⌕</button>
<a href="/methodology" class="btn btn-ghost">Methodology</a>
<a href="/#markets" class="btn btn-primary">Track a watch</a>
</div>
</div></header>"""

PAGE_FOOT = """<footer><div class="footer-inner">
<div class="col"><div class="logo">watch<span>ledger</span></div>
<p>Know what a watch is worth — today. Every number on this site is computed from the raw payloads under <a href="/raw/">/raw</a> and links to its source. No AI, no guesswork.</p></div>
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/references.json">JSON API</a><a href="/#markets">Tracked markets</a></div>
<div class="col"><b>Product</b><a href="/methodology">Methodology</a><a href="/#trust">Why it's trustworthy</a><a href="/#how">How it works</a></div>
</div></footer></body></html>"""


def rng_for(s):
    """Only valid references show a consumer-facing range (design brief #1)."""
    if s["valid"] and s["published_range"] and s["published_range"]["low"] is not None:
        r = s["published_range"]
        return price_fmt(r["low"]) + " – " + price_fmt(r["high"])
    if s["state"] == "zero":
        return "No listings observed yet"
    return "No published range yet"


def state_badge(s):
    if s["state"] == "valid":
        return f'<span class="state-badge state-ok">Published range</span>'
    if s["state"] == "limited":
        return f'<span class="state-badge state-warn">Coverage developing</span>'
    return f'<span class="state-badge state-empty">No listings yet</span>'


def market_card(s):
    rng = rng_for(s)
    meta = f'{s["n_listings"]} observed listings'
    if s["state"] == "limited":
        meta += f' · {s["n_dealers"]} dealer{"s" if s["n_dealers"] != 1 else ""}'
    return f"""
<a class="market-card" href="/reference/{safe_text(s['slug'])}">
 <div class="market-img">{img_html(s["image"], s["brand"] + " " + s["model"])}</div>
 <div class="market-body">
  <div class="market-name">{safe_text(s['brand'])} {safe_text(s['model'])}</div>
  <div class="market-ref">Ref {safe_text(s['ref'])}</div>
  <div class="market-range">{rng}</div>
  {state_badge(s)}
  <div class="market-meta"><span class="dot"></span>{meta} · {fmt_ago(s['updated'])}</div>
  <div class="market-sub">{safe_text(s['confidence'])} confidence · methodology v{market.METHODOLOGY_VERSION}</div>
 </div><span class="market-arrow">→</span></a>"""


def render_home(stats, params=None):
    params = params or {}
    hero = next((s for s in sorted(stats, key=lambda s: -(s["n_listings"]))
                 if s["valid"]), None) or (max(stats, key=lambda s: s["n_listings"])
                 if stats else None)

    # --- discovery filters (design brief #12), URL-shareable ---
    brand_f = (params.get("brand") or "").strip()
    scope_f = (params.get("scope") or "all").strip()
    price_f = (params.get("price") or "").strip()
    diversity_f = (params.get("diversity") or "").strip()

    filtered = stats
    if brand_f:
        filtered = [s for s in filtered if s["brand"].lower() == brand_f.lower()]
    if scope_f == "published":
        filtered = [s for s in filtered if s["valid"]]
    elif scope_f == "developing":
        filtered = [s for s in filtered if not s["valid"]]
    if price_f:
        try:
            ceiling = float(price_f)
            filtered = [s for s in filtered if s["valid"] and
                        s["published_range"] and
                        s["published_range"]["high"] is not None and
                        s["published_range"]["high"] <= ceiling]
        except ValueError:
            pass
    if diversity_f:
        try:
            min_d = int(diversity_f)
            filtered = [s for s in filtered if s["n_dealers"] >= min_d]
        except ValueError:
            pass

    published = [s for s in sorted(filtered, key=lambda s: -(s["n_listings"]))
                 if s["valid"]]
    developing = [s for s in sorted(filtered, key=lambda s: -(s["n_listings"]))
                  if not s["valid"]]

    def grid(cards):
        return "".join(market_card(s) for s in cards)

    published_block = ""
    if published:
        published_block = f"""
<section id="published" class="discovery-section">
 <div class="sec-head">
  <div><p class="eyebrow">PUBLISHED MARKET RANGES</p>
  <h2>References with enough independent evidence</h2></div>
 </div>
 <div class="market-grid">{grid(published)}</div>
</section>"""

    developing_block = ""
    if developing:
        developing_block = f"""
<section id="developing" class="discovery-section">
 <div class="sec-head">
  <div><p class="eyebrow">COVERAGE DEVELOPING</p>
  <h2>References WatchLedger is actively tracking</h2></div>
 </div>
 <div class="market-grid">{grid(developing)}</div>
</section>"""

    brands = sorted({s["brand"] for s in stats if s["brand"]})
    brand_opts = "".join(
        f'<option value="{safe_text(b)}"{" selected" if b == brand_f else ""}>{safe_text(b)}</option>'
        for b in brands)
    qs = urllib.parse.urlencode(
        {k: v for k, v in {"brand": brand_f, "scope": scope_f, "price": price_f,
                           "diversity": diversity_f}.items() if v})

    filters_html = f"""<form class="discovery-filters" method="get" action="/">
 <label>Brand
  <select name="brand"><option value="">All</option>{brand_opts}</select></label>
 <label>Status
  <select name="scope">
   <option value="all"{" selected" if scope_f == "all" else ""}>All tracked references</option>
   <option value="published"{" selected" if scope_f == "published" else ""}>Published ranges</option>
   <option value="developing"{" selected" if scope_f == "developing" else ""}>Coverage developing</option>
  </select></label>
 <label>Max price (USD)
  <input type="number" name="price" min="0" step="500" value="{safe_text(price_f)}" placeholder="any"></label>
 <label>Min dealers
  <select name="diversity">
   <option value="">Any</option>
   <option value="3"{" selected" if diversity_f == "3" else ""}>3+</option>
   <option value="5"{" selected" if diversity_f == "5" else ""}>5+</option>
  </select></label>
 <button class="btn" type="submit">Apply</button>
</form>"""
    if qs:
        filters_html += (f'<div class="filter-active"><a href="/">Clear filters</a>'
                         f' · {len(published)} published · '
                         f'{len(developing)} developing</div>')

    recent = sorted(stats, key=lambda s: s["updated"] or 0, reverse=True)[:5]
    recent_rows = ""
    for s in recent:
        recent_rows += f"""
<a class="recent-row" href="/reference/{safe_text(s['slug'])}">
 {img_html(s["image"], "", "recent-thumb")}
 <div><div class="recent-name">{safe_text(s['brand'])} {safe_text(s['model'])}</div>
 <div class="recent-ref">Ref {safe_text(s['ref'])}</div></div>
 <div class="recent-range"><div class="p">{rng_for(s)}</div><div class="m">{s['n_listings']} listings · updated {fmt_ago(s['updated'])}</div></div>
 <span class="recent-arrow">→</span></a>"""

    hero_block = ""
    if hero:
        if hero["valid"] and hero["published_range"]:
            hrange = rng_for(hero)
            hlabel = "Published observed asking-price range"
            hmeta = f"{hero['n_listings']} observed listings · {fmt_ago(hero['updated'])}"
        elif hero["state"] == "limited":
            hrange = "Coverage developing"
            hlabel = f"{hero['n_listings']} observed listings · no published range yet"
            hmeta = f"{hero['n_dealers']} dealers observed · {fmt_ago(hero['updated'])}"
        else:
            hrange = "No listings observed yet"
            hlabel = "WatchLedger is not yet tracking this reference"
            hmeta = "coverage requested"
        hero_block = f"""
<div class="hero-media">
 {img_html(hero.get("image"), hero["brand"] + " " + hero["model"], "hero-img")}
 <div class="hero-card">
  <div class="hc-brand">{safe_text(hero['brand'])} {safe_text(hero['model'])}</div>
  <div class="hc-ref">Ref {safe_text(hero['ref'])}</div>
  <div class="hc-range">{hrange}</div>
  <div class="hc-label">{hlabel}</div>
  <div class="hc-meta"><span class="dot"></span>{hmeta}</div>
 </div>
</div>"""

    search_data = [
        {
            "slug": safe_slug(s["slug"]),
            "brand": s["brand"] or "",
            "model": s["model"] or "",
            "ref": s["ref"] or "",
            "range": rng_for(s),
            "image_url": safe_external_url(s["image"]),
            "state": s["state"],
        }
        for s in stats
    ]

    return PAGE_HEAD + f"""
<section class="hero">
 <div>
  <p class="eyebrow">LIVE WATCH MARKET DATA</p>
  <h1>Know what a watch is worth — <em>today.</em></h1>
  <p class="hero-copy">Compare live dealer listings, see the published market range, and spot prices that stand out. Ranges are published only when the evidence supports them.</p>
  <div class="search-wrap">
   <div class="search"><span class="icon">⌕</span>
    <input id="q" type="text" placeholder="Search brand, model, or reference number" autocomplete="off">
   </div>
   <div class="suggestions" id="suggestions"></div>
   <div class="search-chips"><span class="chip-label">Popular searches</span>
    <button class="chip" type="button" data-search-value="Rolex 126610LN">Rolex 126610LN</button>
    <button class="chip" type="button" data-search-value="Patek Philippe 5711">Patek 5711</button>
    <button class="chip" type="button" data-search-value="Tudor Black Bay 58">Tudor BB58</button></div>
  </div>
 </div>
 {hero_block}
</section>

<section class="trust-strip">
 <span>Live dealer listings</span><span class="ts-dot">·</span>
 <span>Reference-level comparison</span><span class="ts-dot">·</span>
 <span>Honest, published market ranges</span>
</section>

<section class="sec-head compact" id="how">
 <div><p class="eyebrow">HOW IT WORKS</p>
 <h2>Three steps to a confident answer</h2></div>
</section>
<section class="step-section"><div class="steps">
 <div class="step"><div class="num">01</div><h3>We collect visible market listings</h3>
  <p>Dealer asking prices are pulled from free public sources and stored exactly as returned — with the source URL and fetch time.</p>
  <div class="step-visual sv-collect"><span class="mini-card"></span><span class="mini-card"></span><span class="mini-card"></span><span class="sv-arrow">→</span><span class="mini-tray"></span></div></div>
 <div class="step"><div class="num">02</div><h3>We compare like-for-like watches</h3>
  <p>Listings for the same reference are deduplicated and grouped by exact configuration, condition, and completeness.</p>
  <div class="step-visual sv-compare"><span class="mini-ref">126610LN</span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span></div></div>
 <div class="step"><div class="num">03</div><h3>You see where each price sits</h3>
  <p>The result is a published range, a typical price, and each listing's position — every number traceable to its source.</p>
  <div class="step-visual sv-range"><span class="sv-track"><span class="sv-band"></span><span class="sv-marker"></span></span><span class="sv-dots"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span></div></div>
</div></section>

<section id="discover">
 <div class="sec-head">
  <div><p class="eyebrow">MARKET DISCOVERY</p>
  <h2>Browse tracked markets</h2></div>
 </div>
 {filters_html}
</section>
{published_block}
{developing_block}

<section class="sec-head compact" id="recent">
 <div><p class="eyebrow">FRESHEST DATA</p>
 <h2>Recently updated pricing pages</h2></div>
</section>
<section class="step-section"><div class="recent-list">{recent_rows}</div></section>

<section id="trust">
 <div class="sec-head"><div><p class="eyebrow">THE DATA</p>
 <h2>Why collectors trust this</h2></div></div>
 <div class="trust-grid">
  <div class="trust-item"><div class="ic">⚲</div><h3>Real listings, not estimates</h3>
   <p>Every price is a real, observed dealer listing — with its photo, seller, and a direct link to verify it.</p></div>
  <div class="trust-item"><div class="ic">▦</div><h3>Deterministic, not generated</h3>
   <p>No AI, no guesses. Medians, ranges, and positions are computed by fixed rules from the raw payloads.</p></div>
  <div class="trust-item"><div class="ic">✓</div><h3>Traceable to the source</h3>
   <p>Each number carries its source URL and fetch time, and the raw data is browsable at <a href="/raw/">/raw</a>.</p></div>
 </div>
</section>
<script id="reference-data" type="application/json">{safe_json_script(search_data)}</script>
<script src="/static/home.js" defer></script>
""" + PAGE_FOOT


def render_not_found(what):
    return PAGE_HEAD + """<main class="narrow-page narrow-page-spaced"><h1>Not found</h1>
<p class="src">""" + safe_text(what) + """ is not in this ledger. See the <a href="/">homepage</a> for tracked references.</p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_raw_index():
    entries = []
    for root, _, files in os.walk(RAW_DIR):
        rel = os.path.relpath(root, RAW_DIR)
        for f in sorted(files):
            if f.endswith(".json"):
                p = os.path.join(rel, f) if rel != "." else f
                entries.append(p)
    lis = "".join(
        f"<li><a href='/raw/{safe_text(urllib.parse.quote(p))}'>{safe_text(p)}</a> · "
        f"{os.path.getsize(os.path.join(RAW_DIR, p)):,} bytes</li>"
        for p in sorted(entries))
    return PAGE_HEAD + """<main class="narrow-page narrow-page-spaced"><h1>Raw data — the source of truth</h1>
<p class="src">Every payload exactly as returned by the MEW API, with source_url and fetched_at. The ledger and every report derive from these files alone.
Full payload redistribution may be restricted by source terms; WatchLedger uses these files for internal derivation and links out to each listing for verification.</p>
<ul>""" + lis + """</ul></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_sources(db):
    rows = q(db, """SELECT name, domain, access_method, permission_status,
                    image_usage_status, attribution_requirements,
                    last_terms_reviewed_at FROM source ORDER BY domain""")
    lis = "".join(
        f"""<tr><td>{safe_text(r[0] or r[1])}</td>
            <td class="price-cell">{safe_text(r[1])}</td>
            <td>{safe_text(r[2] or '—')}</td>
            <td>{safe_text(r[3] or '—')}</td>
            <td>{safe_text(r[4] or '—')}</td>
            <td>{safe_text(r[5] or '—')}</td></tr>"""
        for r in rows)
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>Data sources</h1>
<p class="src">Every listing on this site originates from a source below. Access method,
permission, and image-usage status are recorded here so each provider's terms are visible
and auditable.</p>
<table class="listing-table"><thead><tr><th>Source</th><th>Domain</th><th>Access</th>
<th>Permission</th><th>Image usage</th><th>Attribution</th></tr></thead>
<tbody>{lis}</tbody></table></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_methodology():
    return PAGE_HEAD + """<main class="narrow-page narrow-page-spaced"><h1>Methodology</h1>
<div class="methodology">
 <h2>What WatchLedger publishes</h2>
 <p>WatchLedger publishes a market range for a reference only when the observed
 evidence is strong enough. When it is not, the page says so — a polished range
 is never more important than an honest one.</p>

 <h3>1. Exact configuration matching</h3>
 <p>A listing belongs to a reference when the source API matched it to that
 reference. It counts toward pricing only when its configuration (case material)
 matches the reference's active configuration. Other configurations are shown
 separately as variants and never influence the exact range.</p>

 <h3>2. Minimum gates for a published range</h3>
 <p>A range is published only when all of these pass:</p>
 <ul>
  <li>At least %d unique listings (after deduplication)</li>
  <li>At least %d independent dealers</li>
  <li>At least %d%% of listings have a published price</li>
  <li>At least %d%% of listings observed within the last %d hours</li>
 </ul>

 <h3>3. Duplicate clustering</h3>
 <p>Rows that are the same listing (same source ID, URL, or fingerprint) are
 grouped into one cluster. Rows that are likely duplicates (same dealer, same
 configuration, near-identical price, and similar title) share a cluster at
 lower confidence. Only the representative listing of each cluster is counted.</p>

 <h3>4. Outlier handling</h3>
 <p>Prices are combined with a weighted median and weighted 10th/90th
 percentiles, weighted by freshness and completeness. Outliers flagged by a
 robust MAD filter (z &gt; %g) are excluded from the range but are never
 deleted — they stay visible in the ledger and evidence.</p>

 <h3>5. Asking prices versus sold prices</h3>
 <p>All listing data is asking prices from dealers, not completed sale prices.
 Auction hammer prices are shown separately and are never mixed into the
 listing range.</p>

 <h3>6. Freshness policy</h3>
 <p>Observations older than %d hours stop counting toward freshness. Freshness
 is reported as the share of listings observed within that window.</p>

 <h3>7. Source coverage limits</h3>
 <p>Coverage reflects the free public sources WatchLedger can reach today.
 More sources and more listings raise coverage, which is why developing
 references show no range yet.</p>

 <h3>8. What &ldquo;Potential deal&rdquo; means</h3>
 <p>A listing is a potential deal when it sits below the observed comparable
 range. It is a good lead to investigate, not a guarantee of value.</p>

 <h3>9. What WatchLedger does not verify</h3>
 <p>WatchLedger does not verify condition claims, authenticity, or the current
 live status of a listing. All availability is seller-reported at fetch time.
 We call listings <em>observed</em>, never <em>active</em> or <em>verified</em>.</p>

 <p class="src"><a href="/">Back to the homepage</a></p>
</div></main>
<script src="/static/home.js" defer></script>""" % (
        market.MIN_CLUSTERS, market.MIN_DEALERS,
        int(market.MIN_PRICE_RATIO * 100), int(market.MIN_FRESHNESS * 100),
        market.FRESH_WINDOW // 3600, market.ROBUST_Z_CUTOFF,
        market.FRESH_WINDOW // 3600) + PAGE_FOOT


def render_robots():
    return ("User-agent: *\n"
            "Allow: /\n"
            "Disallow: /raw/\n"
            "Disallow: /api/\n"
            "Sitemap: https://watchledger-delta.vercel.app/sitemap.xml\n")


def render_sitemap(stats):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    urls = ['<url><loc>https://watchledger-delta.vercel.app/</loc>'
            f'<lastmod>{now}</lastmod><priority>1.0</priority></url>',
            '<url><loc>https://watchledger-delta.vercel.app/methodology</loc>'
            f'<lastmod>{now}</lastmod><priority>0.8</priority></url>']
    for s in sorted(stats, key=lambda x: x["slug"]):
        urls.append(
            f'<url><loc>https://watchledger-delta.vercel.app/reference/{s["slug"]}</loc>'
            f'<lastmod>{now}</lastmod><priority>0.9</priority></url>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) + "\n</urlset>\n")


def render_track_confirmation(slug, email):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>Confirm your tracking</h1>
<p>We'll email {safe_text(email)} when the market for {safe_text(slug)} changes meaningfully.
Please confirm to start tracking. <a href="/reference/{safe_text(safe_slug(slug))}">Back to the watch page →</a></p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_track_done(email):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>You are tracking this watch</h1>
<p>{safe_text(email)} is now set to receive WatchLedger alerts.
One-click unsubscribe is available in every email. <a href="/">Browse more markets →</a></p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_unsubscribed(email):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>You are unsubscribed</h1>
<p>{safe_text(email)} will no longer receive watchledger alerts.
You can resubscribe from any watch page.</p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_request_done(query):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>Coverage requested</h1>
<p>We've recorded a request for <b>{safe_text(query)}</b>. When WatchLedger starts
tracking it, this page will appear in search. In the meantime, browse
<a href="/">tracked markets</a> or request more coverage.</p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "watchledger/0.3"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_security_headers(self, content_type):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy",
                         "camera=(), microphone=(), geolocation=(), payment=()")
        if content_type.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "; ".join([
                    "default-src 'self'",
                    "base-uri 'self'",
                    "object-src 'none'",
                    "frame-ancestors 'none'",
                    "form-action 'self'",
                    "script-src 'self'",
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                    "font-src 'self' https://fonts.gstatic.com",
                    "img-src 'self' https:",
                    "connect-src 'self'",
                ]),
            )

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_security_headers(ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, obj):
        self.send(code, json.dumps(obj, indent=2, default=str), "application/json; charset=utf-8")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            self.route(path)
        except sqlite3.Error:
            self.log_error("database request failed")
            self.send(500, render_not_found("Internal server error"))
        except BrokenPipeError:
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        path = urllib.parse.urlparse(self.path).path
        params = urllib.parse.parse_qs(body)
        try:
            if path.startswith("/api/track"):
                self.route_track(params)
            elif path.startswith("/api/request"):
                self.route_request(params)
            elif path.startswith("/unsubscribe"):
                self.send(404, render_not_found("Unsubscribe link"))
            else:
                self.send(404, render_not_found(path))
        except sqlite3.Error:
            self.log_error("database request failed")
            self.send(500, json.dumps({"error": "internal error"}),
                      "application/json; charset=utf-8")
        except BrokenPipeError:
            pass

    def route_track(self, params):
        action = params.get("action", [""])[0]
        email = (params.get("email", [""])[0] or "").strip().lower()
        slug = safe_slug(params.get("slug", [""])[0])
        if action == "track":
            if not email or "@" not in email or not slug:
                self.send(400, json.dumps({"error": "email and slug required"}),
                          "application/json; charset=utf-8")
                return
            db = open_db()
            meta = q(db, "SELECT slug FROM references_meta WHERE slug=?", (slug,))
            if not meta:
                db.close()
                self.send(404, json.dumps({"error": "unknown reference"}),
                          "application/json; charset=utf-8")
                return
            alerts = [a for a in params.get("alerts", [])
                      if a in {"new_listing", "below_typical", "range_change",
                               "coverage_ready"}]
            if not alerts:
                alerts = ["new_listing"]
            import hashlib
            token = hashlib.sha256(
                (email + secrets.token_hex(16)).encode()).hexdigest()
            confirm_token = hashlib.sha256(
                (token + "confirm" + secrets.token_hex(8)).encode()).hexdigest()
            db.execute(
                "INSERT OR REPLACE INTO watch_users (id, email, unsubscribe_token,"
                " confirm_token, created_at) VALUES (?,?,?,?,?)",
                (email, email, token, confirm_token, time.time()))
            db.execute(
                "INSERT OR IGNORE INTO watchlist_item (id, user_id,"
                " reference_slug, created_at, active) VALUES (?,?,?,?,1)",
                (f"{email}:{slug}", email, slug, time.time()))
            for t in alerts:
                db.execute(
                    "INSERT OR REPLACE INTO alert_preference (id, watchlist_item_id,"
                    " alert_type, enabled) VALUES (?,?,?,1)",
                    (f"{email}:{slug}:{t}", f"{email}:{slug}", t))
            db.commit()
            db.close()
            self.send(200, json.dumps({
                "ok": True, "slug": slug,
                "confirm_url": f"/confirm?token={confirm_token}",
                "alerts": alerts,
            }), "application/json; charset=utf-8")
            return
        self.send(400, json.dumps({"error": "unknown action"}),
                  "application/json; charset=utf-8")

    def route_request(self, params):
        query = (params.get("query", [""])[0] or "").strip()[:200]
        if not query:
            self.send(400, json.dumps({"error": "query required"}),
                      "application/json; charset=utf-8")
            return
        db = open_db()
        db.execute(
            "CREATE TABLE IF NOT EXISTS coverage_request ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL,"
            " requested_at REAL)")
        db.execute("INSERT INTO coverage_request (query, requested_at) "
                   "VALUES (?,?)", (query, time.time()))
        db.commit()
        db.close()
        self.send(200, json.dumps({"ok": True, "query": query}),
                  "application/json; charset=utf-8")

    def route(self, path):
        if path == "/" or path == "/index.html":
            db = open_db()
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self.send(200, render_home(index_stats(db), params))
            db.close()
        elif path == "/raw" or path == "/raw/":
            self.send(200, render_raw_index())
        elif path == "/sources" or path == "/sources/":
            db = open_db()
            self.send(200, render_sources(db))
            db.close()
        elif path == "/methodology":
            self.send(200, render_methodology())
        elif path == "/robots.txt":
            self.send(200, render_robots(), "text/plain; charset=utf-8")
        elif path == "/sitemap.xml":
            db = open_db()
            self.send(200, render_sitemap(index_stats(db)),
                      "application/xml; charset=utf-8")
            db.close()
        elif path == "/confirm":
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = (params.get("token", [""])[0] or "").strip()
            db = open_db()
            row = q(db, "SELECT email FROM watch_users WHERE confirm_token=?",
                    (token,))
            if not row:
                db.close()
                self.send(404, render_not_found("Confirmation link"))
                return
            db.execute("UPDATE watch_users SET confirmed=1 WHERE email=?",
                       (row[0][0],))
            db.commit()
            email = row[0][0]
            db.close()
            self.send(200, render_track_done(email))
        elif path.startswith("/unsubscribe"):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = (params.get("token", [""])[0] or "").strip()
            db = open_db()
            row = q(db, "SELECT email FROM watch_users WHERE unsubscribe_token=?",
                    (token,))
            if not row:
                db.close()
                self.send(404, render_not_found("Unsubscribe link"))
                return
            db.execute("DELETE FROM alert_preference WHERE watchlist_item_id IN "
                       "(SELECT id FROM watchlist_item WHERE user_id=?)",
                       (row[0][0],))
            db.execute("DELETE FROM watchlist_item WHERE user_id=?", (row[0][0],))
            db.execute("DELETE FROM watch_users WHERE email=?", (row[0][0],))
            db.commit()
            db.close()
            self.send(200, render_unsubscribed(row[0][0]))
        elif path.startswith("/raw/"):
            self.serve_raw(path[5:])
        elif path == "/api/references.json":
            db = open_db()
            self.send_json(200, index_stats(db))
            db.close()
        elif path.startswith("/api/reference/"):
            raw = path[len("/api/reference/"):]
            if raw.endswith(".json"):
                raw = raw[:-5]
            slug = safe_slug(raw)
            if not slug:
                self.send(404, json.dumps({"error": "unknown reference"}),
                          "application/json; charset=utf-8")
                return
            db = open_db()
            d = build_report(db, slug)
            db.close()
            if not d:
                self.send(404, json.dumps({"error": "unknown reference"}),
                          "application/json; charset=utf-8")
            else:
                self.send_json(200, d)
        elif path.startswith("/reference/"):
            slug = safe_slug(path[len("/reference/"):])
            if not slug:
                self.send(404, render_not_found("Unknown reference"))
                return
            db = open_db()
            d = build_report(db, slug)
            db.close()
            if not d:
                self.send(404, render_not_found(slug))
            else:
                self.send(200, render(d))
        elif path.startswith("/api/track"):
            self.send(405, "method not allowed", "text/plain; charset=utf-8")
        elif path.startswith("/api/request"):
            self.send(405, "method not allowed", "text/plain; charset=utf-8")
        elif path.startswith("/static/"):
            self.serve_static(path[len("/static/"):])
        else:
            self.send(404, render_not_found(path))

    def serve_raw(self, rel):
        root = os.path.realpath(RAW_DIR)
        target = os.path.realpath(os.path.join(root, rel))
        if not target.startswith(root + os.sep) and target != root:
            self.send(403, "forbidden")
            return
        if os.path.isdir(target):
            self.send(200, render_raw_index())
            return
        if not os.path.isfile(target):
            self.send(404, "not found")
            return
        with open(target, "rb") as fh:
            self.send(200, fh.read(), "application/json; charset=utf-8")

    def serve_static(self, rel):
        root = os.path.realpath(STATIC_DIR)
        target = os.path.realpath(os.path.join(root, rel))
        if not target.startswith(root + os.sep):
            self.send(403, "forbidden")
            return
        if not os.path.isfile(target):
            self.send(404, "not found")
            return
        ctype = {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".woff2": "font/woff2",
        }.get(os.path.splitext(target)[1].lower(), "application/octet-stream")
        with open(target, "rb") as fh:
            self.send(200, fh.read(), ctype)


def main():
    os.makedirs(STATIC_DIR, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"watchledger serving on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()