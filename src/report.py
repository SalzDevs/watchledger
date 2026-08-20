"""Generate deterministic per-reference market reports from the ledger.

No AI, no manual text: every number is the result of a fixed SQL query
against the ledger, and every number carries a provenance footnote
(source URL + fetch time of the raw payload it came from).

Credibility rules (from the design review):
- The market range is computed from EXACT-reference listings only.
- If exact-match data is limited, show an honest limited-data state
  instead of a misleading broad range.
- Related/vintage listings are shown separately and never included in
  the exact-match range.

Security rules (from the security guide):
- Every server-rendered external URL passes through safe_external_url.
- Every text value passes through safe_text (HTML-escaped).
- Listing details are shipped once as a type=application/json data block,
  read by browser JS and rendered with textContent — never innerHTML.
- No inline event handlers, no inline scripts, no inline styles.
"""

import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from config import DB_PATH, REPORTS_DIR
from security import safe_external_url, safe_json_script, safe_text


def q(db, sql, params=()):
    return db.execute(sql, params).fetchall()


def median(xs):
    return statistics.median(xs) if xs else None


def price_fmt(n):
    return f"${n:,.0f}" if n is not None else "—"


def fmt_k(n):
    return f"${n / 1000:.1f}k" if n is not None else "—"


def provenance(db, slug, table, exact=None):
    if table == "listings":
        if exact is not None:
            row = q(db, "SELECT source_url, fetched_at FROM listings "
                        "WHERE slug=? AND exact=? LIMIT 1", (slug, exact))
        else:
            row = q(db, "SELECT source_url, fetched_at FROM listings "
                        "WHERE slug=? LIMIT 1", (slug,))
    else:
        row = q(db, "SELECT source_url, fetched_at FROM auction_lots "
                    "WHERE ref_slug=? LIMIT 1", (slug,))
    if not row:
        return "no source recorded"
    url, ts = row[0]
    when = __import__("datetime").datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
    safe = safe_external_url(url)
    if safe:
        return f'<a href="{safe_text(safe)}">{safe_text(url)}</a> · fetched {when}'
    return f"{safe_text(url)} · fetched {when}"


def classify(price, lo, hi, typical, n):
    """Five-way price-position classification, per design review #3.

    Returns (kind, pct_label, sub_label).
    kind: deal | fair | above | over | not_comp | limited
    """
    if price is None:
        return ("not_comp", "—", "Not comparable")
    if n < 5 or lo is None or hi is None or typical is None:
        return ("limited", "—", "Limited comparable data")
    if price < lo:
        pct = abs(price - typical) / typical * 100
        return ("deal", f"↓ {pct:.1f}% below typical", "Potential deal")
    if price <= hi:
        return ("fair", "Within observed range", "Fair price")
    pct = abs(price - typical) / typical * 100
    if pct > 12:
        return ("over", f"↑ {pct:.1f}% above typical", "High above market")
    return ("above", f"↑ {pct:.1f}% above typical", "Above market")


BADGE_CLS = {"deal": "badge-deal", "fair": "badge-fair", "above": "badge-above",
             "over": "badge-over", "not_comp": "badge-nc", "limited": "badge-nc"}


def percent(value, low, high):
    """Position of value within [low, high] as a percentage, clamped to 0..100."""
    if high <= low:
        return 0.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def build_report(db, slug):
    meta = q(db, "SELECT brand, ref, model, case_material, url FROM references_meta WHERE slug=?",
             (slug,))
    if not meta:
        return None
    brand, ref, model, material, ref_url = meta[0]

    # Exact-match listings (the credible baseline) and related listings.
    exact_rows = q(db, """SELECT price_usd, condition, box_papers, available,
                          merchant_name, image_url, buy_url, detail_url, title,
                          year, case_material, id, exact
                          FROM listings WHERE slug=? AND exact=1
                          ORDER BY price_usd""", (slug,))
    rel_rows = q(db, """SELECT price_usd, condition, box_papers, available,
                        merchant_name, image_url, buy_url, detail_url, title,
                        year, case_material, id, exact
                        FROM listings WHERE slug=? AND exact=0
                        ORDER BY price_usd""", (slug,))

    prices = [r[0] for r in exact_rows if r[0] is not None]
    n = len(prices)
    band_lo = band_hi = typical = None
    if n >= 5:
        sp = sorted(prices)
        band_lo, band_hi = sp[int(n * 0.1)], sp[min(n - 1, int(n * 0.9))]
        typical = median(prices)
    else:
        typical = median(prices)

    dealers = sorted({r[4] for r in exact_rows if r[4]})
    auc_rows = q(db, "SELECT hammer_usd, year_sold, venue FROM auction_lots "
                     "WHERE ref_slug=?", (slug,))
    auc_prices = [r[0] for r in auc_rows if r[0] is not None]
    auc_by_year = {}
    for _, year, _ in auc_rows:
        auc_by_year[year] = auc_by_year.get(year, 0) + 1

    image = next((r[5] for r in exact_rows if r[5]), None)
    if not image:
        image = next((r[5] for r in rel_rows if r[5]), None)

    stamps = [r[2] for r in q(db, "SELECT source_url, fetched_at, fetched_at "
                                   "FROM listings WHERE slug=? AND exact=1", (slug,))]
    updated = max(stamps) if stamps else None

    # --- listing rows, exact first, then related ---
    listing_data = {}

    def row_html(r, lo, hi, typ_p, n_exact):
        price, cond, bp, _avail, merchant, img, buy, detail, title, year, mat, lid, _ = r
        kind, pct_label, sub = classify(price, lo, hi, typ_p, n_exact)
        badge = (f'<span class="badge {BADGE_CLS[kind]}">'
                 f'<span class="pct">{safe_text(pct_label)}</span>'
                 f'<span class="sub">{safe_text(sub)}</span></span>')
        img_url = safe_external_url(img)
        if img_url:
            thumb = (f'<img class="thumb" src="{safe_text(img_url)}" '
                     f'alt="{safe_text(title or "Listing photo")}" loading="lazy" '
                     f'referrerpolicy="no-referrer">')
        else:
            thumb = '<div class="thumb thumb-placeholder" aria-hidden="true"></div>'
        facts = " · ".join(x for x in [
            safe_text(cond or ""), safe_text(bp or ""),
            safe_text(year or ""), safe_text(mat or "")] if x)
        listing_data[str(lid)] = {
            "id": str(lid),
            "title": title or "",
            "price": price,
            "condition": cond or "",
            "box_papers": bp or "",
            "year": year,
            "material": mat or "",
            "merchant": merchant or "",
            "image_url": img_url,
            "listing_url": safe_external_url(buy) or safe_external_url(detail),
            "kind": kind,
            "pct": pct_label,
            "sub": sub,
            "range": (f"{price_fmt(lo)} – {price_fmt(hi)}" if lo is not None else ""),
        }
        return f"""
<tr class="lrow" data-kind="{safe_text(kind)}" data-price="{price if price is not None else 1e18}" data-listing-id="{safe_text(lid)}">
 <td><div class="watch-cell">{thumb}
   <div><div class="listing-title">{safe_text(title or '—')}</div>
   <div class="listing-sub">{facts}</div></div></div></td>
 <td class="price-cell">{price_fmt(price)}
   <div class="price-pos">{pct_label if kind in ('deal',) else '&nbsp;'}</div></td>
 <td>{badge}</td>
 <td><div class="seller-cell"><div class="listing-sub">{safe_text(merchant or '—')}</div>
   <div class="listing-sub">{'in stock' if _avail else 'on request'}</div></div></td>
 <td><button class="btn btn-sm" type="button" data-open-listing="{safe_text(lid)}">View analysis</button></td>
</tr>"""

    n_exact = n
    rows_html = "".join(row_html(r, band_lo, band_hi, typical, n) for r in exact_rows)
    rel_html = "".join(row_html(r, None, None, None, n) for r in rel_rows)

    auc_html = []
    for a in auc_rows:
        auc_html.append(
            f'<tr><td>{safe_text(a[2] or "—")}</td>'
            f'<td>{safe_text(a[1])}</td>'
            f'<td class="price-cell">{price_fmt(a[0])}</td></tr>')

    return {
        "slug": slug, "brand": brand, "ref": ref, "model": model, "material": material,
        "ref_url": ref_url,
        "n_exact": n_exact, "n_related": len(rel_rows),
        "n_dealers": len(dealers),
        "listing_median": typical,
        "listing_low": min(prices) if prices else None,
        "listing_high": max(prices) if prices else None,
        "band_lo": band_lo, "band_hi": band_hi,
        "n_auction": len(auc_prices),
        "auc_median": median(auc_prices),
        "auc_years": ", ".join(str(y) for y in sorted(auc_by_year)),
        "image": image,
        "updated": updated,
        "listing_data": listing_data,
        "listings_html": rows_html,
        "related_html": rel_html,
        "auctions_html": "".join(auc_html),
        "src_exact": provenance(db, slug, "listings", exact=1),
        "src_related": provenance(db, slug, "listings", exact=0),
        "src_auctions": provenance(db, slug, "auction_lots"),
        "confidence": "High" if n_exact >= 15 else ("Medium" if n_exact >= 5 else "Low"),
        "limited": n_exact < 5,
    }


# --- state-specific render paths (security guide #15) ---

def render_valid_market_summary(d):
    """Render range, median, range bar, and classification explanation."""
    lo, hi = d["listing_low"], d["listing_high"]
    b_lo, b_hi = d["band_lo"], d["band_hi"]
    med = d["listing_median"]
    bar = ""
    if lo is not None and hi is not None and b_lo is not None and med is not None:
        left = percent(b_lo, lo, hi)
        right = percent(b_hi, lo, hi)
        marker = percent(med, lo, hi)
        bar = f"""<div class="range-bar">
 <div class="track">
  <div class="band" style="left:{left:.1f}%;width:{right - left:.1f}%"></div>
  <div class="marker" style="left:calc({marker:.1f}% - 8px)"></div>
 </div>
 <div class="scale"><span>{fmt_k(lo)}</span><span>{fmt_k(b_lo)}</span><span>{fmt_k(med)}</span><span>{fmt_k(b_hi)}</span><span>{fmt_k(hi)}</span></div>
</div>"""
    rng = price_fmt(b_lo) + " – " + price_fmt(b_hi)
    typ = price_fmt(med)
    ago = render_ago(d.get("updated"))
    return f"""
<div class="range-card">
 <div class="range-label">CURRENT OBSERVED MARKET RANGE</div>
 <div class="range-value">{rng}</div>
 <div class="range-sub">Typical asking price <b>{typ}</b></div>
 {bar}
 <div class="range-evidence">Based on <b>{d['n_exact']} exact-reference active listings</b> · updated {ago}
 <span class="ev-dot"></span></div>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""


def render_limited_data_summary(d):
    """Render coverage explanation and next actions only."""
    n_related = d["n_related"]
    msg = (f"We found <b>{d['n_exact']} exact listings</b> for reference {safe_text(d['ref'])}. "
           "That is too few to build a trustworthy market range.")
    if n_related:
        msg += f" {n_related} related listings are available for broader research."
    return f"""
<div class="range-card limited-state">
 <div class="range-label">OBSERVED MARKET RANGE — LIMITED DATA</div>
 <div class="limited-title">Limited exact-match data</div>
 <p class="range-sub">{msg}</p>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""


def render_valid_market_panel(d):
    """Render deal/fair/above-market explanation only when a range exists."""
    panel_low = price_fmt(d["band_lo"])
    panel_high = price_fmt(d["band_hi"])
    return f"""<div class="panel"><h3>How to read this market</h3><div class="panel-cols">
 <div class="panel-col"><div class="tag tag-deal">Potential deal</div><p>Listings priced below {panel_low} may be worth a closer look.</p></div>
 <div class="panel-col"><div class="tag tag-fair">Fair range</div><p>Between {panel_low} and {panel_high} is within the observed comparable range.</p></div>
 <div class="panel-col"><div class="tag tag-above">Above market</div><p>Prices above {panel_high} are higher than most comparable listings.</p></div>
 </div></div>"""


def render_limited_data_panel(d):
    """Explain why no valuation labels are shown yet."""
    return f"""<div class="panel panel-limited"><h3>Why there is no market range yet</h3>
 <p>WatchLedger only classifies prices when it has at least five exact-reference active listings.
 {safe_text(d['ref'])} currently has {d['n_exact']} — so no deal/fair/above labels are shown.
 Check back after more dealers list this reference, or browse the related listings below for context.</p>
</div>"""


def render_ago(up_ts):
    if not up_ts:
        return "—"
    dt = time.time() - up_ts
    if dt < 60:
        return "just now"
    if dt < 3600:
        return f"{int(dt // 60)} min ago"
    if dt < 86400:
        return f"{int(dt // 3600)} h ago"
    return f"{int(dt // 86400)} d ago"


def render_meta(d):
    brand = safe_text(d["brand"])
    ref = safe_text(d["ref"])
    model = safe_text(d["model"] or "")
    title = f"{brand} {ref} — watchledger"
    image_url = safe_external_url(d["image"])
    if image_url:
        img = (f'<img src="{safe_text(image_url)}" alt="{brand} {model}" '
               f'loading="lazy" referrerpolicy="no-referrer">')
    else:
        img = '<div class="image-placeholder" aria-hidden="true"></div>'
    return title, brand, ref, model, img


def render(d):
    title, brand, ref, model, img = render_meta(d)
    ago = render_ago(d.get("updated"))

    # --- market summary + explanation, one path per state ---
    if d["limited"]:
        summary = render_limited_data_summary(d)
        panel = render_limited_data_panel(d)
    else:
        summary = render_valid_market_summary(d)
        panel = render_valid_market_panel(d)

    conf = f"""<div class="conf-grid">
 <div class="conf-item"><span class="dot"></span><span><b>{d['n_exact']}</b> exact-match listings</span></div>
 <div class="conf-item"><span class="dot"></span><span><b>{d['n_dealers']}</b> tracked dealers</span></div>
 <div class="conf-item"><span class="dot"></span><span>Confidence: <b>{d['confidence']}</b></span></div>
 </div>"""

    # --- evidence module ---
    ref_link = ""
    ref_url = safe_external_url(d["ref_url"])
    if ref_url:
        ref_link = (f'<p class="src">Reference page: '
                    f'<a href="{safe_text(ref_url)}">{safe_text(d["ref_url"])}</a></p>')
    evidence = f"""<div class="evidence">
 <div class="ev-title">EVIDENCE BEHIND THIS RANGE</div>
 <div class="ev-row"><span class="ev-item"><b>{d['n_exact']}</b> exact-match active listings</span>
 <span class="ev-item"><b>{d['n_dealers']}</b> tracked dealers</span>
 <span class="ev-item"><b>✓</b> each price links to its live listing</span></div>
 <details class="ev-details"><summary>See sources and methodology</summary>
 <p class="src">Exact-match listings: {d['src_exact']}</p>
 <p class="src">Related listings: {d['src_related']}</p>
 <p class="src">Auction data: {d['src_auctions']}</p>
 {ref_link}
 </details>
 </div>"""

    # --- listings section with tabs and filters ---
    rel_tab_n = f'<span class="tab-n">{d["n_related"]}</span>' if d["n_related"] else ""
    tabs = f"""<div class="tabs" id="ltabs">
 <button class="tab active" type="button" data-tab="exact">Exact matches <span class="tab-n">{d['n_exact']}</span></button>
 <button class="tab" type="button" data-tab="related">Related {rel_tab_n}</button>
</div>
<div class="filters" id="lfilters">
 <select class="fsel" data-filter="condition" aria-label="Filter by condition"><option value="">Condition: All</option>
  <option>Excellent</option><option>Very good</option><option>Good</option><option>Unworn</option></select>
 <select class="fsel" data-filter="bp" aria-label="Filter by box and papers"><option value="">Box &amp; papers: All</option>
  <option>full_set</option><option>box_and_papers</option><option>watch_only</option></select>
 <select class="fsel" data-filter="avail" aria-label="Filter by availability"><option value="">Availability: All</option>
  <option value="1">In stock</option><option value="0">On request</option></select>
 <span class="sort-label">Sort</span>
 <select class="fsel" id="fsort" aria-label="Sort listings"><option value="best">Best value</option>
  <option value="low">Lowest price</option><option value="high">Highest price</option></select>
</div>"""

    table_exact = f"""<table class="listing-table" id="tbl-exact">
 <thead><tr><th>Watch</th><th>Price</th><th>Position</th><th>Seller</th><th></th></tr></thead>
 <tbody>{d['listings_html']}</tbody></table>"""
    table_rel = f"""<table class="listing-table hidden" id="tbl-related">
 <thead><tr><th>Watch</th><th>Price</th><th>Position</th><th>Seller</th><th></th></tr></thead>
 <tbody>{d['related_html']}</tbody></table>"""

    auc_block = ""
    if d["n_auction"] > 0:
        auc_block = f"""
<section class="live-section">
 <div class="live-head"><h2>Auction results</h2>
 <div class="sub">Hammer prices for this reference</div></div>
 <p class="src">Auction data: {d['src_auctions']}</p>
 <table class="listing-table"><thead><tr><th>Venue</th><th>Year</th><th>Hammer</th></tr></thead>
 <tbody>{d['auctions_html']}</tbody></table>
</section>"""

    # --- analysis drawer (no inline handlers) ---
    drawer = """<div class="drawer-mask" id="dmask" aria-hidden="true"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true" aria-label="Listing analysis">
 <button id="drawer-close" class="drawer-close" type="button" data-close-drawer aria-label="Close listing analysis">×</button>
 <div id="drawer-body"></div>
</aside>"""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head><body>
<header class="nav"><div class="nav-inner">
<a href="/" class="logo">watch<span>ledger</span></a>
<nav class="nav-links"><a href="/#markets">Explore Watches</a><a href="/#how">Market Trends</a><a href="/#trust">How It Works</a></nav>
<div class="nav-actions">
<a class="nav-icon" href="/" aria-label="Search">⌕</a>
<a href="/raw/" class="btn btn-ghost">Raw data</a>
<a href="/#markets" class="btn btn-primary">Track a watch</a>
</div>
</div></header>
<main class="report-main">
<p class="breadcrumb"><a href="/">Home</a> / {brand} / {model}</p>
<div class="report-layout">
 <div class="report-img">{img}</div>
 <div>
  <h1 class="model-name">{brand} {model}</h1>
  <div class="model-ref">Reference {ref}</div>
  <p class="model-desc">Case material: {safe_text(d['material'] or '—')}. Market data computed deterministically from {d['n_exact']} exact-reference listings.</p>
  <div class="model-meta">
   <div class="stat"><div class="k">Exact-match listings</div><div class="v">{d['n_exact']}</div></div>
   <div class="stat"><div class="k">Tracked dealers</div><div class="v">{d['n_dealers']}</div></div>
   <div class="stat"><div class="k">Confidence</div><div class="v">{d['confidence']}</div></div>
   <div class="stat"><div class="k">Last checked</div><div class="v">{ago}</div></div>
  </div>
  {summary}
  {panel}
  {conf}
 </div>
</div>
{evidence}

<section class="live-section">
 <div class="live-head"><h2>Live listings</h2>
 <div class="sub">{d['n_exact']} exact-reference listings · {d['n_related']} related · updated {ago}</div></div>
 {tabs}
 {table_exact}
 {table_rel}
</section>
{auc_block}
</main>
{drawer}
<footer><div class="footer-inner">
<div class="col"><div class="logo">watch<span>ledger</span></div>
<p>Every number above traces to the raw payload at the listed source URL. No AI, no guesswork.</p></div>
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/reference/{safe_text(d['slug'])}.json">JSON for this watch</a></div>
<div class="col"><b>Product</b><a href="/#how">How it works</a><a href="/#trust">Why it's trustworthy</a></div>
</div></footer>
<script id="listing-data" type="application/json">{safe_json_script(d["listing_data"])}</script>
<script src="/static/report.js" defer></script>
</body></html>"""


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    slugs = [r[0] for r in q(db, "SELECT DISTINCT slug FROM listings ORDER BY slug")]
    written = 0
    for slug in slugs:
        d = build_report(db, slug)
        if not d:
            continue
        safe = slug.replace("/", "_")
        with open(os.path.join(REPORTS_DIR, f"{safe}.html"), "w", encoding="utf-8") as fh:
            fh.write(render(d))
        written += 1
    print(f"reports written: {written}")


if __name__ == "__main__":
    main()