"""Shared SQLite schema for the WatchLedger ledger and market engine.

The ledger is a derived, deterministic view of the raw payloads under data/raw.
This schema is used by build_db (production), by report/server (readers), and
by the test suite (isolated fixtures), so the columns stay in one place.

Phase 2-6 entities (design brief):
  watch_reference / watch_configuration  canonical matching
  listing_cluster                        deduplication
  source_fetch / listing_observation     history
  market_snapshot                        reproducible calculations
  source                                 source registry (Phase 10)
  watch_users / watchlist_item / alert_preference / alert_delivery  tracking
"""

SCHEMA = """
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
    exact INTEGER DEFAULT 0,
    source_url TEXT, fetched_at REAL,
    source_name TEXT DEFAULT 'mostexpensivewatches.net',
    source_listing_id TEXT,
    canonical_url TEXT,
    canonical_reference_id TEXT,
    canonical_configuration_id TEXT,
    match_level TEXT DEFAULT 'unverified',
    match_confidence REAL,
    match_reason TEXT,
    review_state TEXT DEFAULT 'auto',
    listing_cluster_id TEXT,
    listing_fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS auction_lots (
    slug TEXT PRIMARY KEY,
    brand TEXT, reference TEXT, model TEXT, case_material TEXT,
    hammer_usd REAL, year_sold INTEGER, venue TEXT,
    lot_url TEXT, ref_slug TEXT,
    source_url TEXT, fetched_at REAL
);

CREATE TABLE IF NOT EXISTS watch_reference (
    id TEXT PRIMARY KEY,
    brand TEXT, family TEXT, model_name TEXT,
    reference_number TEXT, reference_normalized TEXT,
    production_start_year INTEGER, production_end_year INTEGER,
    source_url TEXT, fetched_at REAL
);

CREATE TABLE IF NOT EXISTS watch_configuration (
    id TEXT PRIMARY KEY,
    reference_id TEXT NOT NULL,
    configuration_key TEXT NOT NULL,
    case_material TEXT, dial TEXT, bracelet TEXT, bezel TEXT,
    case_size_mm REAL, production_variant TEXT,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS listing_cluster (
    id TEXT PRIMARY KEY,
    canonical_reference_id TEXT,
    representative_listing_id TEXT,
    cluster_confidence REAL,
    cluster_basis TEXT,
    created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS source_fetch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT, fetched_at REAL, source_url TEXT,
    payload_hash TEXT, fetch_status TEXT
);

CREATE TABLE IF NOT EXISTS listing_observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT, source_fetch_id INTEGER,
    observed_at REAL, price_original REAL, currency TEXT,
    price_usd REAL, availability INTEGER, content_hash TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuration_id TEXT, calculated_at REAL,
    methodology_version TEXT,
    input_cluster_ids_json TEXT,
    excluded_cluster_ids_json TEXT,
    exclusion_reasons_json TEXT,
    lower_range REAL, typical_price REAL, upper_range REAL,
    coverage_score TEXT, diversity_score TEXT, freshness_score TEXT,
    confidence_state TEXT
);

CREATE TABLE IF NOT EXISTS source (
    id TEXT PRIMARY KEY, name TEXT, domain TEXT, access_method TEXT,
    permission_status TEXT, image_usage_status TEXT,
    attribution_requirements TEXT, last_terms_reviewed_at REAL
);

CREATE TABLE IF NOT EXISTS watch_users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    unsubscribe_token TEXT NOT NULL,
    confirm_token TEXT,
    confirmed INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS watchlist_item (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL, reference_slug TEXT NOT NULL,
    created_at REAL, active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alert_preference (
    id TEXT PRIMARY KEY,
    watchlist_item_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alert_delivery (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL, alert_type TEXT NOT NULL,
    reference_slug TEXT NOT NULL, payload TEXT,
    delivered_at REAL, status TEXT DEFAULT 'queued'
);

CREATE INDEX IF NOT EXISTS idx_listings_slug ON listings(slug);
CREATE INDEX IF NOT EXISTS idx_listings_exact ON listings(slug, exact);
CREATE INDEX IF NOT EXISTS idx_listings_match ON listings(slug, match_level);
CREATE INDEX IF NOT EXISTS idx_listings_cluster ON listings(listing_cluster_id);
CREATE INDEX IF NOT EXISTS idx_auctions_ref ON auction_lots(brand, reference);
CREATE INDEX IF NOT EXISTS idx_wr_normalized ON watch_reference(reference_normalized);
CREATE INDEX IF NOT EXISTS idx_wc_ref ON watch_configuration(reference_id);
CREATE INDEX IF NOT EXISTS idx_cluster_ref ON listing_cluster(canonical_reference_id);
CREATE INDEX IF NOT EXISTS idx_obs_listing ON listing_observation(listing_id);
CREATE INDEX IF NOT EXISTS idx_snap_cfg ON market_snapshot(configuration_id);
CREATE INDEX IF NOT EXISTS idx_watch_user ON watchlist_item(user_id);
CREATE INDEX IF NOT EXISTS idx_watch_ref ON watchlist_item(reference_slug);
"""