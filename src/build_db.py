"""Normalize raw payloads into the SQLite ledger and run the market pipeline.

The ledger is a derived view of the raw JSON files. Every normalized row
carries the source URL and fetch timestamp of the payload it came from,
so each number in a report can be traced to its origin.

Pipeline (design brief Phases 2-6):
  1. Insert references_meta / listings / auction_lots (validated URLs).
  2. Build canonical watch_reference + watch_configuration entities.
  3. Assign every listing a match_level and match_reason.
  4. Cluster duplicate listings; pick a representative per cluster.
  5. Evaluate eligibility gates and confidence dimensions per reference.
  6. Calculate and store a reproducible market_snapshot per configuration.
  7. Append listing_observation rows for history.
  8. Register observed sources.
"""

import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from config import RAW_DIR, DB_PATH
from security import safe_external_url
from schema import SCHEMA
import market


_MANAGED_TABLES = (
    "references_meta", "listings", "auction_lots", "watch_reference",
    "watch_configuration", "listing_cluster", "source_fetch",
    "listing_observation", "market_snapshot", "source", "watch_users",
    "watchlist_item", "alert_preference", "alert_delivery",
)


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    for t in _MANAGED_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {t}")
    cur.execute("DROP VIEW IF EXISTS v_listing_market")
    db.executescript(SCHEMA)
    return db


def load_raw(kind, name):
    path = os.path.join(RAW_DIR, kind, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    db = connect()
    cur = db.cursor()
    cur.execute("DELETE FROM references_meta")
    cur.execute("DELETE FROM listings")
    cur.execute("DELETE FROM auction_lots")

    n_refs = n_list = n_auc = 0

    # reference index -> references_meta for every known slug
    index = load_raw("index", "references")
    if index:
        for r in (index.get("payload") or {}).get("references") or []:
            slug = r["slug"]
            cur.execute(
                "INSERT OR IGNORE INTO references_meta VALUES (?,?,?,?,?,?,?,?)",
                (slug, r.get("brand"), r.get("ref"), r.get("model"),
                 r.get("case_material"), safe_external_url(r.get("url")),
                 f"{index.get('source_url','')}", index.get("fetched_at")))
            n_refs += 1

    listings = []  # rows as (id, slug, ..., price_usd, ..., available, ...)

    # per-reference payloads -> listings + auction_lots
    for fname in sorted(os.listdir(os.path.join(RAW_DIR, "references"))):
        if not fname.endswith(".json"):
            continue
        raw = load_raw("references", fname[:-5])
        if not raw:
            continue
        payload, src, ts = raw["payload"], raw["source_url"], raw["fetched_at"]
        slug = fname[:-5]
        for l in payload.get("listings") or []:
            safe_image_url = safe_external_url(l.get("image_url"))
            safe_detail_url = safe_external_url(l.get("detail_url"))
            safe_buy_url = safe_external_url(l.get("buy_url"))
            lid = str(l.get("id"))
            cur.execute(
                "INSERT OR REPLACE INTO listings "
                "(id, slug, title, price_usd, currency, condition, "
                "box_papers, case_material, case_size_mm, movement, year, "
                "merchant_slug, merchant_name, available, image_url, "
                "detail_url, buy_url, exact, source_url, fetched_at, "
                "source_name, source_listing_id, canonical_url, "
                "listing_fingerprint) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, slug, l.get("title"), l.get("price_usd"),
                 l.get("currency"), l.get("condition"), l.get("box_papers"),
                 l.get("case_material"), l.get("case_size_mm"),
                 l.get("movement"), l.get("year"), l.get("merchant_slug"),
                 l.get("merchant_name"),
                 1 if l.get("available") else 0,
                 safe_image_url, safe_detail_url, safe_buy_url,
                 0, src, ts, "mostexpensivewatches.net", lid,
                 safe_buy_url or safe_detail_url,
                 market.fingerprint_from_url(safe_buy_url or safe_detail_url)))
            listings.append(cur.lastrowid or lid)
            n_list += 1

        # exact-match listings from the search endpoint -> exact=1.
        exact = load_raw("exact", fname[:-5])
        if exact:
            for l in (exact.get("payload") or {}).get("items") or []:
                safe_image_url = safe_external_url(l.get("image_url"))
                safe_detail_url = safe_external_url(l.get("detail_url"))
                safe_buy_url = safe_external_url(l.get("buy_url"))
                lid = str(l.get("id"))
                cur.execute(
                    "INSERT OR REPLACE INTO listings "
                    "(id, slug, title, price_usd, currency, condition, "
                    "box_papers, case_material, case_size_mm, movement, year, "
                    "merchant_slug, merchant_name, available, image_url, "
                    "detail_url, buy_url, exact, source_url, fetched_at, "
                    "source_name, source_listing_id, canonical_url, "
                    "listing_fingerprint) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lid, slug, l.get("title"), l.get("price_usd"),
                     l.get("currency"), l.get("condition"), l.get("box_papers"),
                     l.get("case_material"), l.get("case_size_mm"),
                     l.get("movement"), l.get("year"), l.get("merchant_slug"),
                     l.get("merchant_name"),
                     1 if l.get("available") else 0,
                     safe_image_url, safe_detail_url, safe_buy_url,
                     1, exact.get("source_url"), exact.get("fetched_at"),
                     "mostexpensivewatches.net", lid,
                     safe_buy_url or safe_detail_url,
                     market.fingerprint_from_url(safe_buy_url or safe_detail_url)))
                listings.append(cur.lastrowid or lid)
                n_list += 1

        for a in payload.get("auction_lots") or []:
            cur.execute(
                "INSERT OR REPLACE INTO auction_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("slug"), a.get("brand"), a.get("reference"),
                 a.get("model"), a.get("case_material"), a.get("hammer_usd"),
                 a.get("year_sold"), a.get("venue"), safe_external_url(a.get("url")),
                 slug, src, ts))
            n_auc += 1

    # full auction dataset -> auction_lots (all brands, for joins).
    full = load_raw("index", "auctions_full")
    if full:
        for a in (full.get("payload") or {}).get("auction_lots") or []:
            cur.execute(
                "INSERT OR IGNORE INTO auction_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("slug"), a.get("brand"), a.get("reference"),
                 a.get("model"), a.get("case_material"), a.get("hammer_usd"),
                 a.get("year_sold"), a.get("venue"), safe_external_url(a.get("url")), None,
                 full.get("source_url"), full.get("fetched_at")))
            n_auc += 1

    db.commit()

    # ---- Phase 2: canonical entities + matching ----
    refs_meta = cur.execute(
        "SELECT slug, brand, ref, model, case_material, url, source_url, "
        "fetched_at FROM references_meta").fetchall()
    all_listings = cur.execute("SELECT * FROM listings").fetchall()

    market.build_canonical(db, refs_meta, all_listings)

    refs = {}
    for slug, brand, ref, model, material, url, src, ts in refs_meta:
        refs[slug] = {
            "ref_key": market.normalize_reference(ref),
            "active_key": "",
            "brand": brand,
        }
    for row in cur.execute("SELECT reference_id, configuration_key, active "
                           "FROM watch_configuration").fetchall():
        if row[2]:
            refs[row[0]]["active_key"] = row[1]

    market.match_all(db, refs)

    # ---- Phase 3: deduplicate ----
    market.cluster_listings(db, all_listings)

    # ---- Phase 4/5/6: eligibility, pricing, snapshots ----
    slugs = [r[0] for r in cur.execute(
        "SELECT DISTINCT slug FROM listings ORDER BY slug")]
    n_snapshots = 0
    for slug in slugs:
        elig = market.eligibility(db, slug)
        cfg = cur.execute(
            "SELECT id FROM watch_configuration WHERE reference_id=? AND active=1",
            (slug,)).fetchone()
        cfg_id = cfg[0] if cfg else slug
        calc = market.calculate_market(db, slug, elig)
        if market.save_snapshot(db, cfg_id, calc, elig):
            n_snapshots += 1

    # ---- Phase 6: observations ----
    fetched_at = time.time()
    src_url = index.get("source_url", "") if index else ""
    market.record_observations(db, all_listings, src_url, fetched_at)

    # ---- Phase 10: sources ----
    merchant_pairs = cur.execute(
        "SELECT DISTINCT merchant_name, merchant_slug FROM listings "
        "WHERE merchant_name IS NOT NULL AND merchant_slug IS NOT NULL").fetchall()
    market.register_sources(db, "mostexpensivewatches.net", merchant_pairs)

    db.commit()
    print(f"ledger: {n_refs} references, {n_list} listings, {n_auc} auction lots, "
          f"{n_snapshots} snapshots")


if __name__ == "__main__":
    main()