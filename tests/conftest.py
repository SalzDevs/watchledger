"""Shared test fixtures: build a mini ledger through the real market pipeline."""

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from src.schema import SCHEMA
import src.market as market

FETCHED_AT = time.time() - 3600  # fresh: within the 72h freshness window


def insert_ref(db, slug="hostile-ref", brand="Rolex", ref="126610LN",
               model="Submariner", material="Steel", url="https://example.com/ref"):
    db.execute(
        "INSERT INTO references_meta VALUES (?,?,?,?,?,?,?,?)",
        (slug, brand, ref, model, material, url,
         "https://example.com/src", FETCHED_AT))


def insert_listing(db, lid, slug, title, price, merchant, image_url=None,
                   buy_url=None, detail_url=None, cond="Excellent",
                   bp="full_set", year=2024, mat="Steel", avail=1, exact=1,
                   size_mm=41.0):
    db.execute(
        """INSERT OR REPLACE INTO listings
           (id, slug, title, price_usd, currency, condition, box_papers,
            case_material, case_size_mm, movement, year, merchant_slug,
            merchant_name, available, image_url, detail_url, buy_url, exact,
            source_url, fetched_at, source_name, source_listing_id,
            canonical_url, listing_fingerprint)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lid, slug, title, price, "USD", cond, bp, mat, size_mm, None, year,
         "dealer", merchant, avail, image_url, detail_url, buy_url, exact,
         "https://example.com/src", FETCHED_AT, "mostexpensivewatches.net",
         lid, buy_url or detail_url,
         market.fingerprint_from_url(buy_url or detail_url or "")))


def run_pipeline(db, slug="hostile-ref", ref="126610LN", brand="Rolex",
                 model="Submariner", material="Steel"):
    """Run the same phase 2-6 steps build_db runs, for a single reference."""
    refs_meta = [(slug, brand, ref, model, material, "https://example.com/ref",
                  "https://example.com/src", FETCHED_AT)]
    all_listings = db.execute("SELECT * FROM listings").fetchall()
    market.build_canonical(db, refs_meta, all_listings)
    refs = {slug: {"ref_key": market.normalize_reference(ref),
                   "active_key": "", "brand": brand}}
    for r in db.execute("SELECT reference_id, configuration_key, active "
                        "FROM watch_configuration").fetchall():
        if r[2]:
            refs[r[0]]["active_key"] = r[1]
    market.match_all(db, refs)
    market.cluster_listings(db, all_listings)
    market.register_sources(
        db, "mostexpensivewatches.net",
        [("mostexpensivewatches.net", "mostexpensivewatches.net")])
    elig = market.eligibility(db, slug)
    cfg = db.execute("SELECT id FROM watch_configuration WHERE reference_id=? "
                     "AND active=1", (slug,)).fetchone()
    cfg_id = cfg[0] if cfg else slug
    calc = market.calculate_market(db, slug, elig)
    market.save_snapshot(db, cfg_id, calc, elig)
    db.commit()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    yield conn
    conn.close()