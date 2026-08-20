"""Market engine: canonical matching, deduplication, eligibility, pricing, history.

Implements the design brief's Phases 2-6:

Phase 2 — Canonical watch matching
  watch_reference + watch_configuration entities; every listing is assigned a
  match_level (exact_configuration | exact_reference_variant | related_reference
  | unverified | rejected) with a stored match_reason.

Phase 3 — Deduplicate listings before analytics
  listing_cluster groups duplicate rows. Only the representative listing of a
  cluster counts in market calculations.

Phase 4 — Market eligibility and confidence gates
  A range is published only when minimum coverage, diversity, freshness, and
  validity gates pass. Confidence is shown as three dimensions plus an overall
  state computed from the lowest important dimension.

Phase 5 — Outlier handling and conservative pricing
  MAD-based robust z-scores flag outliers (never silently deleted). Prices are
  combined with a weighted median and weighted percentiles; every step is
  stored in a reproducible market_snapshot.

Phase 6 — Persist market history
  source_fetch, listing_observation, and market_snapshot rows are appended on
  every build; prior observations are never overwritten.

Phase 10 — Source registry
  The `source` table records access method, permission status, and image usage.

Everything is deterministic and stdlib-only.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from urllib.parse import urlparse

# Methodology version for all snapshots. Bump when a rule changes so old
# snapshots are never mistaken for the current method.
METHODOLOGY_VERSION = "1.0"

# Eligibility gates (Phase 4 initial minima).
MIN_CLUSTERS = 8
MIN_DEALERS = 3
MIN_PRICE_RATIO = 0.8
MIN_FRESHNESS = 0.7
FRESH_WINDOW = 72 * 3600

# Match levels that may influence a strict range.
RANGE_ELIGIBLE = ("exact_configuration",)

# Confidence bands (Phase 4).
COVERAGE_HIGH = 20
COVERAGE_MEDIUM = 8
DIVERSITY_HIGH = 5
DIVERSITY_MEDIUM = 3
FRESHNESS_HIGH = 0.9
FRESHNESS_MEDIUM = 0.7

# MAD outlier policy (Phase 5).
ROBUST_Z_CUTOFF = 3.5

# Weighting factors (Phase 5).
FRESH_24H = 1.00
FRESH_24_72H = 0.85
FRESH_3_7D = 0.60
COMPLETE_WEIGHT = 1.00
INCOMPLETE_WEIGHT = 0.75


def normalize_reference(value):
    """Return a canonical alphanumeric reference key, or ''."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def normalize_material(value):
    """Normalize a case material string into a stable comparison key."""
    if not value:
        return ""
    s = str(value).lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def fingerprint_from_url(url):
    """Stable fingerprint for a canonical URL (buy_url preferred)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = (parsed.netloc + parsed.path).lower().rstrip("/")
        return hashlib.sha256(path.encode("utf-8")).hexdigest()
    except ValueError:
        return ""


def _hash(*parts):
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# --- Phase 2: canonical entities -------------------------------------------

def build_canonical(db, refs_meta, listings):
    """Create canonical references and configurations.

    refs_meta: list of rows (slug, brand, ref, model, case_material, url,
               source_url, fetched_at) from references_meta.
    listings:  list of rows from listings with slug, case_material,
               case_size_mm, exact.

    The active configuration for a reference is the most common
    (case_material, case_size_mm) pair among its exact listings.
    """
    now = time.time()
    for slug, brand, ref, model, material, url, src, ts in refs_meta:
        ref_key = normalize_reference(ref)
        db.execute(
            "INSERT OR REPLACE INTO watch_reference "
            "(id, brand, family, model_name, reference_number, "
            "reference_normalized, production_start_year, production_end_year, "
            "source_url, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (slug, brand, model, model, ref, ref_key, None, None,
             url or "", ts if ts else now))

        configs = {}
        for row in listings:
            if row[1] != slug:  # listings row: id, slug, ...
                continue
            mat = normalize_material(row[7])          # case_material
            key = mat if mat else "unknown"
            configs[key] = configs.get(key, 0) + 1
        active_key = max(configs, key=configs.get) if configs else ""

        for key in configs:
            cid = f"{slug}::{key}"
            active = 1 if key == active_key else 0
            db.execute(
                "INSERT OR REPLACE INTO watch_configuration "
                "(id, reference_id, configuration_key, case_material, dial, "
                "bracelet, bezel, case_size_mm, production_variant, active) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, slug, key, key if key != "unknown" else None, None, None,
                 None, None, None, active))


def _config_for(row, refs):
    """Return (config_id, config_key, active) for a listings row."""
    slug = row[1]
    mat = normalize_material(row[7])
    key = mat if mat else "unknown"
    ref = refs.get(slug)
    if not ref:
        return None, key, False
    return f"{slug}::{key}", key, key == ref["active_key"]


def match_all(db, refs):
    """Assign match_level, match_reason, canonical ids to every listing.

    refs: dict slug -> {"ref_key": ..., "active_key": ..., "brand": ...}
    """
    rows = db.execute("SELECT * FROM listings").fetchall()
    cols = [d[0] for d in db.execute("SELECT * FROM listings LIMIT 1").description]
    idx = {name: i for i, name in enumerate(cols)}

    for row in rows:
        slug = row[idx["slug"]]
        ref_entry = refs.get(slug)
        title = row[idx["title"]] or ""
        listing_ref = row[idx["source_listing_id"]] or row[idx["id"]] or ""

        if not ref_entry:
            level, reason = "unverified", "Reference not in canonical set."
        else:
            title_l = title.lower()
            if any(w in title_l for w in ("strap", "bracelet", "parts",
                                          "tool", "winders", "box only",
                                          "papers only")):
                level, reason = ("rejected",
                                 "Title indicates a parts/accessory listing.")
            else:
                # The exact endpoint matched this listing to the reference.
                # Cross-check the configuration against the active one.
                cfg_id, cfg_key, active = _config_for(row, refs)
                if row[idx["exact"]] and active:
                    level = "exact_configuration"
                    reason = (f"Exact source reference matched {slug}; "
                              f"{row[idx['case_material']] or 'unknown'} case")
                elif row[idx["exact"]] and not active:
                    level = "exact_reference_variant"
                    variant_mat = row[idx['case_material']] or "unknown"
                    active_mat = ref_entry.get("active_material") or "unknown"
                    if active_mat != variant_mat and variant_mat != "unknown":
                        reason = (f"{variant_mat} configuration; excluded from "
                                  f"the {active_mat} reference pricing")
                    else:
                        reason = ("Exact reference but configuration differs "
                                  f"({variant_mat} case)")
                else:
                    level = "related_reference"
                    reason = "Same family, different reference; excluded from exact range."

        cfg_id, _, _ = _config_for(row, refs)
        db.execute(
            "UPDATE listings SET canonical_reference_id=?, "
            "canonical_configuration_id=?, match_level=?, match_reason=?, "
            "match_confidence=? WHERE id=?",
            (slug, cfg_id, level, reason, 1.0 if level == "exact_configuration"
             else 0.5, row[idx["id"]]))


# --- Phase 3: deduplication -------------------------------------------------

def _norm_title(value):
    """Lowercase, de-punctuated, tokenised title for duplicate comparison."""
    if not value:
        return ()
    return tuple(re.findall(r"[a-z0-9]+", str(value).lower()))


def _title_similar(a, b):
    """Jaccard-like overlap of the two normalized title token sets."""
    ta, tb = set(_norm_title(a)), set(_norm_title(b))
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    if not union:
        return False
    return inter / union >= 0.7


def cluster_listings(db, rows):
    """Group duplicate listings into clusters.

    Definite duplicate (cluster_confidence 1.0): same canonical URL
    (buy_url/detail_url), same source listing id, or same fingerprint.

    Likely duplicate (cluster_confidence 0.7): several signals agree —
    same dealer, same exact configuration, near-identical price, and
    similar normalized title (design brief #3).

    Returns dict listing_id -> cluster_id.
    """
    now = time.time()
    cols = [d[0] for d in db.execute("SELECT * FROM listings LIMIT 1").description]
    idx = {name: i for i, name in enumerate(cols)}

    url_seen = {}
    id_seen = {}
    cluster_for = {}
    counter = 0

    def new_cluster(row, confidence, basis):
        nonlocal counter
        counter += 1
        cid = f"cl_{counter}"
        db.execute(
            "INSERT OR REPLACE INTO listing_cluster "
            "(id, canonical_reference_id, representative_listing_id, "
            "cluster_confidence, cluster_basis, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (cid, row[idx["slug"]], row[idx["id"]], confidence, basis, now, now))
        return cid

    # Pass 1 — definite duplicates by id / URL / fingerprint.
    for row in rows:
        lid = row[idx["id"]]
        src_list_id = row[idx["source_listing_id"]] or lid
        buy = row[idx["buy_url"]] or ""
        detail = row[idx["detail_url"]] or ""
        fp = fingerprint_from_url(buy) or fingerprint_from_url(detail)

        cid = None
        if src_list_id in id_seen:
            cid = id_seen[src_list_id]
        elif fp and fp in url_seen:
            cid = url_seen[fp]
        if not cid:
            cid = new_cluster(row, 1.0, "source_id/url")
        cluster_for[lid] = cid
        id_seen[src_list_id] = cid
        if fp:
            url_seen[fp] = cid
        db.execute(
            "UPDATE listings SET listing_cluster_id=? WHERE id=?", (cid, lid))

    # Pass 2 — likely duplicates by signals. Cluster rows that share a dealer,
    # exact configuration, near-identical price, and similar title. Deterministic:
    # iterate in row order, bind to the first matching cluster. Re-read fresh
    # rows: canonical_configuration_id is assigned by match_all *after* the
    # caller captured its row tuples.
    fresh = db.execute("SELECT * FROM listings").fetchall()
    sig_seen = {}  # signature -> cluster id for the first row with that signal
    for row in fresh:
        lid = row[idx["id"]]
        merchant = row[idx["merchant_name"]] or ""
        cfg = row[idx["canonical_configuration_id"]] or ""
        price = row[idx["price_usd"]]
        title = row[idx["title"]] or ""
        if not merchant or not cfg or price is None:
            continue
        norm = _norm_title(title)
        if not norm:
            continue
        matched = None
        for sig, cid in sig_seen.items():
            if merchant != sig[0] or cfg != sig[1]:
                continue
            if abs(sig[2] - price) / max(price, 1.0) > 0.01:
                continue
            if _title_similar(sig[3], title):
                matched = cid
                break
        if matched:
            if cluster_for[lid] != matched:
                # Merge: move the row onto the existing cluster (keep the
                # earlier representative). Confidence stays 0.7 for both.
                old = cluster_for[lid]
                db.execute(
                    "UPDATE listing_cluster SET cluster_confidence=0.7, "
                    "cluster_basis='dealer/config/price/title signals' "
                    "WHERE id=? OR id=?", (old, matched))
                cluster_for[lid] = matched
                db.execute("UPDATE listings SET listing_cluster_id=? WHERE id=?",
                           (matched, lid))
        else:
            sig = (merchant, cfg, price, title)
            sig_seen[sig] = cluster_for[lid]

    # representative: available, then earliest fetched_at, then lowest price
    for cid in sorted(set(cluster_for.values())):
        members = db.execute(
            "SELECT id, available, fetched_at, price_usd FROM listings "
            "WHERE listing_cluster_id=?", (cid,)).fetchall()
        if not members:
            continue
        rep = min(members, key=lambda r: (0 if r[1] else 1,
                                          r[2] or 0, r[3] or 1e18))
        db.execute("UPDATE listing_cluster SET representative_listing_id=? "
                   "WHERE id=?", (rep[0], cid))

    return cluster_for


# --- Phase 4: eligibility and confidence ------------------------------------

def eligibility(db, slug):
    """Evaluate the Phase 4 gates for one reference."""
    rows = db.execute(
        """SELECT l.listing_cluster_id, l.merchant_name, l.price_usd,
                  l.fetched_at, l.match_level
           FROM listings l
           WHERE l.slug=? AND l.listing_cluster_id IS NOT NULL
             AND l.match_level = 'exact_configuration'""", (slug,)).fetchall()

    unique = {}
    for cid, merchant, price, fetched, level in rows:
        if cid not in unique:
            unique[cid] = {"merchant": merchant, "price": price,
                           "fetched": fetched, "level": level}
    n_clusters = len(unique)
    n_dealers = len({v["merchant"] for v in unique.values() if v["merchant"]})
    prices = [v["price"] for v in unique.values()]
    n_priced = sum(1 for p in prices if p is not None)
    price_ratio = n_priced / n_clusters if n_clusters else 0.0

    now = time.time()
    fresh = sum(1 for v in unique.values()
                if v["fetched"] and now - v["fetched"] <= FRESH_WINDOW)
    freshness = fresh / n_clusters if n_clusters else 0.0

    gates = {
        "clusters": n_clusters >= MIN_CLUSTERS,
        "dealers": n_dealers >= MIN_DEALERS,
        "price_ratio": price_ratio >= MIN_PRICE_RATIO,
        "freshness": freshness >= MIN_FRESHNESS,
    }

    coverage = ("High" if n_clusters >= COVERAGE_HIGH
                else "Medium" if n_clusters >= COVERAGE_MEDIUM
                else "Limited")
    diversity = ("High" if n_dealers >= DIVERSITY_HIGH
                 else "Medium" if n_dealers >= DIVERSITY_MEDIUM
                 else "Limited")
    freshness_dim = ("High" if freshness >= FRESHNESS_HIGH
                     else "Medium" if freshness >= FRESHNESS_MEDIUM
                     else "Limited")

    rank = {"High": 0, "Medium": 1, "Limited": 2, "Insufficient": 3}
    if not all(gates.values()) or n_clusters < MIN_CLUSTERS:
        overall = "Insufficient"
    else:
        # Overall confidence may never exceed the weakest critical dimension.
        # rank stores higher values as *weaker*; max() picks the weakest.
        overall = max([coverage, diversity, freshness_dim],
                      key=lambda x: rank.get(x, 3))

    return {
        "n_clusters": n_clusters,
        "n_dealers": n_dealers,
        "n_priced": n_priced,
        "price_ratio": price_ratio,
        "freshness": freshness,
        "gates": gates,
        "coverage": coverage,
        "diversity": diversity,
        "freshness_dim": freshness_dim,
        "overall": overall,
        "range_eligible": overall in ("High", "Medium"),
    }


# --- Phase 5: conservative pricing ------------------------------------------

def _fresh_weight(fetched_at, now):
    if not fetched_at:
        return 1.0
    age = now - fetched_at
    if age <= 24 * 3600:
        return FRESH_24H
    if age <= 72 * 3600:
        return FRESH_24_72H
    return FRESH_3_7D


def _completeness_weight(condition, box_papers, case_material):
    known = sum(1 for v in (condition, box_papers, case_material) if v)
    return COMPLETE_WEIGHT if known >= 2 else INCOMPLETE_WEIGHT


def weighted_median(pairs):
    """pairs: list of (value, weight). Returns weighted median or None."""
    items = sorted(pairs)
    values = [v for v, w in items if v is not None and w > 0]
    weights = [w for v, w in items if v is not None and w > 0]
    if not values:
        return None
    total = sum(weights)
    if total <= 0:
        return statistics.median(values)
    acc = 0.0
    for v, w in zip(values, weights):
        acc += w
        if acc >= total / 2:
            return v
    return values[-1]


def weighted_percentile(pairs, percentile):
    """Weighted percentile of (value, weight) pairs."""
    data = sorted(pairs)
    values = [v for v, w in data if v is not None and w > 0]
    weights = [w for v, w in data if v is not None and w > 0]
    if not values:
        return None
    total = sum(weights)
    if total <= 0:
        xs = sorted(values)
        return xs[min(len(xs) - 1, int(len(xs) * percentile))]
    target = total * percentile
    acc = 0.0
    for v, w in zip(values, weights):
        acc += w
        if acc >= target:
            return v
    return values[-1]


def calculate_market(db, slug, eligibility_result, now=None):
    """Compute the Phase 5 market snapshot for one reference.

    Returns a dict of snapshot fields, or None when no eligible cluster exists.
    """
    now = now or time.time()
    rows = db.execute(
        """SELECT l.listing_cluster_id, l.id, l.price_usd, l.condition,
                  l.box_papers, l.case_material, l.fetched_at, l.available
           FROM listings l
           WHERE l.slug=? AND l.listing_cluster_id IS NOT NULL
             AND l.match_level = 'exact_configuration'""", (slug,)).fetchall()

    # one representative listing per cluster (cluster.representative_listing_id)
    reps = {}
    for cid, lid, price, cond, bp, mat, fetched, avail in rows:
        rep_lid = db.execute(
            "SELECT representative_listing_id FROM listing_cluster WHERE id=?",
            (cid,)).fetchone()
        if rep_lid and rep_lid[0] == lid:
            reps[cid] = {"price": price, "condition": cond, "box_papers": bp,
                         "material": mat, "fetched_at": fetched,
                         "available": avail}

    if not reps:
        return None

    prices = [r["price"] for r in reps.values() if r["price"] is not None]
    if not prices:
        return None

    med = statistics.median(prices)
    mad = statistics.median([abs(p - med) for p in prices]) or 1.0

    excluded_ids = []
    excluded_reasons = []
    kept = []
    for cid, r in reps.items():
        if r["price"] is None:
            continue
        robust_z = 0.6745 * (r["price"] - med) / mad
        if abs(robust_z) > ROBUST_Z_CUTOFF:
            excluded_ids.append(cid)
            excluded_reasons.append(
                f"{cid}: price outlier pending review "
                f"(robust z={robust_z:.2f} exceeds {ROBUST_Z_CUTOFF})")
        else:
            kept.append((cid, r))

    pairs = []
    for cid, r in kept:
        w = _fresh_weight(r["fetched_at"], now)
        w *= _completeness_weight(r["condition"], r["box_papers"], r["material"])
        pairs.append((r["price"], w))

    typical = weighted_median(pairs)
    lower = weighted_percentile(pairs, 0.1)
    upper = weighted_percentile(pairs, 0.9)

    return {
        "methodology_version": METHODOLOGY_VERSION,
        "input_cluster_ids_json": json.dumps(sorted(reps.keys())),
        "excluded_cluster_ids_json": json.dumps(sorted(excluded_ids)),
        "exclusion_reasons_json": json.dumps(excluded_reasons),
        "lower_range": lower,
        "typical_price": typical,
        "upper_range": upper,
        "n_used": len(kept),
        "n_excluded": len(excluded_ids),
        "confidence_state": eligibility_result["overall"],
    }


def save_snapshot(db, configuration_id, calc, eligibility_result):
    """Persist one market_snapshot (Phase 6). Returns id or None."""
    if not calc:
        return None
    db.execute(
        "INSERT INTO market_snapshot "
        "(configuration_id, calculated_at, methodology_version, "
        "input_cluster_ids_json, excluded_cluster_ids_json, "
        "exclusion_reasons_json, lower_range, typical_price, upper_range, "
        "coverage_score, diversity_score, freshness_score, confidence_state) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (configuration_id, time.time(), calc["methodology_version"],
         calc["input_cluster_ids_json"], calc["excluded_cluster_ids_json"],
         calc["exclusion_reasons_json"], calc["lower_range"],
         calc["typical_price"], calc["upper_range"],
         eligibility_result["coverage"], eligibility_result["diversity"],
         eligibility_result["freshness_dim"], calc["confidence_state"]))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def latest_snapshot(db, configuration_id):
    """Return the most recent snapshot for a configuration, or None."""
    return db.execute(
        "SELECT * FROM market_snapshot WHERE configuration_id=? "
        "ORDER BY calculated_at DESC LIMIT 1", (configuration_id,)).fetchone()


def record_observations(db, listings, source_url, fetched_at):
    """Append a listing_observation for every current listing (Phase 6)."""
    if not listings:
        return None
    fetch_id = db.execute(
        "INSERT INTO source_fetch (source_name, fetched_at, source_url, "
        "payload_hash, fetch_status) VALUES (?,?,?,?,?)",
        ("mostexpensivewatches.net", fetched_at, source_url or "",
         _hash(source_url, fetched_at), "ok")).lastrowid
    for row in listings:
        db.execute(
            "INSERT INTO listing_observation "
            "(listing_id, source_fetch_id, observed_at, price_original, "
            "currency, price_usd, availability, content_hash) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (row[0], fetch_id, fetched_at, row[3], row[4], row[3],
             1 if row[12] else 0, _hash(row[0], row[3], row[2])))
    return fetch_id


# --- Phase 10: source registry ---------------------------------------------

def register_sources(db, source_domain, merchant_pairs):
    """Upsert the source registry from observed merchant/domain pairs."""
    now = time.time()
    seen = {}
    for merchant, domain in merchant_pairs:
        if not merchant or not domain:
            continue
        key = domain.lower()
        seen.setdefault(key, merchant)
    for domain, name in seen.items():
        db.execute(
            "INSERT OR REPLACE INTO source "
            "(id, name, domain, access_method, permission_status, "
            "image_usage_status, attribution_requirements, "
            "last_terms_reviewed_at) VALUES (?,?,?,?,?,?,?,?)",
            (domain, name, domain, "public_api" if domain == source_domain
             else "public_web", "unreviewed", "hotlink_pending",
             "attribution required", now))