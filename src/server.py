"""watchledger web server — stdlib only, no dependencies.

Serves the ledger live:
  /                          homepage: hero search, markets, how it works
  /reference/<slug>          per-reference market report (deterministic renderer)
  /api/references.json       index stats as JSON
  /api/reference/<slug>.json one reference's report dict as JSON
  /raw/<path>                raw payload files (the source of truth, browsable)
  /static/<path>             shared CSS, JS, fonts

Security rules (from the security guide):
  - External URLs validated with safe_external_url before rendering.
  - Text values escaped with safe_text.
  - Homepage search data shipped as a type=application/json block, rendered
    by /static/home.js with DOM nodes — never innerHTML.
  - Security headers (CSP, nosniff, frame denial) on every response.
  - Slugs validated before routing to the database.
  - SQLite errors logged server-side only; visitors get a generic page.
"""

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
    carries the eligibility state (valid/limited/zero) from Phase 4.
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
        out.append({
            "slug": slug, "brand": r["brand"], "ref": r["ref"],
            "model": r["model"] or "", "material": r["case_material"] or "",
            "n_listings": n_exact,
            "median_ask": typical,
            "low": min(prices) if prices else None,
            "high": max(prices) if prices else None,
            "band_low": band_low,
            "band_high": band_high,
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head><body>
<header class="nav"><div class="nav-inner">
<a href="/" class="logo">watch<span>ledger</span></a>
<nav class="nav-links"><a href="/#markets">Explore Watches</a><a href="/#how">Market Trends</a><a href="/#trust">How It Works</a></nav>
<div class="nav-actions">
<button class="nav-icon" type="button" data-focus-search aria-label="Search">⌕</button>
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


def render_home(stats):
    hero = next((s for s in sorted(stats, key=lambda s: -(s["n_listings"]))
                 if s["valid"]), None) or (max(stats, key=lambda s: s["n_listings"])
                 if stats else None)

    def rng_for(s):
        if s["valid"]:
            return price_fmt(s["band_low"]) + " – " + price_fmt(s["band_high"])
        if s["n_listings"]:
            return price_fmt(s["low"]) + " – " + price_fmt(s["high"])
        return "No listings yet"

    def state_badge(s):
        if s["state"] == "valid":
            return f'<span class="state-badge state-ok">Published range</span>'
        if s["state"] == "limited":
            return f'<span class="state-badge state-warn">Limited data</span>'
        return f'<span class="state-badge state-empty">No listings</span>'

    market_cards = []
    for s in sorted(stats, key=lambda s: -(s["n_listings"])):
        market_cards.append(f"""
<a class="market-card" href="/reference/{safe_text(s['slug'])}">
 <div class="market-img">{img_html(s["image"], s["brand"] + " " + s["model"])}</div>
 <div class="market-body">
  <div class="market-name">{safe_text(s['brand'])} {safe_text(s['model'])}</div>
  <div class="market-ref">Ref {safe_text(s['ref'])}</div>
  <div class="market-range">{rng_for(s)}</div>
  {state_badge(s)}
  <div class="market-meta"><span class="dot"></span>{s['n_listings']} exact listings · {fmt_ago(s['updated'])}</div>
  <div class="market-sub">{safe_text(s['confidence'])} confidence · methodology v{market.METHODOLOGY_VERSION}</div>
 </div><span class="market-arrow">→</span></a>""")
    market_cards = "".join(market_cards)

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
        hrange = rng_for(hero)
        hero_block = f"""
<div class="hero-media">
 {img_html(hero.get("image"), hero["brand"] + " " + hero["model"], "hero-img")}
 <div class="hero-card">
  <div class="hc-brand">{safe_text(hero['brand'])} {safe_text(hero['model'])}</div>
  <div class="hc-ref">Ref {safe_text(hero['ref'])}</div>
  <div class="hc-range">{hrange}</div>
  <div class="hc-label">Observed asking-price range</div>
  <div class="hc-meta"><span class="dot"></span>{hero['n_listings']} exact active listings · {fmt_ago(hero['updated'])}</div>
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
  <p class="hero-copy">Compare live dealer listings, see the current market range, and spot prices that stand out.</p>
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
 <span>Transparent market ranges</span>
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
   <p>Every price is a real, live dealer listing — with its photo, seller, and a direct link to verify it.</p></div>
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
<p class="src">Every payload exactly as returned by the MEW API, with source_url and fetched_at. The ledger and every report derive from these files alone.</p>
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


def render_track_confirmation(slug, email):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>You are tracking this watch</h1>
<p>We'll email {safe_text(email)} when the market for {safe_text(slug)} changes meaningfully.
<a href="/reference/{safe_text(safe_slug(slug))}">Back to the watch page →</a></p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


def render_unsubscribed(email):
    return PAGE_HEAD + f"""<main class="narrow-page narrow-page-spaced"><h1>You are unsubscribed</h1>
<p>{safe_text(email)} will no longer receive watchledger alerts.
You can resubscribe from any watch page.</p></main>
<script src="/static/home.js" defer></script>""" + PAGE_FOOT


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "watchledger/0.2"

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
            import hashlib, secrets
            token = hashlib.sha256(
                (email + secrets.token_hex(16)).encode()).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO watch_users (id, email, unsubscribe_token,"
                " created_at) VALUES (?,?,?,?)",
                (email, email, token, time.time()))
            db.execute(
                "INSERT OR IGNORE INTO watchlist_item (id, user_id,"
                " reference_slug, created_at, active) VALUES (?,?,?,?,1)",
                (f"{email}:{slug}", email, slug, time.time()))
            db.execute(
                "INSERT OR IGNORE INTO alert_preference (id, watchlist_item_id,"
                " alert_type, enabled) VALUES (?,?,?,1)",
                (f"{email}:{slug}:price", f"{email}:{slug}", "price"))
            db.commit()
            db.close()
            self.send(200, json.dumps({"ok": True, "slug": slug}),
                      "application/json; charset=utf-8")
            return
        self.send(400, json.dumps({"error": "unknown action"}),
                  "application/json; charset=utf-8")

    def route(self, path):
        if path == "/" or path == "/index.html":
            db = open_db()
            self.send(200, render_home(index_stats(db)))
            db.close()
        elif path == "/raw" or path == "/raw/":
            self.send(200, render_raw_index())
        elif path == "/sources" or path == "/sources/":
            db = open_db()
            self.send(200, render_sources(db))
            db.close()
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