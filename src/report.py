"""Generate deterministic per-reference market reports from the ledger.

No AI, no manual text: every number is the result of a fixed SQL query
against the ledger, and every number carries a provenance footnote
(source URL + fetch time of the raw payload it came from).
"""

import html
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))
from config import DB_PATH, REPORTS_DIR


def q(db, sql, params=()):
    return db.execute(sql, params).fetchall()


def median(xs):
    return statistics.median(xs) if xs else None


def price_fmt(n):
    return f"${n:,.0f}" if n is not None else "—"


def provenance(db, slug, table):
    col = "ref_slug" if table == "auction_lots" else "slug"
    row = q(db, f"SELECT source_url, fetched_at FROM {table} WHERE {col}=? LIMIT 1",
            (slug,))
    if not row:
        return "no source recorded"
    url, ts = row[0]
    when = __import__("datetime").datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
    return f'<a href="{html.escape(url)}">{html.escape(url)}</a> · fetched {when}'


def classify(price, lo, hi, n):
    if n < 5 or price is None or lo is None or hi is None:
        return ("limited", "Limited comparable data")
    if price < lo:
        return ("deal", f"↓ {abs(price - (lo + hi) / 2) / max((lo + hi) / 2, 1) * 100:.1f}% below typical")
    if price > hi:
        pct = abs(price - (lo + hi) / 2) / max((lo + hi) / 2, 1) * 100
        return ("over" if pct > 12 else "above", f"↑ {pct:.1f}% above typical")
    return ("fair", "Within observed range")


def build_report(db, slug):
    meta = q(db, "SELECT brand, ref, model, case_material, url FROM references_meta WHERE slug=?",
             (slug,))
    if not meta:
        return None
    brand, ref, model, material, ref_url = meta[0]

    rows = q(db, "SELECT price_usd, condition, box_papers, available, merchant_name, "
                 "image_url, buy_url, detail_url, title FROM listings WHERE slug=?",
             (slug,))
    prices = [r[0] for r in rows if r[0] is not None]
    avail = [r for r in rows if r[4] is not None]
    box_counts = {}
    for r in rows:
        box_counts[r[2] or "unknown"] = box_counts.get(r[2] or "unknown", 0) + 1

    auc_rows = q(db, "SELECT hammer_usd, year_sold, venue FROM auction_lots "
                     "WHERE ref_slug=?", (slug,))
    auc_prices = [r[0] for r in auc_rows if r[0] is not None]
    auc_by_year = {}
    for _, year, _ in auc_rows:
        auc_by_year[year] = auc_by_year.get(year, 0) + 1

    n = len(prices)
    band_lo = band_hi = None
    if n >= 5:
        sp = sorted(prices)
        band_lo, band_hi = sp[int(n * 0.1)], sp[min(n - 1, int(n * 0.9))]

    image = next((r[5] for r in rows if r[5]), None)

    rows_html = []
    for r in rows:
        price, cond, bp, _avail, merchant, img, buy, detail, title = r
        kind, label = classify(price, band_lo, band_hi, n)
        badge_cls = {"deal": "badge-deal", "fair": "badge-fair",
                     "above": "badge-above", "over": "badge-over", "limited": ""}.get(kind, "")
        badge = f'<span class="badge {badge_cls}">{html.escape(label)}</span>' if kind != "limited" else \
            f'<span class="badge">{html.escape(label)}</span>'
        thumb = (f'<img class="thumb" src="{html.escape(img)}" alt="" loading="lazy">'
                 if img else '<div class="thumb" style="background:var(--img-bg)"></div>')
        sub = f"{html.escape(ref)} · {r[7].replace('/out/', '/listing/') if r[7] else ''}".split("/listing/")[0]
        href = html.escape(buy or detail or "#")
        view_link = f'<a class="btn" href="{href}" target="_blank" rel="noopener">View ↗</a>'
        rows_html.append(
            f'<tr><td><div style="display:flex;gap:14px;align-items:center">{thumb}'
            f'<div><div class="listing-title">{html.escape(title or (brand + " " + model))}</div>'
            f'<div class="listing-sub">Ref {html.escape(ref)} · {html.escape(cond or "—")} · {html.escape(bp or "—")}</div></div></div></td>'
            f'<td class="price-cell">{price_fmt(price)}</td>'
            f'<td>{badge}</td>'
            f'<td><div class="listing-sub">{html.escape(merchant or "—")}</div></td>'
            f'<td>{view_link}</td></tr>')

    auc_html = []
    for a in auc_rows:
        auc_html.append(
            f'<tr><td>{html.escape(a[2] or "—")}</td>'
            f'<td>{a[1] if a[1] else "—"}</td>'
            f'<td class="price-cell">{price_fmt(a[0])}</td></tr>')

    return {
        "slug": slug, "brand": brand, "ref": ref, "model": model, "material": material,
        "ref_url": ref_url,
        "n_listings": n,
        "listing_median": median(prices),
        "listing_low": min(prices) if prices else None,
        "listing_high": max(prices) if prices else None,
        "band_lo": band_lo, "band_hi": band_hi,
        "n_available": len(avail),
        "n_auction": len(auc_prices),
        "auc_median": median(auc_prices),
        "auc_years": ", ".join(str(y) for y in sorted(auc_by_year)),
        "box_counts": ", ".join(f"{k}: {v}" for k, v in sorted(box_counts.items())),
        "image": image,
        "listings_html": "".join(rows_html),
        "auctions_html": "".join(auc_html),
        "src_listings": provenance(db, slug, "listings"),
        "src_auctions": provenance(db, slug, "auction_lots"),
        "confidence": "High" if n >= 15 else ("Medium" if n >= 5 else "Low"),
    }


def render(d):
    brand, ref, model = html.escape(d["brand"]), html.escape(d["ref"]), html.escape(d["model"] or "")
    title = f"{brand} {ref} — watchledger"
    img = (f'<img src="{html.escape(d["image"])}" alt="{brand} {model}" loading="lazy">'
           if d["image"] else '')
    rng = price_fmt(d["band_lo"] or d["listing_low"]) + " — " + price_fmt(d["band_hi"] or d["listing_high"])
    typ = price_fmt(d["listing_median"])

    band = d["band_lo"] and d["band_hi"] and d["listing_low"] and d["listing_high"]
    bar = ""
    if band:
        lo, hi = d["listing_low"], d["listing_high"]
        b_lo, b_hi = d["band_lo"], d["band_hi"]
        med = d["listing_median"]
        span = hi - lo or 1
        pos = lambda v: max(0, min(100, (v - lo) / span * 100))
        bar = f"""<div class="range-bar">
 <div class="track">
  <div class="band" style="left:{pos(b_lo):.1f}%;width:{pos(b_hi) - pos(b_lo):.1f}%"></div>
  <div class="marker" style="left:calc({pos(med):.1f}% - 8px)"></div>
 </div>
 <div class="scale"><span>{price_fmt(lo)}</span><span>{price_fmt(b_lo)}</span><span>{price_fmt(b_hi)}</span><span>{price_fmt(hi)}</span></div>
</div>"""

    panel_low = price_fmt(d["band_lo"]) if d["band_lo"] else "—"
    panel_high = price_fmt(d["band_hi"]) if d["band_hi"] else "—"
    panel = f"""<div class="panel"><h3>How to read this market</h3><div class="panel-cols">
 <div class="panel-col"><div class="tag tag-deal">Potential deal</div><p>Listings priced below {panel_low} may be worth a closer look.</p></div>
 <div class="panel-col"><div class="tag tag-fair">Fair range</div><p>Between {panel_low} and {panel_high} is within the observed comparable range.</p></div>
 <div class="panel-col"><div class="tag tag-above">Above market</div><p>Prices above {panel_high} are higher than most comparable listings.</p></div>
 </div></div>"""

    conf = f"""<div class="conf-grid">
 <div class="conf-item"><span class="dot"></span><span><b>{d['n_listings']}</b> active listings</span></div>
 <div class="conf-item"><span class="dot"></span><span>Data confidence: <b>{d['confidence']}</b></span></div>
 <div class="conf-item"><span class="dot"></span><span>Box/papers mix: <b>{html.escape(d['box_counts'] or '—')}</b></span></div>
 </div>"""

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
<button class="nav-icon" onclick="window.location='/'">⌕</button>
<a href="/raw/" class="btn btn-ghost">Raw data</a>
<a href="/#markets" class="btn btn-primary">Track a watch</a>
</div>
</div></header>
<main style="max-width:1200px;margin:0 auto;padding:32px 24px 0">
<p class="breadcrumb"><a href="/">Home</a> / {brand} / {model}</p>
<div class="report-layout">
 <div class="report-img">{img}</div>
 <div>
  <h1 class="model-name">{brand} {model}</h1>
  <div class="model-ref">Reference {ref}</div>
  <p class="model-desc">Case material: {html.escape(d['material'] or '—')}. Market data computed deterministically from {d['n_listings']} live dealer listings.</p>
  <div class="model-meta">
   <div class="stat"><div class="k">Active listings</div><div class="v">{d['n_listings']}</div></div>
   <div class="stat"><div class="k">In stock now</div><div class="v">{d['n_available']}</div></div>
   <div class="stat"><div class="k">Auction results</div><div class="v">{d['n_auction']}</div></div>
   <div class="stat"><div class="k">Confidence</div><div class="v">{d['confidence']}</div></div>
  </div>

  <div class="range-card">
   <div class="range-label">CURRENT OBSERVED MARKET RANGE</div>
   <div class="range-value">{rng}</div>
   <div class="range-sub">Typical comparable asking price: <b>{typ}</b></div>
   {bar}
  </div>
  {panel}
  {conf}
 </div>
</div>

<section class="live-section">
 <div class="live-head"><h2>Live listings</h2>
 <div class="sub">{d['n_listings']} tracked listings · <a href="{html.escape(d['ref_url'])}">source page</a></div></div>
 <p class="src">Listing data: {d['src_listings']}</p>
 <div class="listing-table-wrap"><table class="listing-table">
 <thead><tr><th>Watch</th><th>Price</th><th>Position</th><th>Seller</th><th></th></tr></thead>
 <tbody>{d['listings_html']}</tbody>
 </table></div>
</section>

<section class="live-section">
 <div class="live-head"><h2>Auction results</h2>
 <div class="sub">Hammer prices for this reference</div></div>
 <p class="src">Auction data: {d['src_auctions']}</p>
 <table class="listing-table"><thead><tr><th>Venue</th><th>Year</th><th>Hammer</th></tr></thead>
 <tbody>{d['auctions_html']}</tbody></table>
</section>
</main>
<footer><div class="footer-inner">
<div class="col"><div class="logo">watch<span>ledger</span></div>
<p>Every number above traces to the raw payload at the listed source URL. No AI, no guesswork.</p></div>
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/reference/{html.escape(d['slug'])}.json">JSON for this watch</a></div>
<div class="col"><b>Product</b><a href="/#how">How it works</a><a href="/#trust">Why it's trustworthy</a></div>
</div></footer></body></html>"""


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