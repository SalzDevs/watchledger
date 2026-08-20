"""Generate deterministic per-reference market reports from the ledger.

No AI, no manual text: every number is the result of a fixed SQL query
against the ledger, and every number carries a provenance footnote
(source URL + fetch time of the raw payload it came from).

State model (design brief Phases 4, 7):
  valid   — eligibility gates pass, range + confidence dimensions shown
  limited — gates fail, honest explanation + neutral labels only
  zero    — no exact-match data at all, related research shown instead

Matching model (Phase 2):
  exact_configuration    exact reference, active configuration
  exact_reference_variant exact reference, different configuration
  related_reference      same family, different reference
  rejected               parts/accessories/tool listings, never in tables
  unverified             no canonical reference

Deduplication (Phase 3): only the representative listing of each cluster
appears in tables; raw row counts are shown as dedup evidence. Likely
duplicates (same dealer + config + near price + similar title) share a
cluster with a lower confidence (design brief #3).

Security rules (from the security guide):
- Every server-rendered external URL passes through safe_external_url.
- Every text value passes through safe_text (HTML-escaped).
- Listing details are shipped once as a type=application/json data block,
  read by browser JS and rendered with textContent — never innerHTML.
- No inline event handlers, no inline scripts, no inline styles.
"""

import datetime
import json
import os
import re
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from config import DB_PATH, REPORTS_DIR
from security import safe_external_url, safe_json_script, safe_text
import market

REP_QUERY = """
SELECT l.id, l.price_usd, l.currency, l.condition, l.box_papers, l.available,
       l.merchant_name, l.image_url, l.buy_url, l.detail_url, l.title,
       l.year, l.case_material, l.case_size_mm, l.movement, l.fetched_at,
       l.match_level, l.match_reason, l.source_name, l.source_listing_id,
       l.listing_cluster_id
FROM listings l
JOIN listing_cluster c ON c.representative_listing_id = l.id
WHERE l.slug=? AND l.match_level=?
ORDER BY l.price_usd
"""

# Relevance groups for related listings (design brief #4).
REL_CLOSEST = "Closest alternatives"
REL_VARIANT = "Other variants"
REL_HISTORICAL = "Historical alternatives"

# Alert types offered on the tracking form (design brief #9).
ALERT_TYPES = [
    ("new_listing", "A new exact-match listing appears"),
    ("below_typical", "A listing is 5% below the typical observed price"),
    ("range_change", "The published range changes by 3% or more"),
    ("coverage_ready", "Market coverage becomes sufficient for a range"),
]


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
    when = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
    safe = safe_external_url(url)
    if safe:
        return f'<a href="{safe_text(safe)}">{safe_text(url)}</a> · fetched {when}'
    return f"{safe_text(url)} · fetched {when}"


def canonical_title(row, brand, model, ref):
    """Build the structured WatchLedger identity for a listing row.

    The raw source title is never the primary display (design brief #6).
    Falls back to the raw title only when no structured facts exist.
    """
    _lid, price, cur, cond, bp, _avail, merchant, img, buy, detail, title, \
        year, mat, size, mov, fetched, level, reason, src_name, \
        src_list_id, cid = row
    facts = []
    if year:
        facts.append(str(year))
    if cond:
        facts.append(cond)
    if bp:
        facts.append(bp.replace("_", " "))
    head = f"{brand} {model}".strip() if (brand or model) else (title or "—")
    sub = " · ".join(x for x in [f"Ref. {ref}"] + facts if x)
    return head, sub


def classify(price, lo, hi, typical, valid):
    """Five-way price-position classification against the published range.

    Returns (kind, pct_label, sub_label). Every valid listing shows a
    relative position to the typical price (design brief #7).
    """
    if price is None:
        return ("not_comp", "—", "Not comparable")
    if not valid or lo is None or hi is None or typical is None:
        return ("limited", "—", "No published range")
    pct = abs(price - typical) / typical * 100 if typical else 0.0
    if price < lo:
        return ("deal", f"↓ {pct:.1f}% below typical", "Potential deal")
    if price <= hi:
        if price < typical:
            return ("fair", f"↓ {pct:.1f}% below typical", "Fair price")
        return ("fair", f"↑ {pct:.1f}% above typical", "Fair price")
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


def match_label(level):
    return {
        "exact_configuration": "Exact configuration",
        "exact_reference_variant": "Variant configuration",
        "related_reference": "Related reference",
        "rejected": "Rejected (parts/accessories)",
        "unverified": "Unverified",
    }.get(level, level or "Unknown")


def exclusion_reason(row, brand, model, ref, active_material):
    """Human-readable reason a row is excluded from the exact range (#10)."""
    level = row[16]
    material = row[12] or ""
    if level == "rejected":
        return "Title indicates parts or accessories, not a complete watch."
    if level == "exact_reference_variant":
        if material and active_material and material != active_material:
            return (f"{material} configuration; excluded from "
                    f"{active_material} reference pricing.")
        return "Configuration differs from the active reference."
    if level == "related_reference":
        return "Different reference; not comparable for exact pricing."
    if level == "unverified":
        return "Reference not in the canonical set."
    return ""


def relevance_group(title, model, ref, active_material, material):
    """Rank a related row into a relevance group (#4).

    Closest alternatives: same model family *and* same material as the
    active configuration. Other variants: same family, different material.
    Historical: unrelated family.
    """
    t = (title or "").lower()
    m = (model or "").lower()
    fam_tokens = [w for w in re.findall(r"[a-z0-9]+", m) if len(w) > 2]
    fam_hit = bool(fam_tokens) and all(w in t for w in fam_tokens)
    ref_hit = bool(re.search(r"ref[. ]?\s*[\w/]+", t))
    same_mat = (bool(active_material) and bool(material)
                and market.normalize_material(material)
                == market.normalize_material(active_material))
    if fam_hit and same_mat:
        return REL_CLOSEST
    if fam_hit or ref_hit:
        return REL_VARIANT
    return REL_HISTORICAL


def build_report(db, slug):
    meta = q(db, "SELECT brand, ref, model, case_material, url FROM references_meta WHERE slug=?",
             (slug,))
    if not meta:
        return None
    brand, ref, model, material, ref_url = meta[0]

    # --- canonical + snapshot (Phases 2, 4, 5) ---
    cfg = q(db, "SELECT id FROM watch_configuration WHERE reference_id=? AND active=1",
            (slug,))
    cfg_id = cfg[0][0] if cfg else None
    snap = market.latest_snapshot(db, cfg_id) if cfg_id else None
    elig = market.eligibility(db, slug)
    valid = elig["range_eligible"]

    band_lo = snap[7] if snap else None        # lower_range
    typical = snap[8] if snap else None        # typical_price
    band_hi = snap[9] if snap else None        # upper_range
    method = snap[2] if snap else market.METHODOLOGY_VERSION
    excluded = (snap[5] or "[]") if snap else "[]"

    # Published-range fields are consumer-facing: never expose them for a
    # reference that fails eligibility (design brief #1).
    if not valid:
        band_lo, band_hi, typical = None, None, None

    # --- deduplicated representative rows (Phase 3) ---
    exact_rows = q(db, REP_QUERY, (slug, "exact_configuration"))
    variant_rows = q(db, REP_QUERY, (slug, "exact_reference_variant"))
    rel_rows = q(db, REP_QUERY, (slug, "related_reference"))
    rejected_rows = q(db, REP_QUERY, (slug, "rejected"))

    raw_n = q(db, "SELECT COUNT(*) FROM listings WHERE slug=?", (slug,))[0][0]
    cluster_n = q(db, "SELECT COUNT(DISTINCT listing_cluster_id) FROM listings "
                      "WHERE slug=? AND listing_cluster_id IS NOT NULL", (slug,))[0][0]
    likely_dup_n = q(db, "SELECT COUNT(DISTINCT listing_cluster_id) FROM "
                         "listings WHERE slug=? AND listing_cluster_id IS NOT NULL "
                         "AND listing_cluster_id IN "
                         "(SELECT id FROM listing_cluster WHERE cluster_confidence < 1.0)",
                     (slug,))[0][0]

    prices = [r[1] for r in exact_rows if r[1] is not None]
    n_exact = len(exact_rows)
    n_dealers = elig["n_dealers"]
    all_rep_rows = exact_rows + variant_rows + rel_rows
    image = next((r[7] for r in all_rep_rows if r[7]), None)

    stamps = [r[15] for r in all_rep_rows if r[15]]
    updated = max(stamps) if stamps else None

    auc_rows = q(db, "SELECT hammer_usd, year_sold, venue FROM auction_lots "
                     "WHERE ref_slug=?", (slug,))
    auc_prices = [r[0] for r in auc_rows if r[0] is not None]

    # --- listing rows, exact first, then variant, then related ---
    listing_data = {}
    active_material = elig.get("_active_material", material or "")

    def row_html(r, lo, hi, typ_p, use_range):
        (lid, price, cur, cond, bp, _avail, merchant, img, buy, detail, title,
         year, mat, size, mov, fetched, level, reason, src_name,
         src_list_id, cid) = r
        kind, pct_label, sub = classify(price, lo, hi, typ_p, use_range)
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
            safe_text(year or ""), safe_text(mat or ""),
            f"{size:g}mm" if size else ""] if x)
        head, sub_t = canonical_title(r, brand, model, ref)
        title_html = (f'<div class="listing-title">{safe_text(head)}</div>'
                      f'<div class="listing-sub">{safe_text(sub_t)}</div>')
        excl_reason = exclusion_reason(r, brand, model, ref, active_material)
        listing_data[str(lid)] = {
            "id": str(lid),
            "title": head,
            "subtitle": sub_t,
            "raw_title": title or "",
            "price": price,
            "currency": cur or "USD",
            "condition": cond or "",
            "box_papers": bp or "",
            "year": year,
            "material": mat or "",
            "size_mm": size,
            "movement": mov or "",
            "merchant": merchant or "",
            "available": bool(_avail),
            "fetched_at": fetched,
            "image_url": img_url,
            "listing_url": safe_external_url(buy) or safe_external_url(detail),
            "kind": kind,
            "pct": pct_label,
            "sub": sub,
            "match_level": level or "",
            "match_reason": reason or "",
            "exclusion_reason": excl_reason,
            "source_name": src_name or "",
            "source_listing_id": src_list_id or "",
            "cluster_id": cid or "",
            "range": (f"{price_fmt(lo)} – {price_fmt(hi)}"
                      if lo is not None else ""),
        }
        return f"""
<tr class="lrow" data-kind="{safe_text(kind)}" data-price="{price if price is not None else 1e18}" data-year="{year or ''}" data-merchant="{safe_text(merchant or '')}" data-available="{1 if _avail else 0}" data-listing-id="{safe_text(lid)}">
 <td><div class="watch-cell">{thumb}
   <div>{title_html}
   <div class="listing-sub">{facts}</div></div></div></td>
 <td class="price-cell">{price_fmt(price)}
   <div class="price-pos">{pct_label if kind in ('deal', 'fair', 'above', 'over') else '&nbsp;'}</div></td>
 <td>{badge}</td>
 <td><div class="seller-cell"><div class="listing-sub">{safe_text(merchant or '—')}</div>
   <div class="listing-sub">{'in stock' if _avail else 'on request'}</div></div></td>
 <td><button class="btn btn-sm" type="button" data-open-listing="{safe_text(lid)}">View analysis</button></td>
</tr>"""

    use_range = valid
    exact_html = "".join(row_html(r, band_lo, band_hi, typical, use_range)
                         for r in exact_rows)
    variant_html = "".join(row_html(r, band_lo, band_hi, typical, use_range)
                           for r in variant_rows)

    # Related rows are ranked into relevance groups (design brief #4).
    rel_groups = {REL_CLOSEST: [], REL_VARIANT: [], REL_HISTORICAL: []}
    for r in rel_rows:
        group = relevance_group(r[10], model, ref, active_material, r[12] or "")
        rel_groups[group].append(r)

    def group_table(group_name, rows):
        if not rows:
            return ""
        rows_html = "".join(row_html(r, None, None, None, False) for r in rows)
        return (f'<div class="rel-group"><div class="rel-group-head">'
                f'{safe_text(group_name)}</div>{rows_html}</div>')

    rel_html = (group_table(REL_CLOSEST, rel_groups[REL_CLOSEST])
                + group_table(REL_VARIANT, rel_groups[REL_VARIANT])
                + group_table(REL_HISTORICAL, rel_groups[REL_HISTORICAL]))
    rejected_html = "".join(row_html(r, None, None, None, False)
                            for r in rejected_rows)

    auc_html = "".join(
        f'<tr><td>{safe_text(a[2] or "—")}</td>'
        f'<td>{safe_text(a[1])}</td>'
        f'<td class="price-cell">{price_fmt(a[0])}</td></tr>'
        for a in auc_rows)

    # Dealer context (design brief #16).
    dealers = {}
    for r in all_rep_rows:
        name = r[6] or ""
        if not name:
            continue
        d = dealers.setdefault(name, {"count": 0, "last": 0})
        d["count"] += 1
        if r[15]:
            d["last"] = max(d["last"], r[15])

    return {
        "slug": slug, "brand": brand, "ref": ref, "model": model,
        "material": material, "ref_url": ref_url,
        "n_exact": n_exact, "n_variant": len(variant_rows),
        "n_related": len(rel_rows), "n_rejected": len(rejected_rows),
        "n_dealers": n_dealers,
        "n_clusters": cluster_n, "n_raw_rows": raw_n,
        "n_likely_dup_clusters": likely_dup_n,
        "listing_median": typical,
        "listing_low": min(prices) if prices else None,
        "listing_high": max(prices) if prices else None,
        "band_lo": band_lo, "band_hi": band_hi,
        "n_auction": len(auc_prices),
        "auc_median": median(auc_prices),
        "image": image,
        "updated": updated,
        "listing_data": listing_data,
        "listings_html": exact_html,
        "variant_html": variant_html,
        "related_html": rel_html,
        "rejected_html": rejected_html,
        "auctions_html": auc_html,
        "src_exact": provenance(db, slug, "listings", exact=1),
        "src_related": provenance(db, slug, "listings", exact=0),
        "src_auctions": provenance(db, slug, "auction_lots"),
        "confidence": elig["overall"],
        "confidence_state": elig["overall"],
        "coverage": elig["coverage"],
        "diversity": elig["diversity"],
        "freshness_dim": elig["freshness_dim"],
        "gates": elig["gates"],
        "method": method,
        "excluded_json": excluded,
        "valid": valid,
        "zero": n_exact == 0,
        "dealers": dealers,
        "active_material": material or "",
    }


# --- state-specific render paths (design brief Phase 7) ---

def render_valid_market_summary(d):
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
 <div class="range-evidence">Based on <b>{d['n_exact']} exact-match listings</b> across <b>{d['n_dealers']} dealers</b> · updated {ago}
 <span class="ev-dot"></span></div>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""


def render_limited_data_summary(d):
    """Honest limited state: explain which gates failed, never show a range."""
    gates = d["gates"]
    failures = []
    if not gates["clusters"]:
        failures.append("fewer than 8 unique listings found")
    if not gates["dealers"]:
        failures.append("fewer than 3 independent dealers")
    if not gates["price_ratio"]:
        failures.append("many listings without a published price")
    if not gates["freshness"]:
        failures.append("most listings are older than 72 hours")
    why = "; ".join(failures) or "coverage is below the published minimum"
    msg = (f"We found <b>{d['n_exact']} observed listings</b> for reference "
           f"{safe_text(d['ref'])} — the observed market is still too thin to "
           f"publish a trustworthy range ({why}).")
    if d["n_related"] + d["n_variant"]:
        msg += (f" {d['n_related'] + d['n_variant']} related listings are "
                "available for broader research below.")
    return f"""
<div class="range-card limited-state">
 <div class="range-label">MARKET COVERAGE DEVELOPING</div>
 <div class="limited-title">No published range yet</div>
 <p class="range-sub">{msg}</p>
 <p class="src">Exact-match data: {d['src_exact']}</p>
</div>"""


def render_zero_data_summary(d):
    """Zero state: no exact-match data at all."""
    return f"""
<div class="range-card limited-state">
 <div class="range-label">MARKET DATA — NOT OBSERVED</div>
 <div class="limited-title">No listings tracked for this reference</div>
 <p class="range-sub">WatchLedger has not yet observed listings for {safe_text(d['ref'])}. When dealers list it, eligibility and pricing run automatically.</p>
 <p class="src">Source of this reference: {d['src_exact'] or 'not yet fetched'}</p>
</div>"""


def render_valid_market_panel(d):
    panel_low = price_fmt(d["band_lo"])
    panel_high = price_fmt(d["band_hi"])
    return f"""<div class="panel"><h3>How to read this market</h3><div class="panel-cols">
 <div class="panel-col"><div class="tag tag-deal">Potential deal</div><p>Listings priced below {panel_low} may be worth a closer look.</p></div>
 <div class="panel-col"><div class="tag tag-fair">Fair range</div><p>Between {panel_low} and {panel_high} is within the observed comparable range.</p></div>
 <div class="panel-col"><div class="tag tag-above">Above market</div><p>Prices above {panel_high} are higher than most comparable listings.</p></div>
 </div></div>"""


def render_limited_data_panel(d):
    return f"""<div class="panel panel-limited"><h3>Why there is no market range yet</h3>
 <p>WatchLedger publishes a range only when the eligibility gates pass: at least
 {market.MIN_CLUSTERS} unique listings, {market.MIN_DEALERS} independent dealers,
 {int(market.MIN_PRICE_RATIO * 100)}% with published prices, and {int(market.MIN_FRESHNESS * 100)}%
 fresher than {market.FRESH_WINDOW // 3600} hours.
 {safe_text(d['ref'])} does not meet these yet, so no deal/fair/above labels are shown.
 Check back after more dealers list this reference, or browse the related listings below.</p></div>"""


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
    title = f"{brand} {model} ({ref}) — WatchLedger"
    image_url = safe_external_url(d["image"])
    if image_url:
        img = (f'<img src="{safe_text(image_url)}" alt="{brand} {model}" '
               f'loading="lazy" referrerpolicy="no-referrer">')
    else:
        img = '<div class="image-placeholder" aria-hidden="true"></div>'
    return title, brand, ref, model, img


def render_confidence(d):
    """Confidence dimensions + gate checklist (Phase 4)."""
    gate_rows = {
        "clusters": f"{market.MIN_CLUSTERS}+ unique listings",
        "dealers": f"{market.MIN_DEALERS}+ independent dealers",
        "price_ratio": f"{int(market.MIN_PRICE_RATIO * 100)}% with published price",
        "freshness": f"{int(market.MIN_FRESHNESS * 100)}% fresh (≤{market.FRESH_WINDOW // 3600}h)",
    }
    gate_html = "".join(
        f'<div class="gate {"ok" if d["gates"][k] else "fail"}">'
        f'<span class="gate-mark">{"✓" if d["gates"][k] else "✕"}</span>'
        f'{safe_text(label)}</div>'
        for k, label in gate_rows.items())
    return f"""<div class="conf-grid">
 <div class="conf-item"><span class="dot"></span><span>Coverage: <b>{d['coverage']}</b> ({d['n_exact']} listings)</span></div>
 <div class="conf-item"><span class="dot"></span><span>Diversity: <b>{d['diversity']}</b> ({d['n_dealers']} dealers)</span></div>
 <div class="conf-item"><span class="dot"></span><span>Freshness: <b>{d['freshness_dim']}</b></span></div>
 <div class="conf-item"><span class="dot"></span><span>Overall: <b>{d['confidence_state']}</b></span></div>
 </div>
 <details class="ev-details gate-details"><summary>Eligibility gates</summary>{gate_html}</details>"""


def render_evidence(d):
    """State-specific evidence language (design brief #8)."""
    if d["zero"]:
        return render_evidence_zero(d)
    if not d["valid"]:
        return render_evidence_limited(d)
    return render_evidence_valid(d)


def _evidence_sources(d):
    ref_link = ""
    ref_url = safe_external_url(d["ref_url"])
    if ref_url:
        ref_link = (f'<p class="src">Reference page: '
                    f'<a href="{safe_text(ref_url)}">{safe_text(d["ref_url"])}</a></p>')
    return ref_link


def _dedup_evidence(d):
    parts = []
    if d["n_raw_rows"] != d["n_clusters"]:
        parts.append(f'<b>{d["n_raw_rows"]}</b> raw rows → '
                     f'<b>{d["n_clusters"]}</b> unique listings (deduplicated)')
    if d["n_likely_dup_clusters"]:
        parts.append(f'<b>{d["n_likely_dup_clusters"]}</b> cluster(s) marked as '
                     f'likely duplicates (dealer+config+price+title signals)')
    if not parts:
        return ""
    inner = "".join(f'<span class="ev-item">{p}</span>' for p in parts)
    return f'<div class="ev-row">{inner}</div>'


def render_evidence_valid(d):
    excluded_n = len(json.loads(d["excluded_json"])) if d["excluded_json"] else 0
    excluded_note = ""
    if excluded_n:
        excluded_note = (f'<p class="src">Outliers excluded by robust MAD filter '
                         f'(z&gt;{market.ROBUST_Z_CUTOFF}): {excluded_n} listing(s). '
                         'Excluded rows are never deleted; they remain in the ledger.</p>')
    return f"""<div class="evidence">
 <div class="ev-title">EVIDENCE BEHIND THIS RANGE</div>
 <div class="ev-row"><span class="ev-item"><b>{d['n_exact']}</b> unique exact-match listings</span>
 <span class="ev-item"><b>{d['n_dealers']}</b> independent dealers</span>
 <span class="ev-item"><b>✓</b> observed from source payloads, not independent live checks</span></div>
 {_dedup_evidence(d)}
 <details class="ev-details"><summary>See sources and methodology</summary>
 <p class="src">Methodology: methodology version {d['method']}; weighted median with
 freshness &amp; completeness weights; robust MAD outlier filter (z&gt;{market.ROBUST_Z_CUTOFF}).
 <a href="/methodology">Read the full methodology →</a></p>
 {excluded_note}
 <p class="src">Exact-match listings: {d['src_exact']}</p>
 <p class="src">Related listings: {d['src_related']}</p>
 <p class="src">Auction data: {d['src_auctions']}</p>
 {_evidence_sources(d)}
 </details>
 </div>"""


def render_evidence_limited(d):
    spread = ""
    if d["listing_low"] is not None and d["listing_high"] is not None:
        spread = (f'<p class="src">Observed asking prices span '
                  f'{price_fmt(d["listing_low"])}–{price_fmt(d["listing_high"])}. '
                  'This is <b>not a published market range</b> because the '
                  'comparison set is insufficient.</p>')
    return f"""<div class="evidence">
<div class="ev-title">CURRENT MARKET COVERAGE</div>
  <div class="ev-row"><span class="ev-item"><b>{d['n_exact']}</b> exact-match listings observed</span>
  <span class="ev-item"><b>{d['n_dealers']}</b> independent dealers</span>
  <span class="ev-item">More listing coverage is needed</span></div>
  {_dedup_evidence(d)}
  <details class="ev-details"><summary>See sources and methodology</summary>
 {spread}
 <p class="src">Methodology: methodology version {d['method']}.
 <a href="/methodology">Read the full methodology →</a></p>
 <p class="src">Exact-match listings: {d['src_exact']}</p>
 <p class="src">Related listings: {d['src_related']}</p>
 {_evidence_sources(d)}
 </details>
 </div>"""


def render_evidence_zero(d):
    return f"""<div class="evidence">
 <div class="ev-title">CURRENT TRACKING STATUS</div>
 <div class="ev-row"><span class="ev-item"><b>{d['n_exact']}</b> exact-match listings observed</span>
 <span class="ev-item"><b>{d['n_related'] + d['n_variant']}</b> broader related listings available</span></div>
 <details class="ev-details"><summary>See sources and methodology</summary>
 <p class="src">Methodology: methodology version {d['method']}.
 <a href="/methodology">Read the full methodology →</a></p>
 <p class="src">Related listings: {d['src_related']}</p>
 {_evidence_sources(d)}
 </details>
 </div>"""


def render_tabs(d):
    v_tab = (f'<span class="tab-n">{d["n_variant"]}</span>' if d["n_variant"] else "")
    r_tab = (f'<span class="tab-n">{d["n_related"]}</span>' if d["n_related"] else "")
    x_tab = (f'<span class="tab-n">{d["n_rejected"]}</span>' if d["n_rejected"] else "")
    return f"""<div class="tabs" id="ltabs">
 <button class="tab active" type="button" data-tab="exact">Exact matches <span class="tab-n">{d['n_exact']}</span></button>
 <button class="tab" type="button" data-tab="variant">Variants {v_tab}</button>
 <button class="tab" type="button" data-tab="related">Related {r_tab}</button>
 <button class="tab" type="button" data-tab="excluded">Excluded {x_tab}</button>
</div>
<div class="filters" id="lfilters">
 <select class="fsel" data-filter="condition" aria-label="Filter by condition"><option value="">Condition: All</option>
  <option>Excellent</option><option>Very good</option><option>Good</option><option>Unworn</option></select>
 <select class="fsel" data-filter="bp" aria-label="Filter by box and papers"><option value="">Box &amp; papers: All</option>
  <option value="full_set">Full set</option><option value="box_and_papers">Box &amp; papers</option><option value="watch_only">Watch only</option></select>
 <select class="fsel" data-filter="avail" aria-label="Filter by availability"><option value="">Availability: All</option>
  <option value="1">In stock</option><option value="0">On request</option></select>
 <select class="fsel" data-filter="merchant" aria-label="Filter by seller"><option value="">Seller: All</option></select>
 <span class="sort-label">Sort</span>
 <select class="fsel" id="fsort" aria-label="Sort listings"><option value="best">Best value</option>
  <option value="low">Lowest price</option><option value="high">Highest price</option>
  <option value="typical">Closest to typical</option><option value="recent">Most recently observed</option>
  <option value="newest">Newest listing</option></select>
</div>"""


def render_selected_configuration(d):
    """Show the active configuration prominently (design brief #5)."""
    mat = safe_text(d["active_material"] or "—")
    return f"""<div class="config-box">
 <div class="config-label">SELECTED CONFIGURATION</div>
 <div class="config-value">{safe_text(d['ref'])}</div>
 <div class="config-sub">{mat} · pricing applies to this configuration only</div>
</div>"""


def render_listing_table(d, rows_html, table_id, header=None):
    head = header or ("<tr><th>Watch</th><th>Price</th><th>Position</th>"
                      "<th>Seller</th><th></th></tr>")
    return f"""<table class="listing-table" id="{table_id}">
 <thead>{head}</thead>
 <tbody>{rows_html}</tbody></table>"""


def render_drawer():
    return """<div class="drawer-mask" id="dmask" aria-hidden="true"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true" aria-label="Listing analysis">
 <button id="drawer-close" class="drawer-close" type="button" data-close-drawer aria-label="Close listing analysis">×</button>
 <div id="drawer-body"></div>
</aside>"""


def render_track_form(d):
    """Tracking CTA with alert preference types (design brief #9)."""
    model = safe_text(d["model"] or d["ref"])
    limited = not d["valid"]
    if limited:
        prompt = ("Notify me when WatchLedger has enough independent evidence "
                  "to publish a market range.")
        types = [(t, l) for t, l in ALERT_TYPES if t == "coverage_ready"]
    else:
        prompt = f"Get an email when the market for {model} changes meaningfully."
        types = [(t, l) for t, l in ALERT_TYPES if t != "coverage_ready"]
    boxes = "".join(
        f'<label class="track-choice"><input type="checkbox" name="alerts" value="{t}">'
        f'<span>{safe_text(l)}</span></label>'
        for t, l in types)
    return f"""<div class="track-box">
 <h3>Track this watch</h3>
 <p class="track-sub">{prompt}</p>
 <form id="track-form" action="/api/track" method="post" data-slug="{safe_text(d['slug'])}" data-valid="{1 if not limited else 0}">
  <div class="track-alerts">{boxes}</div>
  <label class="track-field"><input type="email" name="email" required placeholder="you@example.com" autocomplete="email">
  <button class="btn btn-primary" type="submit">Start tracking</button></label>
  <p class="track-note">Double opt-in confirmation by email. One-click unsubscribe in every email. No spam, ever.</p>
 </form>
 <div class="track-done" id="track-done" hidden aria-live="polite">✓ Almost done — check your inbox to confirm.</div>
</div>"""


def render_dealers(d):
    if not d["dealers"]:
        return ""
    rows = "".join(
        f'<tr><td>{safe_text(name)}</td><td>{cnt} listings observed</td>'
        f'<td>{render_ago(last)}</td></tr>'
        for name, info in sorted(d["dealers"].items())
        for cnt, last in [(info["count"], info["last"])])
    return f"""<section class="live-section">
 <div class="live-head"><h2>Dealers observed</h2>
 <div class="sub">Every listing links directly to its source listing</div></div>
 <table class="listing-table"><thead><tr><th>Dealer</th><th>Listings</th><th>Last observed</th></tr></thead>
 <tbody>{rows}</tbody></table>
</section>"""


def render(d):
    title, brand, ref, model, img = render_meta(d)
    ago = render_ago(d.get("updated"))

    if d["zero"]:
        summary = render_zero_data_summary(d)
        panel = render_limited_data_panel(d)
    elif not d["valid"]:
        summary = render_limited_data_summary(d)
        panel = render_limited_data_panel(d)
    else:
        summary = render_valid_market_summary(d)
        panel = render_valid_market_panel(d)

    conf = render_confidence(d)
    evidence = render_evidence(d)

    tabs = render_tabs(d)
    table_exact = render_listing_table(d, d["listings_html"], "tbl-exact")
    table_variant = render_listing_table(d, d["variant_html"], "tbl-variant",
                                         header="<tr><th>Watch</th><th>Price</th>"
                                                "<th>Position</th><th>Seller</th><th></th></tr>")
    table_rel = render_listing_table(d, d["related_html"], "tbl-related")
    table_rejected = render_listing_table(d, d["rejected_html"], "tbl-excluded",
                                          header="<tr><th>Watch</th><th>Price</th>"
                                                 "<th>Position</th><th>Seller</th><th></th></tr>")

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

    drawer = render_drawer()
    track_form = render_track_form(d)
    dealers = render_dealers(d)

    desc = (f"{d['n_exact']} observed listings for {brand} {model} "
            f"(Ref. {ref}). WatchLedger computes market ranges deterministically "
            f"from traceable dealer listings.")
    og_image = safe_external_url(d["image"])
    jsonld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": f"{brand} {model} (Ref. {ref})",
        "brand": {"@type": "Brand", "name": brand},
        "category": "Watches",
        "description": desc,
    }
    if d["band_lo"] is not None:
        jsonld["offers"] = {
            "@type": "AggregateOffer",
            "lowPrice": d["band_lo"],
            "highPrice": d["band_hi"],
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        }

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{safe_text(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="/reference/{safe_text(d['slug'])}">
<meta name="description" content="{safe_text(desc)}">
<meta property="og:type" content="product">
<meta property="og:title" content="{safe_text(title)}">
<meta property="og:description" content="{safe_text(desc)}">
{('' if not og_image else f'<meta property="og:image" content="{safe_text(og_image)}">')}
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{safe_json_script(jsonld)}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css"></head><body>
<header class="nav"><div class="nav-inner">
<a href="/" class="logo">watch<span>ledger</span></a>
<nav class="nav-links"><a href="/#markets">Explore Watches</a><a href="/#how">Market Trends</a><a href="/#trust">How It Works</a></nav>
<div class="nav-actions">
<a class="nav-icon" href="/" aria-label="Search">⌕</a>
<a href="/methodology" class="btn btn-ghost">Methodology</a>
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
  <p class="model-desc">Case material: {safe_text(d['material'] or '—')}. Market data computed deterministically from {d['n_exact']} observed listings.</p>
  <div class="model-meta">
   <div class="stat"><div class="k">Observed listings</div><div class="v">{d['n_exact']}</div></div>
   <div class="stat"><div class="k">Independent dealers</div><div class="v">{d['n_dealers']}</div></div>
   <div class="stat"><div class="k">Confidence</div><div class="v">{d['confidence']}</div></div>
   <div class="stat"><div class="k">Last checked</div><div class="v">{ago}</div></div>
  </div>
  {render_selected_configuration(d)}
  {summary}
  {panel}
  {conf}
 </div>
</div>
{evidence}
{track_form}

<section class="live-section">
 <div class="live-head"><h2>Observed listings</h2>
 <div class="sub">{d['n_exact']} exact · {d['n_variant']} variants · {d['n_related']} related · observed {ago}</div></div>
 {tabs}
 {table_exact}
 {table_variant}
 {table_rel}
 {table_rejected}
</section>
{dealers}
{auc_block}
</main>
{drawer}
<footer><div class="footer-inner">
<div class="col"><div class="logo">watch<span>ledger</span></div>
<p>Every number above traces to the raw payload at the listed source URL. No AI, no guesswork.</p></div>
<div class="col"><b>Data</b><a href="/raw/">Raw payloads</a><a href="/api/reference/{safe_text(d['slug'])}.json">JSON for this watch</a></div>
<div class="col"><b>Product</b><a href="/methodology">Methodology</a><a href="/#trust">Why it's trustworthy</a><a href="/#how">How it works</a></div>
</div></footer>
<script id="listing-data" type="application/json">{safe_json_script(d["listing_data"])}</script>
<script src="/static/report.js" defer></script>
</body></html>"""


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    slugs = [r[0] for r in q(db, "SELECT slug FROM references_meta ORDER BY slug")]
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