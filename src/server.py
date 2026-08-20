"""watchledger web server — stdlib only, no dependencies.

Serves the ledger live:
  /                          homepage: hero search, markets, how it works
  /reference/<slug>          per-reference market report (deterministic renderer)
  /api/references.json       index stats as JSON
  /api/reference/<slug>.json one reference's report dict as JSON
  /raw/<path>                raw payload files (the source of truth, browsable)
  /static/<path>             shared CSS + fonts

Every page is generated at request time from data/ledger.sqlite; nothing is
cached, nothing is written. The source-of-truth guarantee is unchanged: every
number still traces to the raw payloads under /raw/.
"""

import html
import http.server
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from config import DB_PATH, RAW_DIR, STATIC_DIR
from report import build_report, price_fmt, q, render

PORT = int(os.environ.get("PORT", "8040"))


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
    """Per-reference summary rows for the homepage (tracked refs only)."""
    rows = q(db, """SELECT DISTINCT m.slug, m.brand, m.ref, m.model, m.case_material
                    FROM references_meta m
                    LEFT JOIN listings l ON l.slug = m.slug
                    LEFT JOIN auction_lots a ON a.ref_slug = m.slug
                    WHERE l.slug IS NOT NULL OR a.ref_slug IS NOT NULL
                    ORDER BY m.brand, m.ref""")
    out = []
    for r in rows:
        slug = r["slug"]
        lst = q(db, "SELECT price_usd, image_url, fetched_at FROM listings WHERE slug=?",
                (slug,))
        prices = [x[0] for x in lst if x[0] is not None]
        images = [x[1] for x in lst if x[1]]
        stamps = [x[2] for x in lst if x[2]]
        auc = q(db, "SELECT hammer_usd FROM auction_lots WHERE ref_slug=?", (slug,))
        auc_prices = [x[0] for x in auc if x[0] is not None]
        n = len(prices)
        band = None
        if n >= 5:
            sp = sorted(prices)
            band = (sp[int(n * 0.1)], sp[min(n - 1, int(n * 0.9))])
        out.append({
            "slug": slug, "brand": r["brand"], "ref": r["ref"],
            "model": r["model"] or "", "material": r["case_material"] or "",
            "n_listings": n,
            "median_ask": statistics.median(prices) if prices else None,
            "low": min(prices) if prices else None,
            "high": max(prices) if prices else None,
            "band_low": band[0] if band else None,
            "band_high": band[1] if band else None,
            "n_auction": len(auc_prices),
            "median_hammer": statistics.median(auc_prices) if auc_prices else None,
            "image": images[0] if images else None,
            "updated": max(stamps) if stamps else None,
            "confidence": "High" if n >= 15 else ("Medium" if n >= 5 else "Low"),
        })
    return out


PAGE_HEAD = """<!doctype html>
<html><head><meta charset="utf-8"><title>watchledger — know what a watch is worth, today</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head><body>
<header class="nav"><div class="nav-inner">
<a href="/" class="logo">watch<span>ledger</span></a>
<nav class="nav-links"><a href="/#markets">Explore Watches</a><a href="/#how">Market Trends</a><a href="/#trust">How It Works</a></nav>
<div class="nav-actions">
<button class="nav-icon" onclick="document.getElementById('q').focus()" aria-label="Search">⌕</button>
<a href="/raw/" class="btn btn-ghost">Raw data</a>
<a href="/#markets" class="btn btn-primary">Track a watch</a>
</div>
</div></header>"""

PAGE_FOOT = """<footer><div class="footer-inner">
<div class="col"><div class="logo">watch<span>ledger</span></div>
<p>Know what a watch is worth — today. Every number on this site is computed from the raw payloads under <a href="/raw/">/raw</a> and links to its source. No AI, no guesswork.</p></div>
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/references.json">JSON API</a><a href="/#markets">Tracked markets</a></div>
<div class="col"><b>Product</b><a href="/#how">How it works</a><a href="/#trust">Why it's trustworthy</a></div>
</div></footer></body></html>"""


def nav_echo():
    return PAGE_HEAD


def render_home(stats):
    hero = max(stats, key=lambda s: s["n_listings"]) if stats else None

    market_cards = []
    for s in sorted(stats, key=lambda s: -(s["n_listings"])):
        img = (f'<img src="{html.escape(s["image"])}" alt="{html.escape(s["brand"] + " " + s["model"])}" loading="lazy">'
               if s["image"] else '<div class="market-img"></div>')
        rng = price_fmt(s["band_low"] or s["low"]) + " – " + price_fmt(s["band_high"] or s["high"])
        market_cards.append(f"""
<a class="market-card" href="/reference/{html.escape(s['slug'])}">
 <div class="market-img">{img}</div>
 <div class="market-body">
  <div class="market-name">{html.escape(s['brand'])} {html.escape(s['model'])}</div>
  <div class="market-ref">Ref {html.escape(s['ref'])}</div>
  <div class="market-range">{rng}</div>
  <div class="market-meta"><span class="dot"></span>{s['n_listings']} exact listings · {fmt_ago(s['updated'])}</div>
  <div class="market-sub">{s['confidence']} confidence · snapshot data</div>
 </div><span class="market-arrow">→</span></a>""")
    market_cards = "".join(market_cards)

    recent = sorted(stats, key=lambda s: s["updated"] or 0, reverse=True)[:5]
    recent_rows = ""
    for s in recent:
        img = (f'<img src="{html.escape(s["image"])}" alt="" loading="lazy">'
               if s["image"] else '<img alt="">')
        rng = price_fmt(s["band_low"] or s["low"]) + " – " + price_fmt(s["band_high"] or s["high"])
        recent_rows += f"""
<a class="recent-row" href="/reference/{html.escape(s['slug'])}">
 {img}
 <div><div class="recent-name">{html.escape(s['brand'])} {html.escape(s['model'])}</div>
 <div class="recent-ref">Ref {html.escape(s['ref'])}</div></div>
 <div class="recent-range"><div class="p">{rng}</div><div class="m">{s['n_listings']} listings · updated {fmt_ago(s['updated'])}</div></div>
 <span class="recent-arrow">→</span></a>"""

    hero_block = ""
    if hero:
        hrange = price_fmt(hero["band_low"] or hero["low"]) + " – " + price_fmt(hero["band_high"] or hero["high"])
        hero_block = f"""
<div class="hero-media">
 <img class="hero-img" src="{html.escape(hero['image'] or '')}" alt="{html.escape(hero['brand'] + ' ' + hero['model'])}">
 <div class="hero-card">
  <div class="hc-brand">{html.escape(hero['brand'])} {html.escape(hero['model'])}</div>
  <div class="hc-ref">Ref {html.escape(hero['ref'])}</div>
  <div class="hc-range">{hrange}</div>
  <div class="hc-label">Observed asking-price range</div>
  <div class="hc-meta"><span class="dot"></span>{hero['n_listings']} exact active listings · {fmt_ago(hero['updated'])}</div>
 </div>
</div>"""

    refs_json = json.dumps([{
        "slug": s["slug"], "brand": s["brand"], "model": s["model"], "ref": s["ref"],
        "range": price_fmt(s["band_low"] or s["low"]) + " – " + price_fmt(s["band_high"] or s["high"]),
        "image": s["image"],
    } for s in stats])

    return PAGE_HEAD + f"""
<section class="hero">
 <div>
  <p class="eyebrow">LIVE WATCH MARKET DATA</p>
  <h1>Know what a watch is worth — <em>today.</em></h1>
  <p class="hero-copy">Compare live dealer listings, see the current market range, and spot prices that stand out.</p>
  <div class="search-wrap">
   <div class="search"><span class="icon">⌕</span>
    <input id="q" type="text" placeholder="Search brand, model, or reference number" autocomplete="off">
   </div>
   <div class="suggestions" id="suggestions"></div>
   <div class="search-chips"><span class="chip-label">Popular searches</span>
    <button class="chip" data-q="Rolex 126610LN">Rolex 126610LN</button>
    <button class="chip" data-q="Patek Philippe 5711">Patek 5711</button>
    <button class="chip" data-q="Tudor Black Bay 58">Tudor BB58</button></div>
  </div>
 </div>
 {hero_block}
</section>

<section class="trust-strip">
 <span>Live dealer listings</span><span class="ts-dot">·</span>
 <span>Reference-level comparison</span><span class="ts-dot">·</span>
 <span>Transparent market ranges</span>
</section>

<section class="sec-head" id="how" style="padding-bottom:0">
 <div><p class="eyebrow">HOW IT WORKS</p>
 <h2>Three steps to a confident answer</h2></div>
</section>
<section style="padding-top:24px"><div class="steps">
 <div class="step"><div class="num">01</div><h3>We collect visible market listings</h3>
  <p>Dealer asking prices are pulled from free public sources and stored exactly as returned — with the source URL and fetch time.</p>
  <div class="step-visual sv-collect"><span class="mini-card"></span><span class="mini-card"></span><span class="mini-card"></span><span class="sv-arrow">→</span><span class="mini-tray"></span></div></div>
 <div class="step"><div class="num">02</div><h3>We compare like-for-like watches</h3>
  <p>Listings for the same reference are grouped and compared by price, condition, and completeness.</p>
  <div class="step-visual sv-compare"><span class="mini-ref">126610LN</span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span><span class="mini-dot"></span></div></div>
 <div class="step"><div class="num">03</div><h3>You see where each price sits</h3>
  <p>The result is a price range, a typical price, and each listing's position — every number traceable to its source.</p>
  <div class="step-visual sv-range"><span class="sv-track"><span class="sv-band"></span><span class="sv-marker"></span></span><span class="sv-dots"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span></div></div>
</div></section>

<section id="markets">
 <div class="sec-head">
  <div><p class="eyebrow">LIVE MARKET DATA</p>
  <h2>Markets people are watching</h2></div>
  <a class="sec-link" href="/api/references.json">Explore all markets →</a>
 </div>
 <div class="market-grid">{market_cards}</div>
</section>

<section class="sec-head" id="recent" style="padding-bottom:0">
 <div><p class="eyebrow">FRESHEST DATA</p>
 <h2>Recently updated pricing pages</h2></div>
</section>
<section style="padding-top:24px"><div class="recent-list">{recent_rows}</div></section>

<section id="trust">
 <div class="sec-head"><div><p class="eyebrow">THE DATA</p>
 <h2>Why collectors trust this</h2></div></div>
 <div class="trust-grid">
  <div class="trust-item"><div class="ic">⚲</div><h3>Real listings, not estimates</h3>
   <p>Every price is a real, live dealer listing — with its photo, seller, and a direct link to verify it.</p></div>
  <div class="trust-item"><div class="ic">▦</div><h3>Deterministic, not generated</h3>
   <p>No AI, no guesses. Medians, ranges, and positions are computed by fixed rules from the raw payloads.</p></div>
  <div class="trust-item"><div class="ic">✓</div><h3>Traceable to the source</h3>
   <p>Each number carries its source URL and fetch time, and the raw data is browsable at <a href="/raw/">/raw</a>.</p></div>
 </div>
</section>
<script>
const REFS = {refs_json};
const input = document.getElementById('q');
const box = document.getElementById('suggestions');
function money(v) {{ return v ? '$' + Number(v).toLocaleString('en-US', {{maximumFractionDigits: 0}}) : '—'; }}
function open() {{
  const t = input.value.trim().toLowerCase();
  const hits = REFS.filter(r =>
    !t || (r.brand + ' ' + r.model + ' ' + r.ref).toLowerCase().includes(t)).slice(0, 6);
  box.innerHTML = hits.length
    ? hits.map(r => `<a class="sug-row" href="/reference/${{r.slug}}">
        <img src="${{r.image || ''}}" alt="" onerror="this.style.visibility='hidden'">
        <span><span class="t">${{r.brand}} ${{r.model}}</span><br><span class="s">Ref ${{r.ref}}</span></span>
        <span class="r">${{r.range}}</span></a>`).join('')
    : '<div class="sug-empty">No tracked reference matches. Try "Rolex 126610LN".</div>';
  box.classList.add('open');
}}
input.addEventListener('input', open);
input.addEventListener('focus', open);
document.addEventListener('click', e => {{ if (!box.contains(e.target)) box.classList.remove('open'); }});
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {{
  input.value = c.dataset.q;
  open();
  const first = box.querySelector('.sug-row');
  if (first) window.location = first.getAttribute('href');
}}));
input.addEventListener('keydown', e => {{
  if (e.key === 'Enter') {{
    const first = box.querySelector('.sug-row');
    if (first) window.location = first.getAttribute('href');
  }}
}});
</script>""" + PAGE_FOOT


def render_not_found(what):
    return PAGE_HEAD + f"<main style='max-width:800px;margin:60px auto;padding:0 24px'><h1>Not found</h1>" \
        f"<p class='src'>{html.escape(what)} is not in this ledger. See the <a href='/'>homepage</a> for tracked references.</p></main>" + PAGE_FOOT


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "watchledger/0.2"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
        except sqlite3.Error as e:
            self.send(500, f"<pre>ledger error: {html.escape(str(e))}</pre>")
        except BrokenPipeError:
            pass

    def route(self, path):
        if path == "/" or path == "/index.html":
            db = open_db()
            self.send(200, render_home(index_stats(db)))
            db.close()
        elif path == "/raw" or path == "/raw/":
            self.send(200, render_raw_index())
        elif path.startswith("/raw/"):
            self.serve_raw(path[5:])
        elif path == "/api/references.json":
            db = open_db()
            self.send_json(200, index_stats(db))
            db.close()
        elif path.startswith("/api/reference/"):
            slug = path[len("/api/reference/"):]
            db = open_db()
            d = build_report(db, slug)
            db.close()
            if not d:
                self.send(404, json.dumps({"error": "unknown reference", "slug": slug}),
                          "application/json; charset=utf-8")
            else:
                self.send_json(200, d)
        elif path.startswith("/reference/"):
            slug = path[len("/reference/"):]
            db = open_db()
            d = build_report(db, slug)
            db.close()
            if not d:
                self.send(404, render_not_found(slug))
            else:
                self.send(200, render(d))
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
        ctype = "text/css; charset=utf-8" if target.endswith(".css") else "application/octet-stream"
        with open(target, "rb") as fh:
            self.send(200, fh.read(), ctype)


def render_raw_index():
    entries = []
    for root, _, files in os.walk(RAW_DIR):
        rel = os.path.relpath(root, RAW_DIR)
        for f in sorted(files):
            if f.endswith(".json"):
                p = os.path.join(rel, f) if rel != "." else f
                entries.append(p)
    lis = "".join(
        f"<li><a href='/raw/{html.escape(urllib.parse.quote(p))}'>{html.escape(p)}</a> · "
        f"{os.path.getsize(os.path.join(RAW_DIR, p)):,} bytes</li>"
        for p in sorted(entries))
    return PAGE_HEAD + f"<main style='max-width:800px;margin:40px auto;padding:0 24px'>" \
        f"<h1>Raw data — the source of truth</h1>" \
        f"<p class='src'>Every payload exactly as returned by the MEW API, with source_url and fetched_at. The ledger and every report derive from these files alone.</p>" \
        f"<ul>{lis}</ul></main>" + PAGE_FOOT


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