"""Normalize raw payloads into the SQLite ledger.

The ledger is a derived view of the raw JSON files. Every normalized row
carries the source URL and fetch timestamp of the payload it came from,
so each number in a report can be traced to its origin.
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from config import RAW_DIR, DB_PATH


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS references_meta (
        slug TEXT PRIMARY KEY,
        brand TEXT, ref TEXT, model TEXT, case_material TEXT,
        url TEXT, source_url TEXT, fetched_at REAL
    );
    CREATE TABLE IF NOT EXISTS listings (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        title TEXT, price_usd REAL, currency TEXT,
        condition TEXT, box_papers TEXT, case_material TEXT,
        case_size_mm REAL, movement TEXT, year INTEGER,
        merchant_slug TEXT, merchant_name TEXT, available INTEGER,
        image_url TEXT, detail_url TEXT, buy_url TEXT,
        source_url TEXT, fetched_at REAL
    );
    CREATE TABLE IF NOT EXISTS auction_lots (
        slug TEXT PRIMARY KEY,
        brand TEXT, reference TEXT, model TEXT, case_material TEXT,
        hammer_usd REAL, year_sold INTEGER, venue TEXT,
        lot_url TEXT, ref_slug TEXT,
        source_url TEXT, fetched_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_listings_slug ON listings(slug);
    CREATE INDEX IF NOT EXISTS idx_auctions_ref ON auction_lots(brand, reference);
    """)
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
                 r.get("case_material"), r.get("url"),
                 f"{index.get('source_url','')}", index.get("fetched_at")))
            n_refs += 1

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
            cur.execute(
                "INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (l.get("id"), slug, l.get("title"), l.get("price_usd"),
                 l.get("currency"), l.get("condition"), l.get("box_papers"),
                 l.get("case_material"), l.get("case_size_mm"),
                 l.get("movement"), l.get("year"), l.get("merchant_slug"),
                 l.get("merchant_name"),
                 1 if l.get("available") else 0,
                 l.get("image_url"), l.get("detail_url"), l.get("buy_url"),
                 src, ts))
            n_list += 1
        for a in payload.get("auction_lots") or []:
            cur.execute(
                "INSERT OR REPLACE INTO auction_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("slug"), a.get("brand"), a.get("reference"),
                 a.get("model"), a.get("case_material"), a.get("hammer_usd"),
                 a.get("year_sold"), a.get("venue"), a.get("url"),
                 slug, src, ts))
            n_auc += 1

    # full auction dataset -> auction_lots (all brands, for joins).
    # Do not clobber rows already linked to a reference (ref_slug set).
    full = load_raw("index", "auctions_full")
    if full:
        for a in (full.get("payload") or {}).get("auction_lots") or []:
            cur.execute(
                "INSERT OR IGNORE INTO auction_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("slug"), a.get("brand"), a.get("reference"),
                 a.get("model"), a.get("case_material"), a.get("hammer_usd"),
                 a.get("year_sold"), a.get("venue"), a.get("url"), None,
                 full.get("source_url"), full.get("fetched_at")))
            n_auc += 1

    db.commit()
    print(f"ledger: {n_refs} references, {n_list} listings, {n_auc} auction lots")


if __name__ == "__main__":
    main()