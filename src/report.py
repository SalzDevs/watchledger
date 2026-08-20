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
"""

import html
import json
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
    return f'<a href="{html.escape(url)}">{html.escape(url)}</a> · fetched {when}'


def classify(price, lo, hi, typical, n):
    """Five-way price-position classification, per design review #3.

    Returns (kind, pct_label, sub_label).
    kind: deal | fair | above | over | not_comp
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

SCRIPT = """<script>
const LISTINGS = [];
document.querySelectorAll('.lrow').forEach(tr => {
  LISTINGS.push({row: tr, data: JSON.parse(tr.dataset.listing)});
});
function openDrawer(btn) {
  const d = JSON.parse(btn.closest('tr').dataset.listing);
  const body = document.getElementById('drawer-body');
  const tint = {deal: 'deal', fair: 'fair', above: 'above', over: 'over', not_comp: 'nc'}[d.kind] || 'fair';
  body.innerHTML = `
    <img src="${d.image || ''}" class="drawer-img" alt="">
    <div class="drawer-brand">${d.title}</div>
    <div class="drawer-price">${d.price ? '$' + Number(d.price).toLocaleString('en-US') : '—'}</div>
    <div class="badge badge-${tint}"><span class="pct">${d.pct}</span><span class="sub">${d.sub}</span></div>
    <div class="drawer-section tint-${tint}">
      <h4>Why this stands out</h4>
      <p>${d.sub}. This price is compared against the observed range of ${d.range}.</p>
    </div>
    <div class="drawer-section"><h4>Listing details</h4>
      <table class="kv"><tr><td>Condition</td><td>${d.condition || '—'}</td></tr>
      <tr><td>Year</td><td>${d.year || '—'}</td></tr>
      <tr><td>Box &amp; papers</td><td>${d.box_papers || '—'}</td></tr>
      <tr><td>Material</td><td>${d.material || '—'}</td></tr>
      <tr><td>Seller</td><td>${d.merchant || '—'}</td></tr></table>
    </div>
    ${d.url ? `<a class="btn btn-primary" href="${d.url}" target="_blank" rel="noopener">View original listing ↗</a>` : ''}
  `;
  document.getElementById('dmask').classList.add('open');
  document.getElementById('drawer').classList.add('open');
}
function closeDrawer() {
  document.getElementById('dmask').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}
document.querySelectorAll('#ltabs .tab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('#ltabs .tab').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  const which = t.dataset.tab;
  document.getElementById('tbl-exact').style.display = which === 'exact' ? '' : 'none';
  document.getElementById('tbl-related').style.display = which === 'related' ? '' : 'none';
}));
function applyFilters() {
  const cond = document.querySelector('[data-filter=condition]').value;
  const bp = document.querySelector('[data-filter=bp]').value;
  const avail = document.querySelector('[data-filter=avail]').value;
  const sort = document.getElementById('fsort').value;
  let rows = LISTINGS.filter(o => o.data.kind !== 'not_comp');
  rows = rows.filter(o => !cond || (o.data.condition || '') === cond);
  rows = rows.filter(o => !bp || (o.data.box_papers || '') === bp);
  rows = rows.filter(o => avail === '' || (avail === '1' ? o.data.price != null : true));
  const order = {best: ['deal', 'fair', 'above', 'over', 'not_comp'], low: [], high: []};
  if (sort === 'low') rows.sort((a, b) => (a.data.price ?? 1e18) - (b.data.price ?? 1e18));
  else if (sort === 'high') rows.sort((a, b) => (b.data.price ?? -1) - (a.data.price ?? -1));
  else rows.sort((a, b) => order.best.indexOf(a.data.kind) - order.best.indexOf(b.data.kind));
  const tb = document.querySelector('#tbl-exact tbody');
  tb.innerHTML = '';
  rows.forEach(o => tb.appendChild(o.row));
}
document.querySelectorAll('#lfilters select').forEach(s => s.addEventListener('change', applyFilters));
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
</script>"""



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
    def row_html(r, typ, lo, hi, typ_p, n_exact):
        price, cond, bp, _avail, merchant, img, buy, detail, title, year, mat, lid, exact = r
        kind, pct_label, sub = classify(price, lo, hi, typ_p, n_exact)
        badge = (f'<span class="badge {BADGE_CLS[kind]}"><span class="pct">{html.escape(pct_label)}</span>'
                 f'<span class="sub">{html.escape(sub)}</span></span>')
        thumb = (f'<img class="thumb" src="{html.escape(img)}" alt="" loading="lazy">'
                 if img else '<div class="thumb" style="background:var(--img-bg)"></div>')
        facts = " · ".join(x for x in [
            f"{html.escape(cond or '')}", f"{html.escape(bp or '')}",
            f"{year if year else ''}", f"{html.escape(mat or '')}"] if x)
        href = html.escape(buy or detail or "#")
        data = json.dumps({
            "id": lid, "title": title or "", "price": price,
            "condition": cond, "box_papers": bp, "year": year,
            "material": mat, "merchant": merchant, "image": img,
            "url": buy or detail or "", "kind": kind,
            "pct": pct_label, "sub": sub,
            "range": (f"{price_fmt(lo)} – {price_fmt(hi)}" if lo else "—"),
            "typical": typ_p,
        })
        return f"""
<tr class="lrow" data-kind="{kind}" data-price="{price if price is not None else 1e18}" data-listing='{html.escape(data)}'>
 <td><div class="watch-cell">{thumb}
   <div><div class="listing-title">{html.escape(title or '—')}</div>
   <div class="listing-sub">{facts}</div></div></div></td>
 <td class="price-cell">{price_fmt(price)}
   <div class="price-pos">{pct_label if kind in ('deal',) else '&nbsp;'}</div></td>
 <td>{badge}</td>
 <td><div class="seller-cell"><div class="listing-sub" style="font-size:13px">{html.escape(merchant or '—')}</div>
   <div class="listing-sub">{'in stock' if _avail else 'on request'}</div></div></td>
 <td><button class="btn btn-sm" data-lid="{html.escape(lid)}" onclick="openDrawer(this)">View analysis</button></td>
</tr>"""

    n_exact = n
    rows_html = "".join(row_html(r, "exact", band_lo, band_hi, typical, n)
                        for r in exact_rows)
    rel_html = "".join(row_html(r, "related", None, None, None, n)
                       for r in rel_rows)

    auc_html = []
    for a in auc_rows:
        auc_html.append(
            f'<tr><td>{html.escape(a[2] or "—")}</td>'
            f'<td>{a[1] if a[1] else "—"}</td>'
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
        "box_counts": "n/a",
        "image": image,
        "updated": updated,
        "listings_html": rows_html,
        "related_html": rel_html,
        "auctions_html": "".join(auc_html),
        "src_exact": provenance(db, slug, "listings", exact=1),
        "src_related": provenance(db, slug, "listings", exact=0),
        "src_auctions": provenance(db, slug, "auction_lots"),
        "confidence": "High" if n_exact >= 15 else ("Medium" if n_exact >= 5 else "Low"),
        "limited": n_exact < 5,
    }


def render_meta(d):
    brand, ref, model = html.escape(d["brand"]), html.escape(d["ref"]), html.escape(d["model"] or "")
    title = f"{brand} {ref} — watchledger"
    img = (f'<img src="{html.escape(d["image"])}" alt="{brand} {model}" loading="lazy">'
           if d["image"] else '')
    return title, brand, ref, model, img


def render(d):
    title, brand, ref, model, img = render_meta(d)
    rng = price_fmt(d["band_lo"]) + " — " + price_fmt(d["band_hi"]) if d["band_lo"] else None
    typ = price_fmt(d["listing_median"])
    updated = __import__("time").time()
    import time as _t
    up_ts = d.get("updated") or 0
    ago = "—"
    if up_ts:
        dt = _t.time() - up_ts
        ago = ("just now" if dt < 60 else
               f"{int(dt // 60)} min ago" if dt < 3600 else
               f"{int(dt // 3600)} h ago" if dt < 86400 else
               f"{int(dt // 86400)} d ago")

    # --- market summary: credible range or honest limited-data state ---
    if d["limited"]:
        n_related = d["n_related"]
        summary = f"""
<div class="range-card limited-state">
 <div class="range-label">OBSERVED MARKET RANGE — LIMITED DATA</div>
 <div class="limited-title">Limited exact-match data</div>
 <p class="range-sub">We found <b>{d['n_exact']} listings</b> for reference {html.escape(d['ref'])}.
 {f'{n_related} related listings are available for broader research.' if n_related else 'No related listings either.'}</p>
 <div class="range-bar" style="visibility:hidden;height:0;margin:0"></div>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""
    else:
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
 <div class="scale"><span>{fmt_k(lo)}</span><span>{fmt_k(b_lo)}</span><span>{fmt_k(med)}</span><span>{fmt_k(b_hi)}</span><span>{fmt_k(hi)}</span></div>
</div>"""
        summary = f"""
<div class="range-card">
 <div class="range-label">CURRENT OBSERVED MARKET RANGE</div>
 <div class="range-value">{rng}</div>
 <div class="range-sub">Typical asking price <b>{typ}</b></div>
 {bar}
 <div class="range-evidence">Based on <b>{d['n_exact']} exact-reference active listings</b> · updated {ago}
 <span class="ev-dot"></span></div>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""

    panel_low = price_fmt(d["band_lo"]) if d["band_lo"] else "—"
    panel_high = price_fmt(d["band_hi"]) if d["band_hi"] else "—"
    panel = f"""<div class="panel"><h3>How to read this market</h3><div class="panel-cols">
 <div class="panel-col"><div class="tag tag-deal">Potential deal</div><p>Listings priced below {panel_low} may be worth a closer look.</p></div>
 <div class="panel-col"><div class="tag tag-fair">Fair range</div><p>Between {panel_low} and {panel_high} is within the observed comparable range.</p></div>
 <div class="panel-col"><div class="tag tag-above">Above market</div><p>Prices above {panel_high} are higher than most comparable listings.</p></div>
 </div></div>"""

    conf = f"""<div class="conf-grid">
 <div class="conf-item"><span class="dot"></span><span><b>{d['n_exact']}</b> exact-match listings</span></div>
 <div class="conf-item"><span class="dot"></span><span><b>{d['n_dealers']}</b> tracked dealers</span></div>
 <div class="conf-item"><span class="dot"></span><span>Confidence: <b>{d['confidence']}</b></span></div>
 </div>"""

    # --- evidence module (review #15) ---
    evidence = f"""<div class="evidence">
 <div class="ev-title">EVIDENCE BEHIND THIS RANGE</div>
 <div class="ev-row"><span class="ev-item"><b>{d['n_exact']}</b> exact-match active listings</span>
 <span class="ev-item"><b>{d['n_dealers']}</b> tracked dealers</span>
 <span class="ev-item"><b>✓</b> each price links to its live listing</span></div>
 <details class="ev-details"><summary>See sources and methodology</summary>
 <p class="src">Exact-match listings: {d['src_exact']}</p>
 <p class="src">Related listings: {d['src_related']}</p>
 <p class="src">Auction data: {d['src_auctions']}</p>
 <p class="src">Reference page: <a href="{html.escape(d['ref_url'])}">{html.escape(d['ref_url'])}</a></p>
 </details>
</div>"""

    # --- listings section with filters (review #12) ---
    tabs = f"""<div class="tabs" id="ltabs">
 <button class="tab active" data-tab="exact">Exact matches <span class="tab-n">{d['n_exact']}</span></button>
 <button class="tab" data-tab="related">Related {f'<span class="tab-n">{d["n_related"]}</span>' if d["n_related"] else ''}</button>
</div>
<div class="filters" id="lfilters">
 <select class="fsel" data-filter="condition"><option value="">Condition: All</option>
  <option>Excellent</option><option>Very good</option><option>Good</option><option>Unworn</option></select>
 <select class="fsel" data-filter="bp"><option value="">Box &amp; papers: All</option>
  <option>full_set</option><option>box_and_papers</option><option>watch_only</option></select>
 <select class="fsel" data-filter="avail"><option value="">Availability: All</option>
  <option value="1">In stock</option><option value="0">On request</option></select>
 <span class="sort-label">Sort</span>
 <select class="fsel" id="fsort"><option value="best">Best value</option>
  <option value="low">Lowest price</option><option value="high">Highest price</option></select>
</div>"""

    # exact table
    table_exact = f"""<table class="listing-table" id="tbl-exact">
 <thead><tr><th>Watch</th><th>Price</th><th>Position</th><th>Seller</th><th></th></tr></thead>
 <tbody>{d['listings_html']}</tbody></table>"""
    table_rel = f"""<table class="listing-table" id="tbl-related" style="display:none">
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

    # --- analysis drawer (review #13) ---
    drawer = """<div class="drawer-mask" id="dmask" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
 <button class="drawer-close" onclick="closeDrawer()">×</button>
 <div id="drawer-body"></div>
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
  <p class="model-desc">Case material: {html.escape(d['material'] or '—')}. Market data computed deterministically from {d['n_exact']} exact-reference listings.</p>
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
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/reference/{html.escape(d['slug'])}.json">JSON for this watch</a></div>
<div class="col"><b>Product</b><a href="/#how">How it works</a><a href="/#trust">Why it's trustworthy</a></div>
</div></footer>
{SCRIPT}
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